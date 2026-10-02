"""Confirmation pass over P004's fresh standard-agent conversations ($0; after the P004 review).

Questions (fixed before reading the output; the review's three):
  1. Do missing-procedure failures recur? In each failed baseline conversation, which of the task's required documents
     never reached the model (not even partially; bench/kb_evidence.py from the agent's own view)?
  2. Where the documents DID reach the model, the failure is abandonment or misapplication (retrieval cannot fix it).
  3. Reach: a candidate mechanism counts only if it appears across several DIFFERENT tasks.
Required documents and reference actions are read only to score (never given to any agent). Recurrence is checked
against the same tasks' earlier standard-agent conversations (H008, H009 baseline arms). These are new conversations
on familiar development tasks, not independent validation data.

    uv run --extra bench python research/confirmation/p004_baseline.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TRANSFER = "transfer_to_human_agents"


def conv(trace_path, task, tool_type):
    from bench import kb_evidence, metrics

    t = json.loads(Path(trace_path).read_text())
    msgs = t["messages"]
    obs = kb_evidence.observations(msgs)
    seen = {o.doc_id for o in obs if o.level in ("full", "partial")}
    named = {o.doc_id for o in obs}
    required = set(task.required_documents or [])
    refs = task.evaluation_criteria.actions or []
    res = {m.get("tool_call_id") or m.get("id"): m for m in msgs if m["role"] == "tool"}
    transferred = any(c["name"] == TRANSFER and (res.get(c["id"]) or {}).get("content", "").startswith("Transfer successful")
                      for m in msgs if m["role"] == "assistant" for c in m.get("tool_calls") or [])
    p = metrics.progress(msgs, refs, tool_type)
    return {"reward": (t.get("evaluation") or {}).get("reward"), "required": sorted(required),
            "missing_required": sorted(required - seen), "only_named_required": sorted((required & named) - seen),
            "all_required_seen": required <= seen, "transferred": transferred,
            "reference_has_transfer": any(a.name == TRANSFER for a in refs), "progress": p}


def main():
    import bench  # noqa: F401
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    from bench import diagnostics, kb_evidence, pins

    logger.remove()
    tool_type = diagnostics._tool_types()[0]
    dev = sorted(pins.load_split()["dev"])
    tasks = {t.id: t for t in get_tasks(pins.DOMAIN, task_ids=dev)}
    docs = kb_evidence.corpus()
    title = lambda d: (docs.get(d) or {}).get("title", "?")  # noqa: E731
    rows = json.loads((ROOT / "experiments" / "P004_results.json").read_text())["results"]
    base = [r for r in rows if r["arm"] == "baseline" and (r.get("official_reward") or 0) < 1]
    out = []
    for r in sorted(base, key=lambda r: r["task_id"]):
        out.append({"task": r["task_id"], **conv(r["trace"], tasks[r["task_id"]], tool_type)})
    # earlier standard-agent conversations on the same tasks
    earlier = defaultdict(list)
    for b in ("H008", "H009"):
        for r in json.loads((ROOT / "experiments" / f"{b}_results.json").read_text())["results"]:
            if r["arm"] == "baseline" and r.get("trace") and Path(r["trace"]).exists() and (r.get("official_reward") or 0) < 1:
                earlier[r["task_id"]].append(conv(r["trace"], tasks[r["task_id"]], tool_type)["missing_required"])
    missing_by_doc = Counter(d for x in out for d in x["missing_required"])
    tasks_by_doc = defaultdict(set)
    for x in out:
        for d in x["missing_required"]:
            tasks_by_doc[d].add(x["task"])
    summary = {
        "failed_baseline_conversations": len(out),
        "q1_some_required_document_never_reached": [x["task"] for x in out if x["missing_required"]],
        "q2_all_required_documents_reached_yet_failed": [x["task"] for x in out if x["all_required_seen"]],
        "tasks_without_required_documents": [x["task"] for x in out if not x["required"]],
        "missing_documents": [{"doc": d, "title": title(d), "conversations": n, "tasks": sorted(tasks_by_doc[d])}
                              for d, n in missing_by_doc.most_common()],
        "transferred_where_reference_has_none": [x["task"] for x in out if x["transferred"] and not x["reference_has_transfer"]],
        "transferred_with_required_document_missing": [x["task"] for x in out if x["transferred"] and not x["reference_has_transfer"] and x["missing_required"]],
        "recurrence_in_earlier_baseline_failures": {x["task"]: {"now_missing": x["missing_required"], "earlier_missing": earlier[x["task"]]}
                                                    for x in out if earlier.get(x["task"])},
        "per_conversation": out,
    }
    (ROOT / "research" / "confirmation" / "p004_baseline.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_conversation"}, indent=1, default=str))


if __name__ == "__main__":
    main()
