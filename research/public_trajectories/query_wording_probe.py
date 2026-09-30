"""Offline probe ($0): is gpt-5-mini's retrieval gap a query-wording gap?

Top standard agents word about a third of their searches in the knowledge base's own procedural vocabulary
("Internal ... tool ... lookup"); gpt-5-mini does so in 3% (how_found.py). This probe takes gpt-5-mini's OWN search
queries from its saved conversations (H002-H005: standard agent and harness v1, dev tasks) and re-runs each with BM25
(tau2's own index) in two forms:
    plain      the query as the agent wrote it
    + twin     the same query, plus a second search: "Internal tool lookup procedure: <query>"
The twin is one fixed template, written before looking at any result; nothing is tuned per task or document.
Measured: required-document recall over the conversation's queries (top 10 per search), and whether the account
lookup document (_009) is reached. Evidence availability only, never task success.

    uv run --extra bench python research/public_trajectories/query_wording_probe.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
import bench  # noqa: E402,F401
from bench import kb_evidence, pins  # noqa: E402

DOC = re.compile(r"ID:\s*(doc_\S+)")
LOOKUP = "doc_bank_accounts_bank_accounts_(general)_009"
TWIN = "Internal tool lookup procedure: {q}"


def main():
    from loguru import logger
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench import agent

    logger.remove()
    dev = set(pins.load_split()["dev"])
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted(dev))}
    env = build_text_orchestrator(TextRunConfig(domain="banking_knowledge", agent=agent.register("baseline"),
                                                llm_agent="x", llm_user="y", retrieval_config="bm25"),
                                  tasks["task_035"], seed=300).environment
    cache = {}

    def search(q):
        if q not in cache:
            cache[q] = set(DOC.findall(env.tools.KB_search(q)))
        return cache[q]

    rows = []
    for batch in ("H002", "H003", "H004", "H005"):
        path = ROOT / "experiments" / f"{batch}_journal.jsonl"
        results = ([json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else
                   json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())["results"])
        for r in results:
            if not r.get("trace") or not Path(r["trace"]).exists() or r["task_id"] not in dev:
                continue
            t = json.loads(Path(r["trace"]).read_text())
            qs = [kb_evidence.query_of(c) for c, _ in kb_evidence.retrieval_calls(t["messages"]) if c["name"] != "shell"]
            qs = [q for q in dict.fromkeys(qs) if q]
            if not qs:
                continue
            required = set(tasks[r["task_id"]].required_documents or [])
            plain = set().union(*(search(q) for q in qs))
            twin = plain | set().union(*(search(TWIN.format(q=q)) for q in qs))
            rows.append({"batch": batch, "task": r["task_id"], "arm": r.get("arm"), "queries": len(qs),
                         "recall_plain": len(plain & required) / max(len(required), 1),
                         "recall_twin": len(twin & required) / max(len(required), 1),
                         "docs_plain": len(plain), "docs_twin": len(twin),
                         "needs_lookup": LOOKUP in required, "lookup_plain": LOOKUP in plain, "lookup_twin": LOOKUP in twin})
    n = len(rows)
    need = [x for x in rows if x["needs_lookup"]]
    out = {"conversations": n, "twin_template": TWIN,
           "required_doc_recall_plain": round(sum(x["recall_plain"] for x in rows) / n, 3),
           "required_doc_recall_with_twin": round(sum(x["recall_twin"] for x in rows) / n, 3),
           "distinct_docs_retrieved_plain": round(sum(x["docs_plain"] for x in rows) / n, 1),
           "distinct_docs_retrieved_with_twin": round(sum(x["docs_twin"] for x in rows) / n, 1),
           "account_lookup_reached_plain": f"{sum(x['lookup_plain'] for x in need)}/{len(need)}",
           "account_lookup_reached_with_twin": f"{sum(x['lookup_twin'] for x in need)}/{len(need)}"}
    (ROOT / "research" / "public_trajectories" / "query_wording_probe.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
