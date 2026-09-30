"""Offline ($0): the dependency search AS BUILT (bench/depsearch.py, with its budget and de-duplication), replayed
over the saved H002 and H003 conversations. Does it keep the offline probe's recall gain for the required tool
documents? Relevant documents are read only to score (dev tasks). Evidence availability only, never task success:
a replay cannot show what the agent would have done with the extra documents.

    uv run --extra bench python research/h004/dep_replay.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
import bench  # noqa: E402,F401
from bench import depsearch  # noqa: E402
from tool_retrieval_probe import registry  # noqa: E402


def main():
    from tau2.runner.helpers import get_tasks

    names, _, params = registry()
    index, docs = depsearch.tool_index(frozenset(names), str(depsearch.documents_dir()))
    rows = []
    for batch in ("H002", "H003"):
        for r in json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())["results"]:
            if not r.get("trace"):
                continue
            t = json.loads(Path(r["trace"]).read_text())
            task = get_tasks("banking_knowledge", task_ids=[r["task_id"]])[0]
            relevant = set(task.required_documents or []) & set(docs)
            if not relevant:
                continue
            msgs = t["messages"]
            results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
            dep = depsearch.DependencySearch(index, docs, params)
            events, agent_docs, added, known, seen_all, added_chars = [], set(), set(), set(), set(), 0
            for m in msgs:
                for tc in m.get("tool_calls") or []:
                    res = (results.get(tc["id"]) or {}).get("content") or ""
                    if m["role"] == "assistant" and tc["name"] == "KB_search" and not res.lstrip().startswith("Error"):
                        n0 = len(events)
                        extra = dep.augment(res, known, seen_all, events)
                        added_chars += len(extra)
                        new = {d for e in events[n0:] if e["event"] == depsearch.EVENT for d in e["docs_added"]}
                        agent_docs |= set(depsearch.DOC_ID.findall(res)) & set(docs)
                        added |= new
                        seen_all |= set(depsearch.DOC_ID.findall(res)) | new
                    known |= set(depsearch.KNOWN_ID.findall(res))
            rows.append({"batch": batch, "task": r["task_id"], "arm": r["arm"], "attempt": r["attempt"],
                         "relevant": sorted(relevant),
                         "recall_agent": len(agent_docs & relevant) / len(relevant),
                         "recall_with_dep": len((agent_docs | added) & relevant) / len(relevant),
                         "queries": dep.queries, "docs_added": len(added),
                         "irrelevant_added": len(added - relevant), "added_tokens": added_chars // 4,
                         "relevant_only_via_dep": sorted((added - agent_docs) & relevant)})
    out = ROOT / "research" / "h004" / "dep_replay.json"
    out.write_text(json.dumps(rows, indent=1))
    n = len(rows)
    mean = lambda k: sum(x[k] for x in rows) / n  # noqa: E731
    print(f"conversations with a relevant tool document: {n}")
    print(f"recall agent {mean('recall_agent'):.2f} -> with dependency search {mean('recall_with_dep'):.2f}; "
          f"queries/conv {mean('queries'):.1f}; docs added/conv {mean('docs_added'):.1f} "
          f"(irrelevant {mean('irrelevant_added'):.1f}); added tokens/conv {mean('added_tokens'):.0f}; "
          f"budget exhausted in {sum(x['queries'] >= depsearch.MAX_QUERIES for x in rows)}")
    from collections import Counter

    print("relevant documents reached only through dependency search:",
          dict(Counter(d for x in rows for d in x["relevant_only_via_dep"])))


if __name__ == "__main__":
    main()
