"""First real-embedding check of dense retrieval (PAID, about $0.05–0.10; runs only with an approved cap).

Fake embeddings only showed that the dense tool is wired in. This checks that the real index works: it builds the
alltools environment with OpenAI text-embedding-3-large (metered through bench/budget.py under its own cap), then
runs a fixed, task-agnostic probe.
- **Queries:** for each of the 45 tool documents, its own title. No task data is used.
- **Measured:** whether dense search returns that document in its top 3, with BM25's hit rate beside it.
- **Pass:** a dense top-3 hit rate of at least 0.80. It is a sanity check of the index, not a measure of task success.
- **Cost:** embedding the 698 documents once (cached under ./data/.embeddings_cache and reused by later live runs),
  plus 45 query embeddings.

    uv run --extra bench python research/alltools/dense_check.py --approved-usd 0.30
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401

DOC = __import__("re").compile(r"ID:\s*(doc_\S+)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--approved-usd", type=float, required=True)
    p.add_argument("--fake", action="store_true", help="$0 code-path test with fake embeddings (result not meaningful)")
    a = p.parse_args()
    from dotenv import load_dotenv
    from loguru import logger
    from tau2.data_model.simulation import TextRunConfig
    from tau2.knowledge.embedders.openai_embedder import OpenAIEmbedder
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench import agent, depsearch, sandbox_policy
    from bench.budget import Budget, Limits, install, load_prices, metered_embedder, role

    logger.remove()
    load_dotenv(ROOT / ".env", override=False)
    sandbox_policy.patch()
    out_dir = ROOT / "research" / "alltools"
    limits = Limits()
    if a.fake:
        import tempfile

        from bench.run import _isolate_embedding_cache
        from bench.scripted import FAKE_PRICES, FakeEmbedder

        _isolate_embedding_cache(Path(tempfile.mkdtemp(prefix="aep-mock-embeddings-")))
        budget = Budget(a.approved_usd, FAKE_PRICES, Path(tempfile.mkdtemp()) / "ledger.jsonl")
        embedder = FakeEmbedder
    else:
        budget = Budget(a.approved_usd, load_prices(), out_dir / "dense_check_ledger.jsonl")
        embedder = metered_embedder(budget, limits, OpenAIEmbedder)
    with install(budget, limits, embedder_cls=embedder), role("dense_check"):
        env = build_text_orchestrator(TextRunConfig(domain="banking_knowledge", agent=agent.register("baseline"),
                                                    llm_agent="x", llm_user="y", retrieval_config="alltools"),
                                      get_tasks("banking_knowledge", task_ids=["task_035"])[0], seed=300).environment
        names = set(env.tools.get_discoverable_tools()) | set(env.user_tools.get_discoverable_tools())
        _, docs = depsearch.tool_index(frozenset(names), str(depsearch.documents_dir()))
        rows = []
        for doc_id, d in sorted(docs.items()):
            dense = DOC.findall(env.tools.KB_search_dense(d["title"], k=3))
            bm25 = DOC.findall(env.tools.KB_search_bm25(d["title"], k=3))
            rows.append({"doc": doc_id, "title": d["title"], "dense_top3": doc_id in dense, "bm25_top3": doc_id in bm25})
    n = len(rows)
    result = {"queries": n, "dense_top3_hit_rate": round(sum(r["dense_top3"] for r in rows) / n, 3),
              "bm25_top3_hit_rate": round(sum(r["bm25_top3"] for r in rows) / n, 3),
              "pass_threshold": 0.8, "spend": budget.summary(), "rows": rows}
    result["passed"] = result["dense_top3_hit_rate"] >= 0.8
    result["mode"] = "FAKE embeddings: code-path test only" if a.fake else "real embeddings"
    if not a.fake:
        (out_dir / "dense_check.json").write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1, default=str))


if __name__ == "__main__":
    main()
