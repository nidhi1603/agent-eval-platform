"""Run a pre-registered batch of dev tasks sequentially under one shared spending allocation.

    uv run --extra bench python -m bench.batch experiments/S002_plan.json --approved-usd 1.00 [--workers 4]

The plan file (task list, settings, allocation) is committed before running. Sequentially, each run's cap
is the allocation minus the conservative upper-bound spend of earlier runs. In parallel (--workers N), each
run reserves the plan's per_run_cap_usd before it starts, so concurrent runs never overspend together.
Finished rows are journaled (experiments/<batch>_journal.jsonl) as they land, and a rerun resumes from the
journal instead of repeating conversations. No task is retried. Every scheduled task gets an
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


def _exposure(trace: dict) -> int | None:
    """How many agent-visible outputs in this run depended on hidden reference data (None if unchecked)."""
    indep = trace.get("answer_independence")
    if not indep or "agent_visible_outputs_depending_on_hidden_reference" not in indep:
        return None
    return len(indep["agent_visible_outputs_depending_on_hidden_reference"])


def _exposure_status(trace: dict) -> str:
    """exposed | not_observed | unknown. A failed or inconclusive diagnostic is unknown, never 'no exposure'."""
    seen = _exposure(trace)
    if seen:
        return "exposed"
    if seen is None or (trace.get("answer_independence") or {}).get("conclusive") is not True:
        return "unknown"
    return "not_observed"


def _harness_activity(trace: dict) -> dict | None:
    """Counts of harness v1 interventions in one run (None when the harness was off)."""
    h = trace.get("harness")
    if not h:
        return None
    events = h.get("events") or []
    held: dict[str, int] = {}
    for e in events:
        if e.get("event") == "held":
            held[e["gate"]] = held.get(e["gate"], 0) + 1
    return {"held_by_gate": held, "released": sum(e.get("event") == "released" for e in events),
            "withheld": sum(e.get("event") == "withheld" for e in events), "regenerations": h.get("regenerations"),
            "tools_offered": len(h.get("offered") or [])}


def schedule(plan: dict) -> list[dict]:
    """The ordered list of runs. A plain plan lists tasks (one baseline run each); a paired plan lists
    runs as {task_id, arm}, with each arm's settings overrides in plan["arms"]."""
    if "runs" in plan:
        unknown = {r["arm"] for r in plan["runs"]} - set(plan["arms"])
        if unknown:
            raise SystemExit(f"runs reference undefined arms {sorted(unknown)}")
        return [dict(r) for r in plan["runs"]]
    return [{"task_id": t, "arm": None} for t in plan["tasks"]]


def _run_one(item: dict, settings: dict, cap: float, out_dir: str | None) -> dict:
    """One scheduled conversation under its own spending cap. Top level, so a worker process can run it."""
    task_id, arm = item["task_id"], item["arm"]
    s = settings
    opts = RunOptions(
        task_id=task_id, agent_model=s["agent_model"], agent_llm_args=dict(s["agent_args"]),
        user_model=s["user_model"], user_llm_args=dict(s["user_args"]),
        retrieval_config=s["retrieval_config"], seed=s["seed"], max_steps=s["max_steps"],
        budget_usd=cap, limits=Limits(), agent_variant=s.get("agent_variant", "baseline"),
        agent_tool_adapter=s.get("tool_adapter"),
        agent_harness=s.get("harness"),
        **({"out_dir": Path(out_dir)} if out_dir else {}),
    )
    trace, path = run(opts)
    spend = (trace.get("spend") or {}).get("incurred") or {}
    return {
        "task_id": task_id,
        "arm": arm,
        "attempt": item.get("attempt", 0),
        "tool_adapter": (((trace.get("config") or {}).get("agent") or {}).get("tool_adapter")),
        "harness": (((trace.get("config") or {}).get("agent") or {}).get("harness")),
        "harness_activity": _harness_activity(trace),
        "agent_variant": (((trace.get("config") or {}).get("agent") or {}).get("variant") or {}),
        "status": "finished" if trace.get("execution", {}).get("finished") else "interrupted_or_failed",
        "run_id": trace.get("run_id"),
        "official_reward": (trace.get("evaluation") or {}).get("reward"),
        "termination_reason": trace.get("termination_reason"),
        "attribution": trace.get("attribution"),
        "persisted": trace.get("persisted"),
        "cap_given_usd": cap,
        "spend_upper_bound_usd": spend.get("upper_bound_usd"),
        "spend_cache_aware_usd": spend.get("cache_aware_estimate_usd"),
        "unresolved_reservations_usd": spend.get("unresolved_reservations_usd"),
        "counts": trace.get("counts"),
        "flags": (trace.get("research_eligibility") or {}).get("flags"),
        # exposure is recorded alongside the official outcome; exposed runs are never dropped from the batch
        "answer_dependent_outputs_seen": _exposure(trace),
        "exposure_status": _exposure_status(trace),
        "answer_independence_conclusive": (trace.get("answer_independence") or {}).get("conclusive"),
        "duration_s": trace.get("duration_s"),
        "trace": str(path),
    }


def _key(item: dict) -> tuple:
    return item["task_id"], item.get("arm"), item.get("attempt", 0)


def run_batch(plan: dict, approved_usd: float, out_dir: Path | None = None, workers: int = 1,
              journal: Path | None = None) -> dict:
    """Run every scheduled conversation, never admitting spend beyond `approved_usd`.

    workers == 1: one at a time; each run's cap is whatever the allocation has left (the original behaviour).
    workers > 1: separate processes. Before a run starts, the plan's `per_run_cap_usd` is reserved from the
    allocation; when it ends, its conservative upper-bound spend replaces the reservation. A run starts only if
    the unreserved allocation covers a full reservation, so concurrent runs can never overspend together.
    `journal` (a .jsonl file) receives each finished row as it lands; rows already in it are not run again (resume)
    and their spend counts against the allocation."""
    if abs(approved_usd - plan["budget_usd_total"]) > 1e-9:
        raise SystemExit(f"approved ${approved_usd} does not match the plan's ${plan['budget_usd_total']}")
    schedule_ = schedule(plan)
    order = {_key(it): i for i, it in enumerate(schedule_)}
    done: dict[tuple, dict] = {}
    if journal and journal.exists():
        for line in journal.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done[_key(row)] = row
    spent_upper = sum(r.get("spend_upper_bound_usd") or 0.0 for r in done.values())
    todo = [it for it in schedule_ if _key(it) not in done]

    def settings_for(item):
        return {**plan["settings"], **(plan["arms"][item["arm"]] if item["arm"] else {})}

    def record(row):
        done[_key(row)] = row
        if journal:
            with journal.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")

    rows_not_run = []
    if workers <= 1:
        for item in todo:
            remaining = round(approved_usd - spent_upper, 6)
            if remaining <= 0:
                rows_not_run.append({"task_id": item["task_id"], "arm": item["arm"], "attempt": item.get("attempt", 0),
                                     "status": "not_run", "reason": "batch allocation exhausted"})
                continue
            row = _run_one(item, settings_for(item), remaining, str(out_dir) if out_dir else None)
            spent_upper += row.get("spend_upper_bound_usd") or 0.0
            record(row)
    else:
        import multiprocessing as mp
        from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

        per_run = plan.get("per_run_cap_usd")
        if not per_run:
            raise SystemExit("parallel runs need the plan's per_run_cap_usd (the reservation for each conversation)")
        queue, inflight, reserved = list(todo), {}, 0.0
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
            while queue or inflight:
                while queue and len(inflight) < workers and approved_usd - spent_upper - reserved >= per_run - 1e-9:
                    item = queue.pop(0)
                    fut = pool.submit(_run_one, item, settings_for(item), per_run, str(out_dir) if out_dir else None)
                    inflight[fut] = item
                    reserved += per_run
                if not inflight:
                    break  # nothing running and nothing affordable: the rest cannot start
                finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in finished:
                    item = inflight.pop(fut)
                    reserved -= per_run
                    try:
                        row = fut.result()
                    except Exception as e:  # noqa: BLE001 - a crashed worker still leaves an outcome row
                        row = {"task_id": item["task_id"], "arm": item["arm"], "attempt": item.get("attempt", 0),
                               "status": "interrupted_or_failed", "reason": f"worker error: {type(e).__name__}: {e}"[:300],
                               "spend_upper_bound_usd": per_run}  # unknown spend counts as the full reservation
                    spent_upper += row.get("spend_upper_bound_usd") or 0.0
                    record(row)
        rows_not_run = [{"task_id": it["task_id"], "arm": it["arm"], "attempt": it.get("attempt", 0),
                         "status": "not_run", "reason": "batch allocation exhausted"} for it in queue]
    rows = sorted(list(done.values()) + rows_not_run, key=lambda r: order.get(_key(r), 10**9))
    return {
        "pairs": _pairs(rows) if "runs" in plan and len(plan.get("arms") or {}) == 2 else None,
        "comparisons": _comparisons(rows, plan["comparisons"]) if plan.get("comparisons") else None,
        "passes_by_arm": {arm: sum(1 for r in rows if r.get("arm") == arm and r["status"] == "finished"
                                   and (r.get("official_reward") or 0) >= 1.0) for arm in (plan.get("arms") or {})},
        "batch_id": plan["batch_id"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "approved_usd": approved_usd,
        "workers": workers,
        "spend_upper_bound_usd": round(spent_upper, 6),
        "scheduled": len(rows),
        "by_status": {st: sum(r["status"] == st for r in rows) for st in {r["status"] for r in rows}},
        "results": rows,
        "exposed_runs": sum(r.get("exposure_status") == "exposed" for r in rows),
        "exposure_unknown_runs": sum(r.get("exposure_status") == "unknown" for r in rows),
        "note": ("Exploratory sample; first consequential errors are labelled by reading each trace, not by this script. "
                 "Every scheduled trial keeps its official outcome; exposed runs are reported, not removed."),
    }


def _classify(a_row: dict | None, b_row: dict | None) -> str:
    """How arm B did against arm A on one (task, attempt)."""
    rewards = [(r.get("official_reward") if r and r["status"] == "finished" else None) for r in (a_row, b_row)]
    if any(v is None for v in rewards):
        return "incomplete pair"
    a, b = (v >= 1.0 for v in rewards)
    return {(False, True): "improved", (True, False): "regressed", (True, True): "both pass",
            (False, False): "both fail"}[(a, b)]


def _comparisons(rows: list[dict], comparisons: list[str]) -> dict:
    """For each pre-registered "B vs A": paired outcomes per (task, attempt), and their counts."""
    groups: dict[tuple, dict] = {}
    for r in rows:
        groups.setdefault((r["task_id"], r.get("attempt", 0)), {})[r["arm"]] = r
    out = {}
    for comp in comparisons:
        b, a = [x.strip() for x in comp.split(" vs ")]
        per = [{"task_id": t, "attempt": att, "pair": _classify(arms.get(a), arms.get(b))}
               for (t, att), arms in groups.items()]
        counts = {k: sum(x["pair"] == k for x in per) for k in ("improved", "regressed", "both pass", "both fail",
                                                                  "incomplete pair")}
        out[comp] = {"counts": counts, "pairs": per}
    return out


def _pairs(rows: list[dict]) -> list[dict]:
    """Per task, the outcome of each arm, and a paired classification. Incomplete pairs are kept and
    labelled, never dropped. Only official rewards are compared here; behaviour is read from traces."""
    by_task: dict[tuple, dict] = {}
    for r in rows:  # a pair is one task and one attempt: repeated attempts are separate pairs, never merged
        by_task.setdefault((r["task_id"], r.get("attempt", 0)), {})[r["arm"]] = r
    out = []
    for (task_id, attempt), arms in by_task.items():
        rewards = {a: (r.get("official_reward") if r["status"] == "finished" else None) for a, r in arms.items()}
        names = sorted(arms)
        if len(names) != 2 or any(v is None for v in rewards.values()):
            kind = "incomplete pair"
        else:
            base = next((n for n in names if n == "baseline"), names[0])
            other = next(n for n in names if n != base)
            b, o = rewards[base] >= 1.0, rewards[other] >= 1.0
            kind = {(False, True): "improved", (True, False): "regressed",
                    (True, True): "both pass", (False, False): "both fail"}[(b, o)]
        out.append({"task_id": task_id, "attempt": attempt, "rewards": rewards, "pair": kind})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plan", type=Path)
    p.add_argument("--approved-usd", type=float, required=True, help="must equal the plan's budget_usd_total")
    p.add_argument("--workers", type=int, default=1, help="parallel conversations (needs per_run_cap_usd in the plan)")
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    journal = REPO_ROOT / "experiments" / f"{plan['batch_id']}_journal.jsonl"
    summary = run_batch(plan, a.approved_usd, workers=a.workers, journal=journal)
    out = REPO_ROOT / "experiments" / f"{plan['batch_id']}_results.json"
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("batch_id", "spend_upper_bound_usd", "by_status")}, indent=2))
    for r in summary["results"]:
        print(r["task_id"], r.get("arm"), r["status"], r.get("official_reward"), r.get("termination_reason"),
              (r.get("attribution") or {}).get("cause"), r.get("spend_upper_bound_usd"))
    for pr in summary.get("pairs") or []:
        print("pair", pr["task_id"], pr["pair"], pr["rewards"])
    for comp, res in (summary.get("comparisons") or {}).items():
        print("comparison", comp, res["counts"])
    print("passes by arm", summary.get("passes_by_arm"))
    print("results:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
