"""Development-split audit for answer-dependent agent-visible tool outputs. No model calls, no spend.

For every dev task (the held-out test split is never touched), two probe families are executed, call
by call, against three fresh environments built through tau2's official `_build_env_kwargs`:
real (the task), control (the task again: measures nondeterminism) and blind (the task with its
grading-only fields emptied: reference actions, NL assertions, communicate info, required documents).
Each call's agent-visible output is compared; stable-but-different-from-blind = answer-dependent.

Probe families (kept apart in the report because they differ in what they are built from):
  F  reference-free: tool calls that use no task content at all (current time, a fixed KB query,
     the discoverable-tool listing). A false-positive control: expected to never flag.
  R  REFERENCE-CONSTRUCTED: replays the task's reference actions (from its answer key) in order,
     with a `list_discoverable_agent_tools` probe after every discoverable agent call. Built from
     answer fields, so it is a diagnostic of the environment, never agent behaviour.

Removing answer fields is a diagnostic intervention; it does not grade anything. "No flag" means no
answer dependence was observed for the calls and states exercised here, nothing more.

    uv run --extra bench python -m bench.audit            # leaky (unchanged) and fixed environments
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from contextlib import nullcontext
from datetime import datetime, timezone

from bench import REPO_ROOT, fixes, pins
from bench.independence import blind_copy, fresh_env, normalize

LISTING = "list_discoverable_agent_tools"
REFERENCE_FREE_PROBES = [
    ("get_current_time", {}),
    ("KB_search", {"query": "referral program eligibility"}),
    (LISTING, {}),
]


def _probe_calls(task, family: str):
    """Yield (requestor, tool name, arguments) for one probe family."""
    if family == "F":
        for name, args in REFERENCE_FREE_PROBES:
            yield "assistant", name, args
        return
    for action in task.evaluation_criteria.actions or []:
        yield action.requestor, action.name, dict(action.arguments or {})
        if action.requestor == "assistant" and action.name == "call_discoverable_agent_tool":
            yield "assistant", LISTING, {}


def audit_task(config, task, family: str) -> dict:
    from tau2.data_model.message import ToolCall

    envs = {"real": fresh_env(config, task), "control": fresh_env(config, task),
            "blind": fresh_env(config, blind_copy(task))}
    calls, dependent, nondeterministic, errors = [], [], [], 0
    for i, (requestor, name, args) in enumerate(_probe_calls(task, family)):
        tc = ToolCall(id=f"probe_{family}_{i}", name=name, arguments=args, requestor=requestor)
        out = {k: env.get_response(tc) for k, env in envs.items()}
        text = {k: normalize(name, m.content) for k, m in out.items()}
        errors += bool(out["real"].error)
        calls.append({"i": i, "requestor": requestor, "tool": name, "error": out["real"].error})
        if text["real"] != text["control"]:
            nondeterministic.append({"i": i, "tool": name})
        elif requestor == "assistant" and text["real"] != text["blind"]:
            dependent.append({"i": i, "tool": name, "real": text["real"][:200], "blind": text["blind"][:200]})
    return {
        "family": family,
        "calls": len(calls),
        "agent_calls": sum(c["requestor"] == "assistant" for c in calls),
        "tools": dict(Counter(c["tool"] for c in calls)),
        "errors_in_real_env": errors,
        "states_exercised": len(calls) + 1,  # the initial state plus one state after each call
        "answer_dependent": dependent,
        "nondeterministic": nondeterministic,
        "conclusive": not nondeterministic,
    }


def run_audit(fixed: bool) -> dict:
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    split = pins.load_split()
    dev = split["dev"]
    assert not set(dev) & set(split["test"]), "dev and test overlap"
    config = TextRunConfig(domain=pins.DOMAIN, retrieval_config="bm25")
    tasks = get_tasks(pins.DOMAIN, task_ids=dev)
    ctx = fixes.listing_from_agent_state() if fixed else nullcontext()
    rows = []
    with ctx:
        for task in sorted(tasks, key=lambda t: t.id):
            rows.append({"task_id": task.id, "F": audit_task(config, task, "F"), "R": audit_task(config, task, "R")})
    return {"environment": fixes.FIX_NAME if fixed else "unchanged tau2 v1.0.1", "rows": rows}


def summarize(result: dict) -> dict:
    rows = result["rows"]
    groups = defaultdict(set)  # tool -> tasks where that tool's output depended on the answer key
    totals = Counter()
    tools_seen = set()
    for r in rows:
        for fam in ("F", "R"):
            a = r[fam]
            totals[f"{fam}_calls"] += a["calls"]
            totals[f"{fam}_agent_calls"] += a["agent_calls"]
            totals[f"{fam}_flagged_calls"] += len(a["answer_dependent"])
            totals[f"{fam}_nondeterministic_calls"] += len(a["nondeterministic"])
            totals[f"{fam}_errors_in_real_env"] += a["errors_in_real_env"]
            tools_seen |= set(a["tools"])
            for d in a["answer_dependent"]:
                groups[d["tool"]].add(r["task_id"])
    return {
        "environment": result["environment"],
        "tasks": len(rows),
        "totals": dict(totals),
        "tasks_flagged": sorted({r["task_id"] for r in rows if r["F"]["answer_dependent"] or r["R"]["answer_dependent"]}),
        # one entry per distinct mechanism (grouped by the tool whose output varies), not per task
        "defect_groups": {tool: {"tasks": sorted(ts), "count": len(ts)} for tool, ts in groups.items()},
        "tools_exercised": sorted(tools_seen),
        "tasks_with_discoverable_agent_calls_in_reference": sorted(
            r["task_id"] for r in rows if r["R"]["tools"].get("call_discoverable_agent_tool")),
    }


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    from loguru import logger

    logger.remove()
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "split": "dev", "retrieval_config": "bm25",
              "benchmark": pins.verify_benchmark()}
    for label, fixed in (("unchanged", False), ("fixed", True)):
        result = run_audit(fixed)
        report[label] = {"summary": summarize(result), "per_task": result["rows"]}
    out = REPO_ROOT / "results" / "audit_dev_split.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({k: report[k]["summary"] for k in ("unchanged", "fixed")}, indent=2))
    print("written:", out.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
