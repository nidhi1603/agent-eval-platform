"""Next-message probe of reason-code grounding (P003; development diagnostic, after the transfer-table review).

Question: when a transfer is held for a reason-code re-check, does giving the model the bank's reason-code document
(doc 042, the tier table) make it choose the policy-correct code more often than the SAME re-check request alone?

Each case is a saved transfer_to_human_agents proposal (research/transfers/, fixed selection rule in the plan). The
model gets exactly its history up to and including that proposal, then the tool result for the held transfer:
  control    REQUEST                  (re-check the code and call the transfer again)
  treatment  REQUEST + doc 042 text   (the same request, with the tier document)
Other calls in the same proposal get the harness's usual "not executed" result. Everything else is the original
call's: system prompt (tau2's, unmodified), tool list, model and reasoning setting. One model call per sample; the
reply is recorded and scored, never executed. Nothing is graded by tau2.

History: a harness run's saved model_view (held drafts included), or for a standard-agent run the messages the
agent itself received (bench.continuation.agent_visible). Reconstruction is checked before any call: model
messages align one-to-one with the original run's agent calls, and the tool list hashes to the tools_sha256 the
ledger recorded for the call that proposed the transfer.

Score per sample: the first transfer_to_human_agents call's `reason`. CORRECT if it equals the case's policy target
(the readers' adjudicated applicable code); a missing transfer call, an invalid code or a text-only reply is a
failure. Cases are selected development decisions, not a rate estimate.

    uv run --extra bench python -m bench.code_probe experiments/P003_plan.json --approved-usd X
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT, pins
from bench.hold_probe import PlanError, _sha, _tau2

TRANSFER = "transfer_to_human_agents"
ARMS = ("control", "treatment")
TIER_DOC_ID = "doc_bank_accounts_bank_accounts_(general)_042"
REQUEST = ("Not executed yet: before this transfer is sent, re-check its reason code. Choose the single most accurate "
           "reason code for this customer's situation, then call transfer_to_human_agents again with that reason and "
           "your summary.")
OTHER_HELD = "Not executed: another call in the same message was held by a harness check."


def tier_document() -> str:
    d = json.loads((pins.documents_dir() / f"{TIER_DOC_ID}.json").read_text())
    return f"{d.get('title', '')}\n\n{d.get('content', '')}".strip()


def valid_codes() -> set[str]:
    import re

    return set(re.findall(r"^\|\s*([a-z_]+)\s*\|", tier_document(), re.M)) - {"reason_code"}


def feedback(arm: str) -> str:
    if arm == "control":
        return REQUEST
    return (REQUEST + f"\n\nThe bank's reason-code policy ({TIER_DOC_ID}) follows; select from the highest tier that "
            "applies.\n\n" + tier_document())


def score(reply: dict, target: str, codes: set[str]) -> dict:
    calls = [c for c in reply.get("tool_calls") or [] if c["name"] == TRANSFER]
    if not calls:
        return {"reason": None, "outcome": "no_transfer_call", "correct": False}
    reason = (calls[0].get("arguments") or {}).get("reason")
    if reason not in codes:
        return {"reason": reason, "outcome": "invalid_code", "correct": False}
    return {"reason": reason, "outcome": "transfer_call", "correct": reason == target}


class Case:
    """One saved transfer proposal, with everything needed to rebuild the model's input at that point."""

    def __init__(self, spec: dict):
        from loguru import logger
        from tau2.data_model.simulation import TextRunConfig
        from tau2.runner.helpers import get_tasks

        from bench.continuation import agent_visible
        from bench.independence import fresh_env

        logger.remove()
        self.spec = spec
        self.trace = json.loads((REPO_ROOT / spec["source_trace"]).read_text())
        traj = self.trace["messages"]
        i = spec["trajectory_index"]
        call_id = spec["call_id"]
        if traj[i]["role"] != "assistant" or call_id not in [c["id"] for c in traj[i].get("tool_calls") or []]:
            raise PlanError(f"case {spec['id']}: trajectory message {i} is not the transfer proposal")
        self.harness = ((self.trace.get("config") or {}).get("agent") or {}).get("harness")
        view = (self.trace.get("harness") or {}).get("model_view")
        if self.harness:
            ks = [k for k, m in enumerate(view or []) if m["role"] == "assistant"
                  and call_id in [c["id"] for c in m.get("tool_calls") or []]]
            if len(ks) != 1:
                raise PlanError(f"case {spec['id']}: the proposal is not found exactly once in the model view")
            self.view, k = view, ks[0]
        else:
            self.view = [dict(m) for m in agent_visible(traj, i + 1)]
            k = len(self.view) - 1
        self.k = k
        self.proposal = self.view[k]
        self.before = self.view[:k]
        self.task = get_tasks(pins.DOMAIN, task_ids=[spec["task_id"]])[0]
        self.env = fresh_env(TextRunConfig(domain=pins.DOMAIN, retrieval_config=spec["retrieval_config"]), self.task)
        self.agent_tools = frozenset(self.env.tools.get_discoverable_tools())
        self.user_tools = frozenset(self.env.user_tools.get_discoverable_tools())
        self.offered = self._offered() if self.harness else []
        from bench.harness import is_withheld_reply

        # Model calls in view order (as bench/verify_probe.py, D005): tau2's greeting, fixed replies, adapter unlock
        # turns and capability searches are not model calls, EXCEPT that a capability search triggered BEFORE ASKING
        # replaced a draft the model had generated (not in the view): it counts once, at its harness turn.
        cap_events = [e for e in (self.trace.get("harness") or {}).get("events") or [] if e.get("event") == "capability_search"]

        def positions(msgs):
            out, cap_seen = [], 0
            for j, m in enumerate(msgs):
                if m["role"] != "assistant" or j == 0 or is_withheld_reply(m.get("content")):
                    continue
                ids = [c["id"] for c in m.get("tool_calls") or []]
                if any(x.startswith("capability_") for x in ids):
                    if cap_seen < len(cap_events) and cap_events[cap_seen].get("trigger") == "before_asking":
                        out.append(j)
                    cap_seen += 1
                elif not any(x.startswith("adapter_unlock_") for x in ids):
                    out.append(j)
            return out

        calls = [e for e in (self.trace.get("spend") or {}).get("ledger") or []
                 if e.get("role") == "agent" and e.get("kind") == "chat" and e.get("status") == "ok"]
        full = self.view if self.harness else [dict(m) for m in agent_visible(traj, len(traj))]
        self.aligned = len(positions(full)) == len(calls)
        n = sum(1 for j in positions(full) if j <= k)
        self.proposing_call = calls[n - 1] if 0 < n <= len(calls) else None

    def _offered(self) -> list[str]:
        """Tools the adapter offered by the proposal (as research/d005/make_plan.py): names seen in KB results,
        minus mutating ones under auto_offer non_mutating, plus tools the model unlocked itself under
        expose_model_unlocks."""
        from bench.adapter import names_in_kb_results

        h = self.harness or {}
        offered = set(names_in_kb_results(_tau2(self.before), self.agent_tools))
        if h.get("auto_offer") == "non_mutating":
            effects = json.loads((REPO_ROOT / "research" / "h009" / "tool_effects.json").read_text())["tools"]
            offered = {n for n in offered if effects.get(n, {}).get("classification") != "mutating"}
        if h.get("expose_model_unlocks"):
            calls = {c["id"]: c for m in self.before if m["role"] == "assistant" for c in m.get("tool_calls") or []}
            offered |= {calls[m["tool_call_id"]]["arguments"].get("agent_tool_name") for m in self.before
                        if m["role"] == "tool" and m.get("tool_call_id") in calls
                        and calls[m["tool_call_id"]]["name"] == "unlock_discoverable_agent_tool"
                        and not m["tool_call_id"].startswith("adapter_unlock")
                        and (m.get("content") or "").startswith("Tool unlocked:")}
        return sorted(offered - {None})

    def tools_sha256(self) -> str:
        a = self.agent("probe", {})
        tools = list(a.tools) + [t for n, t in sorted((getattr(a, "offered", None) or {}).items())
                                 if n not in {x.name for x in a.tools}]
        return hashlib.sha256(json.dumps([t.openai_schema for t in tools], sort_keys=True).encode()).hexdigest()

    def checks(self) -> dict:
        params = (self.proposing_call or {}).get("request_params") or {}
        return {"model_messages_align_with_the_ledger": self.aligned,
                "tools_match_the_call_that_proposed_the_transfer": params.get("tools_sha256") == self.tools_sha256(),
                "proposal_has_the_transfer_call": self.spec["call_id"] in [c["id"] for c in self.proposal.get("tool_calls") or []]}

    def messages(self, arm: str) -> list[dict]:
        text = feedback(arm)
        results = [{"role": "tool", "tool_call_id": c["id"], "content": text if c["id"] == self.spec["call_id"] else OTHER_HELD,
                    "error": True} for c in self.proposal["tool_calls"]]
        return self.before + [self.proposal] + results

    def agent(self, model: str, llm_args: dict):
        from tau2.environment.tool import as_tool

        from bench import agent as agent_mod

        a = agent_mod.factory(tools=self.env.get_tools(), domain_policy=self.env.get_policy(), variant="baseline",
                              harness=self.harness, llm=model, llm_args=dict(llm_args))
        if self.harness:
            a.adapter_toolkit = self.env.tools
            a.agent_tool_names = self.agent_tools
            a.user_tool_names = self.user_tools
            a.offered = {n: as_tool(self.env.tools.tools[n]) for n in self.offered}
        return a


def probe(case: Case, arm: str, model: str, llm_args: dict, target: str, codes: set[str]) -> dict:
    """One next-message sample. The caller installs spending control (bench.budget.install)."""
    import tau2.agent.llm_agent as llm_agent_module

    from bench.guard import messages_as_dicts

    a = case.agent(model, llm_args)
    state = a.get_init_state()
    state.messages = _tau2(case.messages(arm))
    if case.harness:
        msg = a._generate(state)
    else:
        msg = llm_agent_module.generate(model=a.llm, tools=a.tools, messages=state.system_messages + state.messages,
                                        call_name="agent_response", **a.llm_args)
    reply = messages_as_dicts([msg])[0]
    return {"reply_text": reply.get("content"), "reply_tool_calls": reply.get("tool_calls") or [], **score(reply, target, codes)}


def preflight(plan: dict, approved_usd: float):
    if plan.get("budget_usd_total") is None or abs(approved_usd - plan["budget_usd_total"]) > 1e-9:
        raise PlanError(f"approved ${approved_usd} does not match the plan's ${plan.get('budget_usd_total')}")
    if hashlib.sha256(tier_document().encode()).hexdigest() != plan["tier_document_sha256"]:
        raise PlanError("the tier document changed since the plan was frozen")
    dev = set(pins.load_split()["dev"])
    codes = valid_codes()
    cases = {}
    for spec in plan["cases"]:
        if spec["task_id"] not in dev:
            raise PlanError(f"case {spec['id']}: not a development task")
        path = REPO_ROOT / spec["source_trace"]
        if not path.is_file() or _sha(path) != spec["trace_sha256"]:
            raise PlanError(f"case {spec['id']}: source trace missing or changed")
        if spec["target"] not in codes:
            raise PlanError(f"case {spec['id']}: target {spec['target']!r} is not a code in the tier document")
        c = Case(spec)
        bad = [k for k, ok in c.checks().items() if not ok]
        if bad:
            raise PlanError(f"case {spec['id']}: reconstruction check failed: {bad}")
        cases[spec["id"]] = c
    return ({"batch_id": plan["batch_id"], "created_at": datetime.now(timezone.utc).isoformat(), "approved_usd": approved_usd,
             "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
             "feedback": {arm: feedback(arm) for arm in ARMS}, "valid_codes": sorted(codes),
             "tools_sha256": {cid: c.tools_sha256() for cid, c in cases.items()},
             "benchmark": pins.verify_benchmark(), "provenance": pins.provenance()}, cases, codes)


def summarize(rows: list[dict], plan: dict) -> dict:
    """Case level: a case is CORRECT in an arm when a majority of its samples are correct (failures count as wrong)."""
    done = [r for r in rows if r.get("status") == "done"]
    per = {}
    for spec in plan["cases"]:
        cid = spec["id"]
        per[cid] = {"originally": "correct" if spec["originally_correct"] else "wrong", "task": spec["task_id"],
                    "target": spec["target"], "original_code": spec["original_code"]}
        for arm in ARMS:
            xs = [r for r in done if r["case"] == cid and r["arm"] == arm]
            per[cid][arm] = {"correct_samples": sum(r["correct"] for r in xs), "samples": len(xs),
                             "majority_correct": sum(r["correct"] for r in xs) * 2 > len(xs) if xs else None,
                             "codes": [r.get("reason") or r["outcome"] for r in xs]}
    wrong = [c for c, v in per.items() if v["originally"] == "wrong"]
    right = [c for c, v in per.items() if v["originally"] == "correct"]
    t_fix = sum(per[c]["treatment"]["majority_correct"] is True for c in wrong)
    t_all = sum(per[c]["treatment"]["majority_correct"] is True for c in per)
    c_all = sum(per[c]["control"]["majority_correct"] is True for c in per)
    t_break = [c for c in right if per[c]["treatment"]["majority_correct"] is not True]
    gate = {"G1_treatment_corrects_at_least_half_of_originally_wrong": f"{t_fix} of {len(wrong)}",
            "G1_met": t_fix * 2 >= len(wrong),
            "G2_treatment_more_correct_cases_than_control": f"{t_all} vs {c_all}", "G2_met": t_all > c_all,
            "G3_no_originally_correct_case_incorrect_under_treatment": t_break, "G3_met": not t_break}
    complete = all(per[c][arm]["samples"] == plan["samples_per_arm"] for c in per for arm in ARMS)
    verdict = ("INCOMPLETE" if not complete else
               "PASS" if gate["G1_met"] and gate["G2_met"] and gate["G3_met"] else "FAIL")
    pooled = {arm: {"samples": sum(r["arm"] == arm for r in done), "correct": sum(r["correct"] for r in done if r["arm"] == arm),
                    "outcomes": {o: sum(r["outcome"] == o for r in done if r["arm"] == arm)
                                 for o in ("transfer_call", "no_transfer_call", "invalid_code")}} for arm in ARMS}
    return {"verdict": verdict, "gate": gate, "pooled_samples": pooled, "per_case": per}


def main(argv=None, send=None, prices=None) -> int:
    from bench.budget import Budget, Limits, install, load_prices

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plan", type=Path)
    p.add_argument("--approved-usd", type=float, required=True, help="must equal the plan's budget_usd_total")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments")
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    try:
        manifest, cases, codes = preflight(plan, a.approved_usd)
    except PlanError as e:
        raise SystemExit(f"preflight failed, nothing was sent: {e}") from e
    if send is None:
        import litellm
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
        litellm.suppress_debug_info = True
    s = plan["settings"]
    out_dir = a.out_dir / f"{plan['batch_id']}_runs"
    out_dir.mkdir(exist_ok=False)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    budget = Budget(a.approved_usd, prices or load_prices(), out_dir / "ledger.jsonl", accounting=s.get("budget_accounting", "billed"))
    targets = {c["id"]: c["target"] for c in plan["cases"]}
    rows, stopped = [], False
    with install(budget, Limits(max_output_tokens=s["max_output_tokens"]), send=send):
        for k, item in enumerate(plan["runs"]):
            row = {"run": k, **item}
            if stopped:
                rows.append({**row, "status": "not_run", "reason": "allocation exhausted"})
                continue
            n0 = len(budget.calls)
            try:
                row.update(probe(cases[item["case"]], item["arm"], s["agent_model"], s["agent_args"], targets[item["case"]], codes),
                           status="done")
            except Exception as e:  # noqa: BLE001
                row.update(status="error", error=f"{type(e).__name__}: {e}"[:500])
                stopped = type(e).__name__ in ("BudgetExceeded", "BoundViolation")
            new = budget.calls[n0:]
            row["tools_sha256_sent"] = next((c.request_params.get("tools_sha256") for c in new), None)
            row["input_tokens"] = next((c.input_tokens for c in new if c.status == "ok"), None)
            rows.append(row)
            (out_dir / "results.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
    summary = {"batch_id": plan["batch_id"], "finished_at": datetime.now(timezone.utc).isoformat(),
               "by_status": {st: sum(r["status"] == st for r in rows) for st in {r["status"] for r in rows}},
               "fidelity": {"tools_sent_equal_original_request": all(r.get("tools_sha256_sent") == manifest["tools_sha256"][r["case"]]
                                                                     for r in rows if r["status"] == "done")},
               "result": summarize(rows, plan), "spend": budget.summary(), "results": rows}
    (a.out_dir / f"{plan['batch_id']}_results.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("by_status", "fidelity", "spend")}, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary["result"].items() if k != "per_case"}, indent=2))
    return 3 if any(r["status"] != "done" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
