"""How do the top standard agents find the documents a task requires? ($0, dev tasks only; see analyze.py)

For every required document that reached the model: which tool first showed it, and at which retrieval call.
Also: how often search queries use the knowledge base's own vocabulary for procedures ("internal", "tool", "lookup").

    uv run --extra bench python research/public_trajectories/how_found.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "public_trajectories"))
import bench  # noqa: E402,F401
from analyze import DATA, FILES, as_view, load_dev  # noqa: E402
from bench import kb_evidence, pins  # noqa: E402

INTERNAL = re.compile(r"\b(internal|tool|lookup|look up|retriev)", re.I)
ACCOUNT_LOOKUP = "doc_bank_accounts_bank_accounts_(general)_009"


def main():
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    logger.remove()
    dev = set(pins.load_split()["dev"])
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted(dev))}
    out = {}
    sources = {m: [(s["task_id"], as_view(s["messages"])) for s in load_dev(DATA / f, dev)] for m, f in FILES.items()}
    ours = []
    for r in (json.loads(x) for x in (ROOT / "experiments" / "H005_journal.jsonl").read_text().splitlines() if x.strip()):
        if r.get("trace") and Path(r["trace"]).exists() and r.get("arm") == "baseline":
            ours.append((r["task_id"], json.loads(Path(r["trace"]).read_text())["messages"]))
    sources["gpt-5-mini/standard (H005, 4 conversations)"] = ours
    for model, convs in sources.items():
        first_tool, queries, internal_q, lookup_needed, lookup_found, lookup_by = Counter(), 0, 0, 0, 0, Counter()
        for task_id, view in convs:
            required = set(tasks[task_id].required_documents or [])
            seen = {}
            for o in kb_evidence.observations(view):
                if o.doc_id in required and o.level in ("full", "partial") and o.doc_id not in seen:
                    seen[o.doc_id] = o.tool
            first_tool.update(seen.values())
            first_tool["(never reached)"] += len(required - set(seen))
            for c, _ in kb_evidence.retrieval_calls(view):
                if c["name"] != "shell":
                    queries += 1
                    internal_q += bool(INTERNAL.search(kb_evidence.query_of(c)))
            if ACCOUNT_LOOKUP in required:
                lookup_needed += 1
                lookup_found += ACCOUNT_LOOKUP in seen
                if ACCOUNT_LOOKUP in seen:
                    lookup_by[seen[ACCOUNT_LOOKUP]] += 1
        tot = sum(first_tool.values())
        out[model] = {"required_docs_first_shown_by": {k: round(v / tot, 2) for k, v in first_tool.most_common()},
                      "search_queries_with_internal_tool_wording": f"{internal_q}/{queries} = {internal_q / max(queries, 1):.2f}",
                      "account_lookup_doc_009": f"reached in {lookup_found}/{lookup_needed} conversations that need it",
                      "account_lookup_first_shown_by": dict(lookup_by)}
    (ROOT / "research" / "public_trajectories" / "how_found.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
