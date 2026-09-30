"""Offline probe ($0): would a dedicated search over TOOL documents have surfaced the tool documents a task needs,
earlier or more often than the agent's own searches did?

General mechanism, fixed before looking at results:
- Index: every knowledge-base document whose public text names a discoverable tool from the registry (agent or
  customer tools). No task data is used to build it.
- BM25 over that index (lowercased word tokens, k1=1.5, b=0.75), top K=3 per query. Nothing is tuned per document.
- Queries use only what was visible at that point in the conversation:
    Q_last:  the latest customer message
    Q_all:   all customer messages so far, concatenated
    Q_agent: the agent's own KB_search queries, re-run against the tool index
- Relevant = the task's required_documents that are in the tool index (read here only to score, dev tasks only).
Metrics per conversation: recall of relevant tool documents (by the end, and before the first write/transfer/denial),
irrelevant tool documents surfaced, and added tokens (~chars/4 of newly surfaced documents). This measures evidence
availability only, never task success.

    uv run --extra bench python research/h002/tool_retrieval_probe.py
"""
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import bench  # noqa: E402,F401

K, K1, B = 3, 1.5, 0.75
# The agent asks the customer for something an internal lookup could provide (fixed before looking at results)
ASK = re.compile(r"\b(account (?:number|id)|card (?:number|id)|last (?:4|four)|which (?:account|card)|"
                 r"transaction (?:id|number)|provide (?:the|your) (?:account|card))", re.I)
TOKEN = re.compile(r"[a-z0-9]+")
DOC = re.compile(r"ID:\s*(doc_\S+)")


def registry():
    from loguru import logger
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench import agent
    from bench.guard import toolkit_type_lookup

    logger.remove()
    env = build_text_orchestrator(TextRunConfig(domain="banking_knowledge", agent=agent.register("baseline"),
                                                llm_agent="x", llm_user="y", retrieval_config="bm25"),
                                  get_tasks("banking_knowledge", task_ids=["task_035"])[0], seed=300).environment
    names = set(env.tools.get_discoverable_tools()) | set(env.user_tools.get_discoverable_tools())
    from tau2.environment.tool import as_tool

    params = {n: list(as_tool(env.tools.tools[n]).openai_schema["function"]["parameters"].get("properties", {}))
              for n in env.tools.get_discoverable_tools()}
    return names, toolkit_type_lookup(env.tools), params


class BM25:
    def __init__(self, docs: dict[str, str]):
        self.ids = list(docs)
        self.toks = [TOKEN.findall(docs[i].lower()) for i in self.ids]
        self.avg = sum(map(len, self.toks)) / len(self.toks)
        df = Counter(t for d in self.toks for t in set(d))
        n = len(self.toks)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.toks]
        self.lens = {i: len(d) for i, d in zip(self.ids, self.toks)}

    def top(self, query: str, k: int = K) -> list[str]:
        q = TOKEN.findall(query.lower())
        scores = []
        for i, tf in zip(self.ids, self.tf):
            s = sum(self.idf.get(t, 0) * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * self.lens[i] / self.avg))
                    for t in q if t in tf)
            if s > 0:
                scores.append((s, i))
        return [i for _, i in sorted(scores, reverse=True)[:k]]


def main():
    names, tool_type, params = registry()
    name_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b")
    docdir = Path(bench.os.environ["TAU2_DATA_DIR"]) / "tau2/domains/banking_knowledge/documents"
    docs = {}
    for f in docdir.glob("*.json"):
        d = json.loads(f.read_text())
        text = d["title"] + "\n" + d["content"]
        if any(re.search(rf"\b{re.escape(n)}\b", text) for n in names):
            docs[d["id"]] = text
    index = BM25(docs)
    from tau2.runner.helpers import get_tasks

    res = json.loads((ROOT / "experiments" / "H002_results.json").read_text())
    rows = []
    for r in res["results"]:
        if not r.get("trace"):
            continue
        t = json.loads(Path(r["trace"]).read_text())
        msgs = t["messages"]
        task = get_tasks("banking_knowledge", task_ids=[r["task_id"]])[0]
        relevant = set(task.required_documents or []) & set(docs)
        if not relevant:
            continue
        results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
        # the first consequential step (write, transfer or denial): the point by which the tool doc was needed
        acting = next((i for i, m in enumerate(msgs) if m["role"] == "assistant" and any(
            tc["name"] == "transfer_to_human_agents" or (tc["name"] == "call_discoverable_agent_tool") for tc in m.get("tool_calls") or [])), len(msgs))
        seen = {"agent": {}, "Q_last": {}, "Q_all": {}, "Q_agent": {}, "Q_ask": {}, "Q_dep": {}}
        known_ids = set()
        customer = []
        for i, m in enumerate(msgs):
            if m["role"] == "user" and m.get("content") and not m.get("tool_calls"):
                customer.append(m["content"])
                for d in index.top(m["content"]):
                    seen["Q_last"].setdefault(d, i)
                for d in index.top(" ".join(customer)):
                    seen["Q_all"].setdefault(d, i)
            if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls") and ASK.search(m["content"]):
                # the agent is asking the customer for an identifier or record: query the tool index with its words
                for d in index.top(m["content"]):
                    seen["Q_ask"].setdefault(d, i)
            for tc in m.get("tool_calls") or []:
                if m["role"] == "assistant" and tc["name"] == "KB_search":
                    for d in index.top(str(tc["arguments"].get("query", ""))):
                        seen["Q_agent"].setdefault(d, i)
                    kb = (results.get(tc["id"]) or {}).get("content") or ""
                    for d in DOC.findall(kb):
                        if d in docs:
                            seen["agent"].setdefault(d, i)
                    # dependency following: identifier inputs of the tools named in this result that the agent
                    # does not yet hold -> search the tool index for what provides them (static schemas only)
                    for tool in set(name_re.findall(kb)):
                        for prm in params.get(tool, []):
                            if prm.endswith("_id") and prm not in known_ids and prm != "user_id":
                                for d in index.top(f"retrieve {prm.replace('_', ' ')} {prm} returns list"):
                                    seen["Q_dep"].setdefault(d, i)
            for tc in m.get("tool_calls") or []:
                res_c = (results.get(tc["id"]) or {}).get("content") or ""
                known_ids |= {k for k in re.findall(r"\b([a-z_]+_id):", res_c)}
        row = {"task": r["task_id"], "arm": r["arm"], "attempt": r["attempt"], "relevant": sorted(relevant)}
        for src, got in seen.items():
            by_end = set(got) & relevant
            by_act = {d for d, i in got.items() if i < acting} & relevant
            new_vs_agent = set(got) - set(seen["agent"])
            row[src] = {"recall_end": len(by_end) / len(relevant), "recall_before_acting": len(by_act) / len(relevant),
                        "irrelevant": len(set(got) - relevant),
                        "added_tokens": sum(len(docs[d]) for d in new_vs_agent) // 4 if src != "agent" else 0,
                        "found": sorted(by_end)}
        u = set(seen["agent"]) | set(seen["Q_all"])
        row["agent+Q_all"] = {"recall_end": len(u & relevant) / len(relevant), "recall_before_acting": None}
        u2 = set(seen["agent"]) | set(seen["Q_ask"])
        row["agent+Q_ask"] = {"recall_end": len(u2 & relevant) / len(relevant), "recall_before_acting": None}
        u3 = set(seen["agent"]) | set(seen["Q_dep"])
        row["agent+Q_dep"] = {"recall_end": len(u3 & relevant) / len(relevant), "recall_before_acting": None}
        rows.append(row)
    out = ROOT / "research" / "h002" / "tool_retrieval_probe.json"
    out.write_text(json.dumps({"index_size": len(docs), "k": K, "rows": rows}, indent=1))
    print(f"tool-document index: {len(docs)} documents; conversations with a relevant tool document: {len(rows)}")
    srcs = ["agent", "Q_last", "Q_all", "Q_agent", "Q_ask", "Q_dep", "agent+Q_all", "agent+Q_ask", "agent+Q_dep"]
    print(f"{'source':<14}{'recall (end)':>14}{'before acting':>15}{'irrelevant/conv':>17}{'added tokens/conv':>19}")
    for s in srcs:
        xs = [r[s] for r in rows]
        g = lambda k: sum(x.get(k) or 0 for x in xs) / len(xs)  # noqa: E731
        na = xs[0].get("recall_before_acting") is None
        print(f"{s:<14}{g('recall_end'):>14.2f}{'n/a' if na else format(g('recall_before_acting'), '.2f'):>15}"
              f"{'n/a' if na else format(g('irrelevant'), '.1f'):>17}{'n/a' if na else format(g('added_tokens'), '.0f'):>19}")
    per_doc = defaultdict(lambda: Counter())
    for r in rows:
        for d in r["relevant"]:
            per_doc[d]["needed"] += 1
            for s in ("agent", "Q_all", "Q_ask", "Q_dep"):
                per_doc[d][s] += d in r[s]["found"]
    print("\nper relevant tool document (conversations: needed / agent / Q_all / Q_ask / Q_dep found):")
    for d, c in sorted(per_doc.items(), key=lambda x: -x[1]["needed"]):
        print(f"  {d:<60}{c['needed']:>4}{c['agent']:>6}{c['Q_all']:>6}{c['Q_ask']:>6}{c['Q_dep']:>6}")


if __name__ == "__main__":
    main()
