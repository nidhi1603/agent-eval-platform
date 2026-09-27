"""Development diagnostic: short agent-only continuations from saved conversation prefixes.

For each case, the environment is restored by replaying every tool call the saved trajectory made before
the prefix end (in a fresh environment built through tau2's official path), and the agent is given the
messages it had seen up to that point. It then continues alone: its tool calls are executed in the
restored environment and their results fed back, until it sends a text message (to the customer) or
`max_rounds` tool rounds pass. No user simulator is called, and nothing is graded by tau2: this measures
the next decision at a known failure point, not task success.

Cases are chosen after observing failures, so results are a development diagnostic on known failures,
never a reliability estimate. Scoring rules are fixed in the case file before any run.

    uv run --extra bench python -m bench.continuation experiments/D001_plan.json --approved-usd X
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT, pins

JSON_ARG_KEYS = {"arguments"}


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
    """Argument values that appear nowhere in what the agent had seen (possible inventions)."""
    return [v for v in _leaves(arguments) if v not in ignore and v not in context]


def underlying(call: dict) -> str:
    if call["name"] in ("call_discoverable_agent_tool", "unlock_discoverable_agent_tool"):
        return call["arguments"].get("agent_tool_name") or call["name"]
    if call["name"] == "give_discoverable_user_tool":
        return call["arguments"].get("discoverable_tool_name") or call["name"]
    return call["name"]


def continue_case(case: dict, variant: str, llm: str, llm_args: dict, max_rounds: int = 8) -> dict:
    """Run one continuation. The caller installs spending control (bench.budget.install)."""
    from tau2.data_model.message import MultiToolMessage
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench import agent as agent_mod

    trace = json.loads((REPO_ROOT / case["source_trace"]).read_text())
    end = case["prefix_end"]
    task = get_tasks(pins.DOMAIN, task_ids=[case["task_id"]])[0]
    config = TextRunConfig(domain=pins.DOMAIN, retrieval_config=case.get("retrieval_config", "bm25"))
    env = restore_env(config, task, trace["messages"], end)
    seen = agent_visible(trace["messages"], end)
    assert seen and seen[-1]["role"] in ("user", "tool"), "a prefix must end with the customer's or a tool's message"
    agent = agent_mod.factory(tools=env.get_tools(), domain_policy=env.get_policy(), variant=variant,
                              llm=llm, llm_args=dict(llm_args))
    history = to_tau2(seen)
    state = agent.get_init_state(history[:-1])
    incoming = history[-1]
    context = json.dumps(seen)
    calls, final_text, rounds = [], None, 0
    while True:
        msg, state = agent.generate_next_message(incoming, state)
        if not msg.tool_calls:
            final_text = msg.content
            break
        if rounds >= max_rounds:
            break
        rounds += 1
        results = []
        for tc in msg.tool_calls:
            res = env.get_response(tc)
            call = {"round": rounds, "name": tc.name, "arguments": tc.arguments, "error": bool(res.error),
                    "result": (res.content or "")[:600]}
            call["underlying"] = underlying(call)
            call["values_not_in_context"] = unsupported_values(tc.arguments, context, set(case.get("ignore_values", [])))
            calls.append(call)
            context += json.dumps(call["result"])
            results.append(res)
        incoming = results[0] if len(results) == 1 else MultiToolMessage(role="tool", tool_messages=results)
    return {"case": case["id"], "variant": variant, "calls": calls, "final_text": final_text,
            "rounds": rounds, "stopped": "text" if final_text is not None else "max_rounds",
            "score": score(case, calls, final_text)}


def score(case: dict, calls: list[dict], final_text: str | None) -> dict:
    """Automatic parts of the pre-registered scoring. Text behaviours are labelled by reading."""
    executed_ok = [c for c in calls if c["name"] == "call_discoverable_agent_tool" and not c["error"]
                   and "Error" not in c["result"][:40]]
    ok_tools = {c["underlying"] for c in executed_ok}
    s = {
        "unlocked": sorted({c["underlying"] for c in calls if c["name"] == "unlock_discoverable_agent_tool"}),
        "executed_discoverable": sorted(ok_tools),
        "given_to_user": sorted({c["underlying"] for c in calls if c["name"] == "give_discoverable_user_tool"}),
        "possible_invented_values": [v for c in calls for v in c["values_not_in_context"]],
        "tool_errors": sum(c["error"] for c in calls),
    }
    if case.get("success_any_of"):
        s["invoked_expected_tool"] = bool(ok_tools & set(case["success_any_of"]))
    if case.get("forbidden"):
        proposed = {c["underlying"] for c in calls if c["name"] == "call_discoverable_agent_tool"}
        s["forbidden_proposed"] = sorted(proposed & set(case["forbidden"]))
        s["forbidden_executed"] = sorted(ok_tools & set(case["forbidden"]))
    return s


def main(argv=None) -> int:
    from bench.budget import BoundViolation, Budget, BudgetExceeded, Limits, install, load_prices

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plan", type=Path)
    p.add_argument("--approved-usd", type=float, required=True, help="must equal the plan's budget_usd_total")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments")
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    if plan.get("budget_usd_total") is None or abs(a.approved_usd - plan["budget_usd_total"]) > 1e-9:
        raise SystemExit(f"approved ${a.approved_usd} does not match the plan's ${plan.get('budget_usd_total')}")
    import litellm
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
    litellm.suppress_debug_info = True
    pins.verify_benchmark()
    out_dir = a.out_dir / f"{plan['batch_id']}_runs"
    out_dir.mkdir(exist_ok=False)
    budget = Budget(a.approved_usd, load_prices(), out_dir / "ledger.jsonl")
    cases = {c["id"]: c for c in plan["cases"]}
    rows = []
    stopped = False
    with install(budget, Limits()):
        for item in plan["runs"]:
            if stopped:
                rows.append({"case": item["case"], "variant": item["variant"], "sample": item.get("sample", 0),
                             "status": "not_run", "reason": "allocation exhausted or bound violated"})
                continue
            case = cases[item["case"]]
            try:
                r = continue_case(case, item["variant"], plan["settings"]["agent_model"], plan["settings"]["agent_args"],
                                  plan["settings"].get("max_rounds", 8))
                r["sample"] = item.get("sample", 0)
            except Exception as e:  # noqa: BLE001 - record, never retry
                r = {"case": item["case"], "variant": item["variant"], "sample": item.get("sample", 0),
                     "status": "error", "error": f"{type(e).__name__}: {e}"[:500]}
                stopped = isinstance(e, (BudgetExceeded, BoundViolation))
            rows.append(r)
            (out_dir / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
    summary = {"batch_id": plan["batch_id"], "finished_at": datetime.now(timezone.utc).isoformat(),
               "spend": budget.summary(), "results": rows}
    (a.out_dir / f"{plan['batch_id']}_results.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary["spend"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
