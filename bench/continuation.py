"""Development diagnostic: short agent-only continuations from saved conversation prefixes.

For each case, the environment is restored by replaying every tool call the saved trajectory made before
the prefix end (in a fresh environment built through tau2's official path), and the agent is given the
messages it had seen up to that point. It then continues alone: its tool calls are executed in the
restored environment and their results fed back, until it sends a text message (to the customer) or
`max_rounds` tool rounds pass. No user simulator is called, and nothing is graded by tau2: this measures
the next decision at a known failure point, not task success.

Evidence handling:
- Every generated proposal is recorded, including one reached at the round limit and drafts withheld by a
  guard or pre-send check (from the agent's harness events). Records are written to disk as they grow, so a
  later error or budget stop never erases earlier actions.
- Tool results are kept in full; the full text is the evidence for scoring and provenance. Previews are
  separate and only for reading.
- Success is judged from receipts (tau2 returns failures as text starting "Error", often with error=False).
- Outcomes are separated: proposed, blocked, attempted, successful, and final state (read from the
  environment after the continuation).

Cases are chosen after observing failures, so results are a development diagnostic on known failures,
never a reliability estimate. Scoring rules are fixed in the case file before any run.

    uv run --extra bench python -m bench.continuation experiments/D001_plan.json --approved-usd X
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT, pins

JSON_ARG_KEYS = {"arguments"}
PREVIEW = 300


class PlanError(Exception):
    """The plan does not match what would run. Raised before any network call."""


def agent_visible(trace_messages: list[dict], end: int) -> list[dict]:
    """The messages the agent itself had seen before `end`: its own messages, its tool results, and the
    customer's text. The customer's own tool calls and results go to the user side, not the agent."""
    out = []
    for m in trace_messages[:end]:
        if m["role"] == "assistant":
            out.append(m)
        elif m["role"] == "tool" and m.get("requestor") == "assistant":
            out.append(m)
        elif m["role"] == "user" and not m.get("tool_calls"):
            out.append(m)
    return out


def to_tau2(messages: list[dict]):
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage

    out = []
    for m in messages:
        if m["role"] == "assistant":
            calls = [ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"], requestor="assistant")
                     for c in m.get("tool_calls") or []] or None
            out.append(AssistantMessage(role="assistant", content=m.get("content"), tool_calls=calls))
        elif m["role"] == "tool":
            out.append(ToolMessage(id=m["tool_call_id"], role="tool", content=m.get("content"),
                                   requestor="assistant", error=bool(m.get("error"))))
        else:
            out.append(UserMessage(role="user", content=m.get("content")))
    return out


def restore_env(config, task, trace_messages: list[dict], end: int):
    from tau2.data_model.message import ToolCall

    from bench.independence import fresh_env

    env = fresh_env(config, task)
    for m in trace_messages[:end]:
        for c in m.get("tool_calls") or []:
            env.get_response(ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"],
                                      requestor="assistant" if m["role"] == "assistant" else "user"))
    return env


def prefix_steps(trace_messages: list[dict], end: int) -> list[dict]:
    return [{"requestor": "assistant" if m["role"] == "assistant" else "user", "name": c["name"],
             "arguments": c["arguments"], "checked": False}
            for m in trace_messages[:end] for c in m.get("tool_calls") or []]


def _leaves(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in JSON_ARG_KEYS and isinstance(v, str):
                try:
                    yield from _leaves(json.loads(v))
                    continue
                except json.JSONDecodeError:
                    pass
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)
    elif obj is not None:
        yield str(obj)


def unsupported_values(arguments: dict, context: str, ignore: set[str]) -> list[str]:
    """Argument values that appear nowhere in what the agent had seen (a review flag, not a verdict)."""
    return [v for v in _leaves(arguments) if v not in ignore and v not in context]


def underlying(name: str, arguments: dict) -> str:
    if name in ("call_discoverable_agent_tool", "unlock_discoverable_agent_tool"):
        return (arguments or {}).get("agent_tool_name") or name
    if name == "give_discoverable_user_tool":
        return (arguments or {}).get("discoverable_tool_name") or name
    return name


def receipt_ok(name: str, content: str) -> bool:
    """Whether the tool result is a success receipt. tau2 reports most failures as text, not as errors."""
    text = (content or "").lstrip()
    if name == "unlock_discoverable_agent_tool":
        return text.startswith("Tool unlocked:")
    if name == "give_discoverable_user_tool":
        return text.startswith("Tool given to user:")
    return not text.startswith("Error")


def _inner_args(arguments: dict) -> dict:
    inner = (arguments or {}).get("arguments") or "{}"
    try:
        inner = json.loads(inner) if isinstance(inner, str) else dict(inner)
    except (json.JSONDecodeError, TypeError):
        inner = {}
    return inner if isinstance(inner, dict) else {}


def _table_digest(db, table: str) -> str:
    rows = getattr(getattr(db, table, None), "data", None) or {}
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def final_state(case: dict, env, before: dict) -> dict:
    """Case-specific final-state facts, read from the environment after the continuation."""
    out = {}
    spec = case.get("completion_state")
    if spec:
        rows = getattr(getattr(env.tools.db, spec["table"]), "data")
        want = spec.get("fields") or {spec["field"]: spec["value"]}  # every field must match
        done = [rid for rid in spec["records"]
                if isinstance(rows.get(rid), dict) and all(rows[rid].get(k) == v for k, v in want.items())]
        out["completed_targets"] = done
        out["completion"] = f"{len(done)}/{len(spec['records'])}"
    for table in case.get("watch_tables", []):
        out[f"{table}_changed"] = _table_digest(env.tools.db, table) != before.get(table)
    return out


def continue_case(case: dict, variant: str, llm: str, llm_args: dict, max_rounds: int = 8,
                  guard_rules: tuple = (), nudges: tuple = (), budget=None, record_path: Path | None = None,
                  evidence_mode: str | None = None) -> dict:
    """Run one continuation. The caller installs spending control (bench.budget.install). Always returns a
    record; on an exception the record keeps every action taken so far, with status 'error'."""
    from tau2.data_model.message import MultiToolMessage
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench import agent as agent_mod

    rec: dict = {"case": case["id"], "variant": variant, "guard_rules": list(guard_rules), "nudges": list(nudges),
                 "evidence_mode": evidence_mode,
                 "status": "started", "proposals": [], "calls": [], "final_text": None, "rounds": 0}
    seq_start = len(budget.calls) if budget is not None else None

    def flush():
        if record_path is not None:
            record_path.write_text(json.dumps(rec, indent=2, default=str) + "\n")

    agent = env = task = config = None
    before: dict = {}
    trace_messages: list[dict] = []
    try:
        trace = json.loads((REPO_ROOT / case["source_trace"]).read_text())
        trace_messages = trace["messages"]
        end = case["prefix_end"]
        task = get_tasks(pins.DOMAIN, task_ids=[case["task_id"]])[0]
        config = TextRunConfig(domain=pins.DOMAIN, retrieval_config=case.get("retrieval_config", "bm25"))
        env = restore_env(config, task, trace_messages, end)
        before = {t: _table_digest(env.tools.db, t) for t in case.get("watch_tables", [])}
        seen = agent_visible(trace_messages, end)
        if not seen or seen[-1]["role"] not in ("user", "tool"):
            raise PlanError("a prefix must end with the customer's or a tool's message")
        agent = agent_mod.factory(tools=env.get_tools(), domain_policy=env.get_policy(), variant=variant,
                                  guard_rules=tuple(guard_rules), nudges=tuple(nudges), evidence_mode=evidence_mode,
                                  llm=llm, llm_args=dict(llm_args))
        if guard_rules or nudges or evidence_mode:
            from bench import guard

            agent.guard_toolkit = env.tools
            agent.agent_tool_names = frozenset(env.tools.get_discoverable_tools())
            agent.discoverable_names = agent.agent_tool_names | frozenset(env.user_tools.get_discoverable_tools())
            if any(guard.RULES[r]["evidence"] == "environment_db" for r in guard_rules):
                agent.guard_db = env.tools.db
        history = to_tau2(seen)
        state = agent.get_init_state(history[:-1])
        incoming = history[-1]
        context = json.dumps(seen)
        while True:
            msg, state = agent.generate_next_message(incoming, state)
            prop = {"n": len(rec["proposals"]), "text": msg.content,
                    "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls or []],
                    "executed": False}
            rec["proposals"].append(prop)
            flush()
            if not msg.tool_calls:
                rec["final_text"], rec["status"] = msg.content, "text"
                break
            if rec["rounds"] >= max_rounds:
                prop["not_executed_reason"] = "round limit reached"
                rec["status"] = "max_rounds"
                break
            rec["rounds"] += 1
            prop["executed"] = True
            results = []
            for tc in msg.tool_calls:
                res = env.get_response(tc)
                content = res.content or ""
                call = {"round": rec["rounds"], "name": tc.name, "arguments": tc.arguments,
                        "underlying": underlying(tc.name, tc.arguments), "error_flag": bool(res.error),
                        "ok": receipt_ok(tc.name, content) and not res.error,
                        "result": content, "result_preview": content[:PREVIEW],
                        "values_not_in_context": unsupported_values(tc.arguments, context,
                                                                    set(case.get("ignore_values", [])))}
                rec["calls"].append(call)
                context += json.dumps(content)  # the model sees the full result, so provenance uses it too
                results.append(res)
                flush()
            incoming = results[0] if len(results) == 1 else MultiToolMessage(role="tool", tool_messages=results)
    except Exception as e:  # noqa: BLE001 - keep the evidence; the caller decides whether to stop
        rec["status"], rec["error_type"], rec["error"] = "error", type(e).__name__, f"{type(e).__name__}: {e}"[:500]
    finally:
        rec["harness_events"] = getattr(agent, "events", []) if agent is not None else []
        if budget is not None:
            rec["ledger_calls"] = [c.seq for c in budget.calls[seq_start:]]
        if env is not None:
            rec["final_state"] = final_state(case, env, before)
        rec["score"] = score(case, rec)
        if env is not None and task is not None:
            rec["exposure"] = _exposure(config, task, trace_messages, case["prefix_end"], rec["calls"])
        flush()
    return rec


def _exposure(config, task, trace_messages, end, calls) -> dict:
    """Answer-dependence of the continuation's own tool outputs, replaying prefix + continuation.
    A failed or inconclusive check is 'unknown', never 'not observed'."""
    from bench.independence import check_sequence

    try:
        steps = prefix_steps(trace_messages, end) + [
            {"requestor": "assistant", "name": c["name"], "arguments": c["arguments"], "checked": True} for c in calls]
        r = check_sequence(config, task, steps)
        dep = r["agent_visible_outputs_depending_on_hidden_reference"]
        r["status"] = "exposed" if dep else "not_observed" if r["conclusive"] else "unknown"
        return r
    except Exception as e:  # noqa: BLE001
        return {"status": "unknown", "error": f"{type(e).__name__}: {e}"[:300]}


def score(case: dict, rec: dict) -> dict:
    """Automatic parts of the pre-registered scoring, at separate levels. Text behaviours are labelled by reading.

    proposed   every tool call the agent generated: executed, stopped by the round limit, or withheld/blocked by
               the harness (from its events)
    blocked    proposals a permission rule blocked
    attempted  calls sent to the environment
    successful attempted calls whose result is a success receipt
    final      facts read from the environment after the continuation (rec["final_state"])

    `values_for_review` are argument values that appear nowhere in what the agent had seen, compared against
    full tool results. A review flag, not a verdict: calculations, reformatting and policy constants are new too."""
    calls = rec.get("calls", [])
    proposed = [(tc["name"], tc["arguments"]) for p in rec.get("proposals", []) for tc in p["tool_calls"] if not p["executed"]]
    proposed += [(c["name"], c["arguments"]) for c in calls]
    blocked = []
    for e in rec.get("harness_events", []):
        if e.get("event") == "blocked":
            blocked.append((e["tool_call"], e["arguments"]))
            proposed.append((e["tool_call"], e["arguments"]))
        elif e.get("event") == "nudged":
            proposed += [(tc["name"], tc["arguments"]) for tc in e.get("draft_tool_calls_full", [])]
        elif e.get("event") == "evidence_assessed" and e.get("enforced") and not e.get("allowed"):
            call = {"name": "call_discoverable_agent_tool",
                    "arguments": e["arguments"]} if isinstance(e.get("arguments"), dict) and "agent_tool_name" in e["arguments"] else None
            pair = (call["name"], call["arguments"]) if call else (e["tool"], e.get("arguments") or {})
            blocked.append(pair)
            proposed.append(pair)
    names = lambda pairs: sorted({underlying(n, a) for n, a in pairs})  # noqa: E731
    discoverable_calls = lambda cs: [c for c in cs if c["name"] == "call_discoverable_agent_tool"]  # noqa: E731
    ok_calls = [c for c in calls if c["ok"]]
    s = {
        "proposed_tools": names(proposed),
        "blocked_tools": names(blocked),
        "attempted_discoverable": sorted({c["underlying"] for c in discoverable_calls(calls)}),
        "successful_discoverable": sorted({c["underlying"] for c in discoverable_calls(ok_calls)}),
        "unlocked_ok": sorted({c["underlying"] for c in ok_calls if c["name"] == "unlock_discoverable_agent_tool"}),
        "given_to_user_ok": sorted({c["underlying"] for c in ok_calls if c["name"] == "give_discoverable_user_tool"}),
        "values_for_review": [v for c in calls for v in c["values_not_in_context"]],
        "failed_receipts": sum(not c["ok"] for c in calls),
        "status": rec.get("status"),
    }
    if case.get("success_tool"):  # a successful call of this tool with these exact argument values
        want = case.get("success_args", {})
        args_of = lambda c: _inner_args(c["arguments"]) if c["name"] == "call_discoverable_agent_tool" else (c["arguments"] or {})  # noqa: E731
        s["success"] = any(c["underlying"] == case["success_tool"] and c["name"] != "unlock_discoverable_agent_tool"
                           and all(args_of(c).get(k) == v for k, v in want.items())
                           for c in ok_calls)
    if case.get("progress_calls"):  # useful progress: a successful call on the correct customer's relevant resource
        args_of_ = lambda c: _inner_args(c["arguments"]) if c["name"] == "call_discoverable_agent_tool" else (c["arguments"] or {})  # noqa: E731
        s["progress"] = any(c["underlying"] == p["tool"] and c["name"] != "unlock_discoverable_agent_tool"
                            and all(args_of_(c).get(k) == v for k, v in p.get("args", {}).items())
                            for p in case["progress_calls"] for c in ok_calls)
    elif case.get("progress_any_of"):  # intermediate progress, never reported as completion
        s["progress"] = bool(set(s["successful_discoverable"]) & set(case["progress_any_of"]))
    if case.get("completion_state"):
        fs = rec.get("final_state") or {}
        s["completion_final_state"] = fs.get("completion")  # from the environment, not from calls made
    if case.get("forbidden"):
        f = set(case["forbidden"])
        s["forbidden_proposed"] = sorted(set(s["proposed_tools"]) & f)
        s["forbidden_blocked"] = sorted(set(s["blocked_tools"]) & f)
        s["forbidden_attempted"] = sorted(set(s["attempted_discoverable"]) & f)
        s["forbidden_successful"] = sorted(set(s["successful_discoverable"]) & f)
        for table in case.get("watch_tables", []):
            s[f"final_{table}_changed"] = (rec.get("final_state") or {}).get(f"{table}_changed")
    if case.get("valid_next_step_tools"):  # automatic part (successful handoff); explaining is labelled by reading
        s["valid_next_step_tool_given_ok"] = bool(set(s["given_to_user_ok"]) & set(case["valid_next_step_tools"]))
    return s


# ---- preflight --------------------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(plan: dict, approved_usd: float) -> dict:
    """Everything that must hold before any network call. Returns the manifest to save first."""
    from bench import variants

    if plan.get("budget_usd_total") is None or abs(approved_usd - plan["budget_usd_total"]) > 1e-9:
        raise PlanError(f"approved ${approved_usd} does not match the plan's ${plan.get('budget_usd_total')}")
    for name, recorded in plan.get("variants", {}).items():
        actual = variants.record(name)["sha256"]
        if recorded.get("sha256") != actual:
            raise PlanError(f"variant {name!r}: plan sha256 {recorded.get('sha256')} != file sha256 {actual}")
    cases = {c["id"]: c for c in plan["cases"]}
    arms = plan.get("arms", {})
    split = pins.load_split()
    for c in plan["cases"]:
        if c["task_id"] not in split["dev"]:
            raise PlanError(f"case {c['id']}: {c['task_id']} is not a development task")
        if not (REPO_ROOT / c["source_trace"]).is_file():
            raise PlanError(f"case {c['id']}: source trace missing")
    for item in plan["runs"]:
        if item["case"] not in cases:
            raise PlanError(f"run references unknown case {item['case']!r}")
        if item["variant"] not in plan.get("variants", {}):
            raise PlanError(f"run references variant {item['variant']!r} that the plan does not fingerprint")
        if item.get("arm") is not None and item["arm"] not in arms:
            raise PlanError(f"run references undefined arm {item['arm']!r}")
    for name, arm in arms.items():
        if arm.get("evidence") not in (None, "record", "enforce"):
            raise PlanError(f"arm {name!r}: evidence must be null, 'record' or 'enforce'")
    return {
        "batch_id": plan["batch_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "approved_usd": approved_usd,
        "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
        "variants": {n: variants.record(n) for n in plan.get("variants", {})},
        "source_traces": {c["id"]: {"path": c["source_trace"], "sha256": _sha(REPO_ROOT / c["source_trace"])}
                          for c in plan["cases"]},
        "settings": plan["settings"],
        "arms": arms,
        "benchmark": pins.verify_benchmark(),
        "provenance": pins.provenance(),
    }


def main(argv=None) -> int:
    from bench.budget import Budget, Limits, install, load_prices

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plan", type=Path)
    p.add_argument("--approved-usd", type=float, required=True, help="must equal the plan's budget_usd_total")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments")
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    try:
        manifest = preflight(plan, a.approved_usd)
    except PlanError as e:
        raise SystemExit(f"preflight failed, nothing was sent: {e}") from e
    import litellm
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
    litellm.suppress_debug_info = True
    out_dir = a.out_dir / f"{plan['batch_id']}_runs"
    out_dir.mkdir(exist_ok=False)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")  # saved first
    budget = Budget(a.approved_usd, load_prices(), out_dir / "ledger.jsonl")
    cases = {c["id"]: c for c in plan["cases"]}
    rows, stopped = [], False
    with install(budget, Limits()):
        for k, item in enumerate(plan["runs"]):
            base = {"run": k, "case": item["case"], "variant": item["variant"], "arm": item.get("arm"),
                    "sample": item.get("sample", 0)}
            if stopped:
                rows.append({**base, "status": "not_run", "reason": "allocation exhausted or bound violated"})
                continue
            arm = plan.get("arms", {}).get(item["arm"], {}) if item.get("arm") is not None else {}
            r = continue_case(cases[item["case"]], item["variant"], plan["settings"]["agent_model"],
                              plan["settings"]["agent_args"], plan["settings"].get("max_rounds", 8),
                              tuple(arm.get("guard_rules", ())), tuple(arm.get("nudges", ())),
                              budget=budget, record_path=out_dir / f"run_{k:02d}.json",
                              evidence_mode=arm.get("evidence"))
            rows.append({**base, **r})
            stopped = r.get("error_type") in ("BudgetExceeded", "BoundViolation")
            (out_dir / "results.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
    summary = {"batch_id": plan["batch_id"], "finished_at": datetime.now(timezone.utc).isoformat(),
               "manifest": str((out_dir / "manifest.json").relative_to(a.out_dir)),
               "by_status": {st: sum(r.get("status") == st for r in rows) for st in {r.get("status") for r in rows}},
               "spend": budget.summary(), "results": rows}
    (a.out_dir / f"{plan['batch_id']}_results.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("by_status", "spend")}, indent=2, default=str))
    return 3 if any(r.get("status") in ("error", "not_run") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
