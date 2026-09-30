"""Offline replay of v3's capability searches over saved gpt-5-mini conversations ($0).

For each saved dev conversation (H002-H005, every arm), walk the messages the way the harness would:
- after the first successful verification, run the "accounts" capability search (unless an account id was already
  shown by a record lookup);
- at each agent text reply that asks the customer for an account, card or transaction identifier it does not hold,
  run the matching capability search (once per kind).
Searches use BM25 (tau2's own index); only the TOP 5 documents are counted, matching v3's k=5.

Measured: how often each trigger fires; required-document recall without and with the capability searches; and
whether the account-lookup document (_009) is reached when the task requires it. Required documents are read only to
score (dev tasks). This is evidence availability only: a replay cannot show what the agent then does.

    uv run --extra bench python research/v3/replay.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401
from bench import capability, kb_evidence, pins  # noqa: E402

DOC = re.compile(r"ID:\s*(doc_\S+)")
LOOKUP = "doc_bank_accounts_bank_accounts_(general)_009"


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
    top5 = {k: set(DOC.findall(env.tools.KB_search(q))[:capability.K]) for k, q in capability.QUERIES.items()}
    rows, fired = [], Counter()
    for batch in ("H002", "H003", "H004", "H005"):
        path = ROOT / "experiments" / f"{batch}_journal.jsonl"
        results = ([json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else
                   json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())["results"])
        for r in results:
            if not r.get("trace") or not Path(r["trace"]).exists() or r["task_id"] not in dev:
                continue
            t = json.loads(Path(r["trace"]).read_text())
            msgs = t["messages"]
            done, added, triggers = set(), set(), []
            for i, m in enumerate(msgs):
                before = msgs[:i + 1]
                s = capability.after_verification(before, done)
                if s is None and m["role"] == "assistant":
                    s = capability.before_asking({"content": m.get("content"), "tool_calls": m.get("tool_calls")},
                                                 msgs[:i], done)
                if s is not None:
                    done.add(s.kind)
                    added |= top5[s.kind]
                    triggers.append(f"{s.trigger}:{s.kind}")
            fired.update(triggers)
            required = set(tasks[r["task_id"]].required_documents or [])
            own = {o.doc_id for o in kb_evidence.observations(msgs) if o.level in ("full", "partial")}
            rows.append({"batch": batch, "task": r["task_id"], "arm": r.get("arm"), "triggers": triggers,
                         "recall_own": len(own & required) / max(len(required), 1),
                         "recall_with_capability": len((own | added) & required) / max(len(required), 1),
                         "needs_lookup": LOOKUP in required, "lookup_own": LOOKUP in own,
                         "lookup_with_capability": LOOKUP in (own | added),
                         "docs_added": len(added - own)})
    n = len(rows)
    need = [x for x in rows if x["needs_lookup"]]
    out = {"conversations": n,
           "top5_of_each_capability_query": {k: sorted(v) for k, v in top5.items()},
           "triggers_fired": dict(fired), "conversations_with_any_trigger": sum(bool(x["triggers"]) for x in rows),
           "required_doc_recall_own": round(sum(x["recall_own"] for x in rows) / n, 3),
           "required_doc_recall_with_capability": round(sum(x["recall_with_capability"] for x in rows) / n, 3),
           "account_lookup_reached_own": f"{sum(x['lookup_own'] for x in need)}/{len(need)}",
           "account_lookup_reached_with_capability": f"{sum(x['lookup_with_capability'] for x in need)}/{len(need)}",
           "docs_added_per_conversation": round(sum(x["docs_added"] for x in rows) / n, 2)}
    (ROOT / "research" / "v3" / "replay.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
