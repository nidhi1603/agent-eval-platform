"""$0 probe: would searching with the customer's own words find required documents the agent's queries missed?
Uses the 19 saved conversations. required_documents are read ONLY to measure recall here; no harness sees them.

    uv run --extra bench python research/harness_v1/recall_probe.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401

DOC = re.compile(r"ID:\s*(doc_\S+)")


def main():
    from loguru import logger
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench import agent

    logger.remove()
    name = agent.register("baseline")
    rows = []
    paths = sorted((ROOT / "results").glob("S00*/*/trace.json")) + sorted((ROOT / "results").glob("S001_*/trace.json"))
    for p in paths:
        t = json.loads(p.read_text())
        tid = t["task"]["id"]
        task = get_tasks("banking_knowledge", task_ids=[tid])[0]
        env = build_text_orchestrator(TextRunConfig(domain="banking_knowledge", agent=name, llm_agent="x", llm_user="y",
                                                    retrieval_config="bm25"), task, seed=300).environment
        search = lambda q: set(DOC.findall(env.tools.KB_search(q)))  # noqa: E731
        required = set(task.required_documents or [])
        msgs = t["messages"]
        agent_got, n_queries = set(), 0
        for i, m in enumerate(msgs):
            for c in m.get("tool_calls") or []:
                if m["role"] == "assistant" and c["name"] == "KB_search":
                    n_queries += 1
                    res = next((x for x in msgs[i + 1:] if x["role"] == "tool" and x.get("tool_call_id") == c["id"]), None)
                    agent_got |= set(DOC.findall((res or {}).get("content") or ""))
        customer = [m["content"] for m in msgs if m["role"] == "user" and m.get("content") and not m.get("tool_calls")]
        cust_got = set()
        for text in customer:
            cust_got |= search(text[:1000])
        rows.append({"run": f"{p.parent.parent.name}/{p.parent.name}", "required": len(required), "agent_queries": n_queries,
                     "agent_recall": len(required & agent_got), "customer_words_recall": len(required & cust_got),
                     "union_recall": len(required & (agent_got | cust_got)),
                     "extra_docs_shown": len(cust_got - agent_got), "customer_messages": len(customer)})
    tot = {k: sum(r[k] for r in rows) for k in ("required", "agent_recall", "customer_words_recall", "union_recall")}
    for r in rows:
        print(r)
    print(tot)
    (ROOT / "research" / "harness_v1" / "recall_probe.json").write_text(json.dumps({"rows": rows, "totals": tot}, indent=1))


if __name__ == "__main__":
    main()
