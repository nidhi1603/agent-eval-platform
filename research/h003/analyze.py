"""H003 calibration analysis ($0). Uses the reference-progress rules of research/h002/analyze.py unchanged (imported,
not copied), and compares against H002's low-reasoning baseline on the same 5 tasks.

    uv run --extra bench python research/h003/analyze.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
from analyze import DOC, key, matched  # noqa: E402  (H002's committed matching rules)

TASKS = ["task_069", "task_058", "task_023", "task_089", "task_077"]


def row(r, task, cap):
    t = json.loads(Path(r["trace"]).read_text())
    msgs = t["messages"]
    results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
    calls, docs, transfers, searches = [], set(), 0, 0
    for m in msgs:
        for c in m.get("tool_calls") or []:
            res_m = results.get(c["id"]) or {}
            ok = not res_m.get("error") and not (res_m.get("content") or "").lstrip().startswith("Error")
            if ok:
                calls.append(key(m["role"] if m["role"] == "user" else "assistant", c["name"], c["arguments"]))
            if m["role"] == "assistant":
                if c["name"] == "KB_search":
                    searches += 1
                    docs |= set(DOC.findall(res_m.get("content") or ""))
                transfers += c["name"] == "transfer_to_human_agents"
    refs = task.evaluation_criteria.actions or []
    ok = [matched(a, calls) for a in refs]
    writes = [(a, o) for a, o in zip(refs, ok) if a.name == "call_discoverable_agent_tool"]
    agent = [e for e in t["spend"]["ledger"] if e.get("role") == "agent" and e.get("kind") == "chat"]
    req = set(task.required_documents or [])
    return {
        "task": r["task_id"], "arm": r["arm"], "status": r["status"], "reward": r.get("official_reward"),
        "termination": r.get("termination_reason"),
        "ref_matched": sum(ok), "ref_actions": len(refs),
        "ref_writes_matched": sum(o for _, o in writes), "ref_writes": len(writes),
        "first_unmatched": next((f"{a.requestor}:{key(a.requestor, a.name, a.arguments)[1]}"
                                 for a, o in zip(refs, ok) if not o), None),
        "searches": searches, "req_doc_recall": round(len(docs & req) / max(len(req), 1), 2),
        "transfers": transfers,
        "agent_calls": len(agent),
        "agent_output_tokens_max": max((e.get("output_tokens") or 0) for e in agent) if agent else 0,
        "agent_output_tokens_sum": sum((e.get("output_tokens") or 0) for e in agent),
        "cap_hits": sum(1 for e in agent if (e.get("output_tokens") or 0) >= cap),
        "empty_agent_messages": sum(1 for m in msgs if m["role"] == "assistant" and not m.get("content")
                                    and not m.get("tool_calls")),
        "cost_ub": r.get("spend_upper_bound_usd"), "cost_cache": r.get("spend_cache_aware_usd"),
        "duration_s": r.get("duration_s") or t.get("duration_s"),
    }


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=TASKS)}
    out = {"H003": [], "H002_baseline": []}
    for r in json.loads((ROOT / "experiments" / "H003_results.json").read_text())["results"]:
        out["H003"].append(row(r, tasks[r["task_id"]], 16384))
    for r in json.loads((ROOT / "experiments" / "H002_results.json").read_text())["results"]:
        if r["arm"] == "baseline" and r["task_id"] in TASKS and r.get("trace") and r["status"] != "not_run":
            out["H002_baseline"].append({**row(r, tasks[r["task_id"]], 4096), "attempt": r["attempt"]})
    (ROOT / "research" / "h003" / "diagnostics.json").write_text(json.dumps(out, indent=1))

    def summ(xs):
        n = len(xs)
        return {"n": n, "passes": sum(x["reward"] == 1.0 for x in xs),
                "ref_progress": round(sum(x["ref_matched"] / x["ref_actions"] for x in xs) / n, 2),
                "write_progress": round(sum(x["ref_writes_matched"] / max(x["ref_writes"], 1) for x in xs
                                            if x["ref_writes"]) / max(sum(1 for x in xs if x["ref_writes"]), 1), 2),
                "writes_matched_total": f"{sum(x['ref_writes_matched'] for x in xs)}/{sum(x['ref_writes'] for x in xs)}",
                "cap_hits": sum(x["cap_hits"] for x in xs), "transfers": sum(x["transfers"] for x in xs),
                "mean_cost_ub": round(sum(x["cost_ub"] for x in xs) / n, 3),
                "mean_cost_cache": round(sum(x["cost_cache"] or 0 for x in xs) / n, 3),
                "mean_duration_s": round(sum(x["duration_s"] or 0 for x in xs) / n, 1),
                "mean_agent_out_tokens": round(sum(x["agent_output_tokens_sum"] for x in xs) / n),
                "req_doc_recall": round(sum(x["req_doc_recall"] for x in xs) / n, 2)}

    print(json.dumps({k: summ(v) for k, v in out.items()}, indent=1))
    for k, xs in out.items():
        print(f"\n{k}")
        for x in xs:
            print(f"  {x['task']}{'#'+str(x['attempt']) if 'attempt' in x else ''}: reward={x['reward']} "
                  f"ref {x['ref_matched']}/{x['ref_actions']} writes {x['ref_writes_matched']}/{x['ref_writes']} "
                  f"first_miss={x['first_unmatched']} searches={x['searches']} recall={x['req_doc_recall']} "
                  f"transfers={x['transfers']} max_out={x['agent_output_tokens_max']} cap_hits={x['cap_hits']} "
                  f"empty={x['empty_agent_messages']} ${x['cost_ub']:.3f} {x['duration_s']}s")


if __name__ == "__main__":
    main()
