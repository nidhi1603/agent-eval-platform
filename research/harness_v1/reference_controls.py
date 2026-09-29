"""Offline negative control for harness v1 ($0): does any check fire on CORRECT behaviour?

For every dev task, a scripted agent performs the task's reference actions (the benchmark's own solution), in
order, as a careful agent would: it searches the knowledge base three times first, looks the customer up and reads
the clock before logging verification, and then reads the customer's card accounts and card transactions (base
tools) and their bank accounts (a discoverable read). The scripted customer performs the reference customer actions and reads out the card digits the agent will
need, as a customer who has just looked them up would. Each
script runs twice through the real tau2 path with the official evaluator: baseline agent and harness v1.

Pass condition (Stage 0 gate): no hard check fires, and harness v1 gets the same official reward as the baseline.
Reference actions are read here only to build the correct-behaviour script; the harness itself never sees them.

    uv run --extra bench python research/harness_v1/reference_controls.py [task_id ...]
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401
from bench import pins  # noqa: E402
from bench.run import RunOptions, run  # noqa: E402
from bench.scripted import AGENT_MODEL, USER_MODEL  # noqa: E402

ACCOUNTS = "get_all_user_accounts_by_user_id_3847"
GENERIC_QUERIES = ["identity verification procedure", "transfer to a human agent policy"]


def _inner(action) -> dict:
    args = dict(action.arguments)
    if "arguments" in args:
        try:
            return {**args, **json.loads(args["arguments"])}
        except (TypeError, ValueError):
            return args
    return args


def script_for(task) -> dict:
    acts = task.evaluation_criteria.actions or []
    names = [a.arguments.get("agent_tool_name") or a.arguments.get("discoverable_tool_name") for a in acts]
    first_tool = next((n for n in names if n), None)
    queries = GENERIC_QUERIES + [first_tool.rsplit("_", 1)[0].replace("_", " ") if first_tool else "account help"]
    agent = [{"call": "KB_search", "args": {"query": q}} for q in queries]
    digits = sorted({str(v) for x in acts if x.requestor == "assistant" for k, v in _inner(x).items()
                     if "last_4" in k or "last_four" in k})
    user = [{"say": "Hi, I need help with my account." + (f" My card's last 4 digits are {', '.join(digits)}."
                                                          if digits else "")}]
    segments, cur = [], None
    for a in acts:
        side = "agent" if a.requestor == "assistant" else "user"
        if cur is None or cur[0] != side:
            cur = (side, [])
            segments.append(cur)
        cur[1].append(a)
    for side, seg in segments:
        steps = []
        for a in seg:
            args = dict(a.arguments)
            if side == "agent" and a.name == "log_verification":
                steps.append({"call": "get_user_information_by_id", "args": {"user_id": args.get("user_id")}})
                steps.append({"call": "get_current_time", "args": {}})
            steps.append({"call": a.name, "args": args})
            if side == "agent" and a.name == "log_verification":
                for base in ("get_credit_card_accounts_by_user", "get_credit_card_transactions_by_user"):
                    steps.append({"call": base, "args": {"user_id": args.get("user_id")}})
                # the reference omits some reads a real agent needs (task_069 closes an existing account whose id only
                # this lookup returns); unlocking and reading change nothing graded
                steps.append({"call": "unlock_discoverable_agent_tool", "args": {"agent_tool_name": ACCOUNTS}})
                steps.append({"call": "call_discoverable_agent_tool", "args": {
                    "agent_tool_name": ACCOUNTS, "arguments": json.dumps({"user_id": args.get("user_id")})}})
        if side == "agent":
            agent += steps + [{"say": "Done. Is there anything else?"}]
        else:
            user += steps + [{"say": "OK, thanks."}]
    user.append({"say": "That's all. ###STOP###"})
    # the customer speaks after every agent text reply; pad so neither side runs out
    return {"description": f"MOCK reference-behaviour control for {task.id}", "agent": agent + [{"say": "Goodbye."}] * 3,
            "user": user + [{"say": "###STOP###"}] * 3}


def _agent_tokens(trace) -> int:
    """Input tokens the agent's calls sent (the scripted model counts them with a real tokenizer)."""
    return sum(e.get("input_tokens") or 0 for e in (trace.get("spend") or {}).get("ledger") or []
               if e.get("role") == "agent" and e.get("kind") == "chat")


def run_one(task_id, script, harness, tmp):
    path = tmp / f"{task_id}_{'h' if harness is not None else 'b'}.json"
    path.write_text(json.dumps(script))
    opts = RunOptions(task_id=task_id, agent_model=AGENT_MODEL, user_model=USER_MODEL, retrieval_config="bm25",
                      scripted=path, out_dir=tmp / "runs", agent_harness=harness,
                      budget_usd=20.0)  # scripted runs use FAKE prices; the cap only bounds the mock ledger
    trace, _ = run(opts)
    return trace


def main(argv):
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    ids = argv or pins.load_split()["dev"]
    rows = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for tid in ids:
            task = get_tasks(pins.DOMAIN, task_ids=[tid])[0]
            s = script_for(task)
            b = run_one(tid, s, None, tmp)
            h = run_one(tid, s, {}, tmp)
            ev = (h.get("harness") or {}).get("events") or []
            fired = [e for e in ev if e["event"] in ("held", "withheld", "released")]
            soft_fired = any(e.get("gate") == "search_before_giving_up" for e in fired)
            if soft_fired:
                # a soft advisory makes the model generate again, which consumes the next scripted step and
                # misaligns the script; rerun with only the hard checks to test them and the reward
                h_soft = h
                h = run_one(tid, s, {"gates": ["clock_before_verification", "verification_before_write",
                                                 "ids_observed"]}, tmp)
                ev = ((h.get("harness") or {}).get("events") or []) + [
                    e for e in (h_soft.get("harness") or {}).get("events") or [] if e.get("gate") == "search_before_giving_up"]
                fired = [e for e in ev if e["event"] in ("held", "withheld", "released")]
            row = {"task": tid, "baseline_reward": (b.get("evaluation") or {}).get("reward"),
                   "harness_reward": (h.get("evaluation") or {}).get("reward"),
                   "baseline_error": (b.get("error") or {}).get("message") if isinstance(b.get("error"), dict) else b.get("error"),
                   "harness_error": (h.get("error") or {}).get("message") if isinstance(h.get("error"), dict) else h.get("error"),
                   "soft_advisory_fired": soft_fired,
                   "fired": [{k: e.get(k) for k in ("event", "gate", "gates", "detail")} for e in fired],
                   "agent_input_tokens": {"baseline": _agent_tokens(b), "harness": _agent_tokens(h)},
                   "tools_offered": len((h.get("harness") or {}).get("offered") or []),
                   "checker_errors": sum(e["event"] == "checker_error" for e in ev)}
            rows.append(row)
            print(tid, row["baseline_reward"], row["harness_reward"], row["tools_offered"],
                  round(row["agent_input_tokens"]["harness"] / max(row["agent_input_tokens"]["baseline"], 1), 2),
                  [f.get("gate") or f.get("gates") for f in row["fired"]], (row["harness_error"] or "")[:120], flush=True)
    out = ROOT / "research" / "harness_v1" / "reference_controls.json"
    if not argv:
        out.write_text(json.dumps(rows, indent=1, default=str))
    same = sum(r["baseline_reward"] == r["harness_reward"] for r in rows)
    hard = sum(any(f.get("gate") != "search_before_giving_up" and f.get("event") == "held" for f in r["fired"]) or
               any(f.get("event") == "withheld" for f in r["fired"]) for r in rows)
    b_tok = sum(r["agent_input_tokens"]["baseline"] for r in rows)
    h_tok = sum(r["agent_input_tokens"]["harness"] for r in rows)
    print(f"\nsame reward {same}/{len(rows)}; tasks with a hard-check firing: {hard}; "
          f"agent input tokens harness/baseline = {h_tok / max(b_tok, 1):.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
