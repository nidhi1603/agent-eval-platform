"""Run a pre-registered batch of dev tasks sequentially under one shared spending allocation.

    uv run --extra bench python -m bench.batch experiments/S002_plan.json --approved-usd 1.00

The plan file (task list, settings, allocation) is committed before running. Each run's cap is the
allocation minus the conservative upper-bound spend of earlier runs, so runs never overlap and the
batch never admits spend beyond the allocation. No task is retried. Every scheduled task gets an
outcome: a finished run, an interrupted run, or "not_run" when nothing was left to admit a call.
Results go to experiments/<batch_id>_results.json.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT
from bench.budget import Limits
from bench.run import RunOptions, run


def run_batch(plan: dict, approved_usd: float, out_dir: Path | None = None) -> dict:
    if abs(approved_usd - plan["budget_usd_total"]) > 1e-9:
        raise SystemExit(f"approved ${approved_usd} does not match the plan's ${plan['budget_usd_total']}")
    s = plan["settings"]
    spent_upper = 0.0
    rows = []
    for task_id in plan["tasks"]:
        remaining = round(approved_usd - spent_upper, 6)
        if remaining <= 0:
            rows.append({"task_id": task_id, "status": "not_run", "reason": "batch allocation exhausted"})
            continue
        opts = RunOptions(
            task_id=task_id, agent_model=s["agent_model"], agent_llm_args=dict(s["agent_args"]),
            user_model=s["user_model"], user_llm_args=dict(s["user_args"]),
            retrieval_config=s["retrieval_config"], seed=s["seed"], max_steps=s["max_steps"],
            budget_usd=remaining, limits=Limits(), **({"out_dir": out_dir} if out_dir else {}),
        )
        trace, path = run(opts)
        spend = (trace.get("spend") or {}).get("incurred") or {}
        spent_upper += spend.get("upper_bound_usd") or 0.0
        rows.append({
            "task_id": task_id,
            "status": "finished" if trace.get("execution", {}).get("finished") else "interrupted_or_failed",
            "run_id": trace.get("run_id"),
            "official_reward": (trace.get("evaluation") or {}).get("reward"),
            "termination_reason": trace.get("termination_reason"),
            "attribution": trace.get("attribution"),
            "persisted": trace.get("persisted"),
            "cap_given_usd": remaining,
            "spend_upper_bound_usd": spend.get("upper_bound_usd"),
            "spend_cache_aware_usd": spend.get("cache_aware_estimate_usd"),
            "unresolved_reservations_usd": spend.get("unresolved_reservations_usd"),
            "counts": trace.get("counts"),
            "flags": (trace.get("research_eligibility") or {}).get("flags"),
            "trace": str(path),
        })
    return {
        "batch_id": plan["batch_id"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "approved_usd": approved_usd,
        "spend_upper_bound_usd": round(spent_upper, 6),
        "scheduled": len(plan["tasks"]),
        "by_status": {st: sum(r["status"] == st for r in rows) for st in {r["status"] for r in rows}},
        "results": rows,
        "note": "Exploratory sample; first consequential errors are labelled by reading each trace, not by this script.",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plan", type=Path)
    p.add_argument("--approved-usd", type=float, required=True, help="must equal the plan's budget_usd_total")
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    summary = run_batch(plan, a.approved_usd)
    out = REPO_ROOT / "experiments" / f"{plan['batch_id']}_results.json"
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("batch_id", "spend_upper_bound_usd", "by_status")}, indent=2))
    for r in summary["results"]:
        print(r["task_id"], r["status"], r.get("official_reward"), r.get("termination_reason"),
              (r.get("attribution") or {}).get("cause"), r.get("spend_upper_bound_usd"))
    print("results:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
