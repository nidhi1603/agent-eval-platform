"""H005 pilot analysis ($0): standard agent vs harness v1 under alltools (experiments/H005_plan.json).

Progress uses bench/metrics.py, where reads and writes are kept apart. Retrieval uses bench/kb_evidence.py on what
reached each model: the trajectory for the standard agent, which has no private history, and the harness's
model_view for v1. Reference actions and required documents are read only to score dev tasks.

    uv run --extra bench python research/h005/analyze.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
import bench  # noqa: E402,F401
from bench import kb_evidence, metrics  # noqa: E402

ARMS = ("baseline", "harness_v1")


def row(r, task, tool_type):
    base = {"task": r["task_id"], "arm": r["arm"], "status": r["status"], "reward": r.get("official_reward"),
            "cost_ub": r.get("spend_upper_bound_usd") or 0.0, "cost_cache": r.get("spend_cache_aware_usd") or 0.0,
            "duration_s": r.get("duration_s") or 0.0}
    if not r.get("trace"):
        return {**base, "traced": False}
    t = json.loads(Path(r["trace"]).read_text())
    msgs = t["messages"]
    view = (t.get("harness") or {}).get("model_view") or msgs
    obs = kb_evidence.observations(view)
    required = set(task.required_documents or [])
    full = {o.doc_id for o in obs if o.level == "full"}
    seen = {o.doc_id for o in obs if o.level in ("full", "partial")}
    calls = [(c["name"], c.get("arguments") or {}) for m in msgs if m["role"] == "assistant"
             for c in (m.get("tool_calls") or [])]
    full_ledger = (t.get("spend") or {}).get("ledger") or []
    ledger = [e for e in full_ledger if e.get("role") == "agent"]
    # cache-aware estimate, recomputed uniformly from the ledger: embeddings have no cached price (full price)
    base["cost_cache"] = round(sum((e.get("cost_with_cache_usd") if e.get("cost_with_cache_usd") is not None
                                    else (e.get("cost_usd") or 0.0)) for e in full_ledger), 6)
    h = t.get("harness") or {}
    return {**base, "traced": True, **metrics.progress(msgs, task.evaluation_criteria.actions or [], tool_type),
            "retrieval_calls": Counter(n for n, _ in calls if n in kb_evidence.RETRIEVAL_TOOLS),
            "docs_by_level": Counter(o.level for o in obs),
            "docs_by_tool_full": Counter(o.tool for o in obs if o.level == "full"),
            "req_recall_full": round(len(full & required) / max(len(required), 1), 3),
            "req_recall_full_or_partial": round(len(seen & required) / max(len(required), 1), 3),
            "req_missing": sorted(required - seen),
            "transfers": sum(n == "transfer_to_human_agents" for n, _ in calls),
            "held": sum(e.get("event") == "held" for e in h.get("events") or []),
            "withheld": sum(e.get("event") == "withheld" for e in h.get("events") or []),
            "tools_offered": len(h.get("offered") or []),
            "shell_audit": t.get("shell_audit"),
            "agent_in_tokens": sum(e.get("input_tokens") or 0 for e in ledger),
            "agent_out_tokens": sum(e.get("output_tokens") or 0 for e in ledger),
            "independence_conclusive": (t.get("answer_independence") or {}).get("conclusive")}


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks
    from tool_retrieval_probe import registry

    logger.remove()
    tool_type = registry()[1]
    path = ROOT / "experiments" / "H005_results.json"
    res = json.loads(path.read_text()) if path.exists() else {
        "status": "PARTIAL (journal)", "results": [r for r in (json.loads(x) for x in
                                                   (ROOT / "experiments" / "H005_journal.jsonl").read_text().splitlines() if x.strip())
                                        if r.get("kind") != "operator_stopped"]}
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted({r["task_id"] for r in res["results"]}))}
    rows = [row(r, tasks[r["task_id"]], tool_type) for r in res["results"]]
    pairs = []
    for tk in dict.fromkeys(x["task"] for x in rows):
        a = next((x for x in rows if x["task"] == tk and x["arm"] == "baseline"), None)
        b = next((x for x in rows if x["task"] == tk and x["arm"] == "harness_v1"), None)
        if not (a and b and a["status"] == b["status"] == "finished"):
            kind = "incomplete pair"
        else:
            pa, pb = (a["reward"] or 0) >= 1, (b["reward"] or 0) >= 1
            kind = {(False, True): "improved", (True, False): "regressed", (True, True): "both pass"}.get((pa, pb), "both fail")
        pairs.append({"task": tk, "pair": kind})
    complete = {p["task"] for p in pairs if p["pair"] != "incomplete pair"}

    def summ(arm):
        xs = [x for x in rows if x["arm"] == arm and x.get("traced")]
        n = max(len(xs), 1)
        dw = (sum(x["ref_discoverable_writes_matched"] for x in xs), sum(x["ref_discoverable_writes"] for x in xs))
        return {"n": len(xs), "passes_complete_pairs": sum((x["reward"] or 0) >= 1 for x in xs if x["task"] in complete),
                "discoverable_writes_pooled": f"{dw[0]}/{dw[1]}", "discoverable_write_progress": round(dw[0] / max(dw[1], 1), 3),
                "discoverable_reads_pooled": f"{sum(x['ref_discoverable_reads_matched'] for x in xs)}/{sum(x['ref_discoverable_reads'] for x in xs)}",
                "customer_actions_pooled": f"{sum(x['ref_customer_matched'] for x in xs)}/{sum(x['ref_customer'] for x in xs)}",
                "agent_read_calls": sum(x["read_calls"] for x in xs), "attempted_writes": sum(x["attempted_writes"] for x in xs),
                "successful_writes": sum(x["successful_writes"] for x in xs),
                "req_recall_full": round(sum(x["req_recall_full"] for x in xs) / n, 3),
                "req_recall_full_or_partial": round(sum(x["req_recall_full_or_partial"] for x in xs) / n, 3),
                "retrieval_calls": dict(sum((x["retrieval_calls"] for x in xs), Counter())),
                "docs_full_by_tool": dict(sum((x["docs_by_tool_full"] for x in xs), Counter())),
                "transfers": sum(x["transfers"] for x in xs), "held": sum(x["held"] for x in xs),
                "withheld": sum(x["withheld"] for x in xs),
                "shell_audit_flags": sum(len((x["shell_audit"] or {}).get("flagged") or []) for x in xs),
                "cost_ub_per_conv": round(sum(x["cost_ub"] for x in xs) / n, 3),
                "cost_cache_per_conv": round(sum(x["cost_cache"] for x in xs) / n, 3),
                "latency_s_per_conv": round(sum(x["duration_s"] for x in xs) / n, 1),
                "agent_in_tokens_per_conv": round(sum(x["agent_in_tokens"] for x in xs) / n),
                "independence_all_conclusive": all(x["independence_conclusive"] for x in xs),
                "not_finished": [x["task"] for x in rows if x["arm"] == arm and x["status"] != "finished"]}

    s = {arm: summ(arm) for arm in ARMS}
    b, v = s["baseline"], s["harness_v1"]
    heuristic = {"level_on_passes": v["passes_complete_pairs"] >= b["passes_complete_pairs"],
                 "more_passes": v["passes_complete_pairs"] > b["passes_complete_pairs"],
                 "write_progress_gain_ge_0.10": v["discoverable_write_progress"] - b["discoverable_write_progress"] >= 0.10,
                 "no_more_violating_conversations": "needs the blind audit"}
    audit_queue = sorted({(x["task"], x["arm"]) for x in rows if x.get("successful_writes")} |
                         {(p["task"], arm) for p in pairs if p["pair"] in ("improved", "regressed") for arm in ARMS})
    out = {"batch_status": res.get("status"), "pairs": pairs, "summary": s, "heuristic": heuristic,
           "audit_queue": [{"task": t, "arm": a} for t, a in audit_queue], "rows": rows}
    (ROOT / "research" / "h005" / "diagnostics.json").write_text(json.dumps(out, indent=1, default=dict))
    print(json.dumps({k: out[k] for k in ("batch_status", "pairs", "heuristic")}, indent=1))
    for arm in ARMS:
        print(f"\n{arm}: " + json.dumps(s[arm], default=dict))
    print(f"\naudit queue: {len(audit_queue)}")


if __name__ == "__main__":
    main()
