"""Dependency-following tool search: one isolated harness option (`{"dep_search": true}`), after H002/H003.

**The failure it targets.** In H002, 78% of reference writes were never attempted. The commonest first failure was
a requirement only in a document the agent never retrieved (C3, 24/60). The most-missed documents describe *lookup*
tools, e.g. the tool that lists a customer's accounts. The agent finds the procedure and its write tool (say, a tool
taking `account_id`), but never the tool that would give it the `account_id`, and customer-worded searches don't reach
that tool (research/h002/tool_retrieval_probe.py).

**The mechanism.** It was fixed in the offline probe before any result was seen, and is unchanged here:
1. **The index.** Every knowledge-base document whose text names a discoverable tool from the benchmark's registry
   (45 documents). This is the same public corpus that KB_search serves, restricted to tool documents. No task
   data is used.
2. **The trigger.** A successful KB_search result, in the agent's own view, names a discoverable agent tool that
   takes an identifier parameter (`*_id`, except `user_id`) that the agent does not hold yet. "Holds" means an
   `<name>_id:` field has appeared in some tool result so far.
3. **The query.** A fixed template, `retrieve <param words> <param> returns list`, run with BM25 (k1=1.5, b=0.75)
   against that index. The top 3 hits are kept.
4. **The effect.** Documents the agent has not seen yet are appended to *the model's own copy* of that search
   result, in the KB_search result format and under a label saying the harness added them. The benchmark's
   trajectory is untouched. The adapter then offers any tools those documents name, as for any retrieved
   document (bench/adapter.py).

**The budget.** Added by the harness; the probe had none:
- each identifier parameter is searched at most once per conversation;
- at most MAX_QUERIES queries per conversation;
- at most K documents per query, and only documents that are new to the agent.

**What it does not do.**
- It never calls a tool or writes anything.
- It never tells the agent what to do: document text is data.
- There is no special case for any document or task. The probe found that it never reaches doc `_009`, and that
  known limit is kept, not tuned away.

**The record of what the model saw.** Every search is logged in `harness_events` (event "dependency_search"), with:
- its query and ranking;
- the documents added and the exact text appended;
- the id of the search result it was appended to.

The trace's harness section also saves the model's full own history (`model_view`), and the tools offered only
because an added document named them (`offered_only_via_dep_search`). The benchmark trajectory alone is not a
complete record of this arm's inputs.
"""

import json
import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

K, K1, B = 3, 1.5, 0.75
MAX_QUERIES = 4
TOKEN = re.compile(r"[a-z0-9]+")
KNOWN_ID = re.compile(r"\b([a-z_]+_id):")
DOC_ID = re.compile(r"ID:\s*(doc_\S+)")
EVENT = "dependency_search"


class BM25:
    """Plain BM25 over lowercased word tokens (the same parameters as the offline probe)."""

    def __init__(self, docs: dict[str, str]):
        self.ids = list(docs)
        toks = [TOKEN.findall(docs[i].lower()) for i in self.ids]
        self.avg = sum(map(len, toks)) / max(len(toks), 1)
        df = Counter(t for d in toks for t in set(d))
        n = len(toks)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in toks]
        self.lens = [len(d) for d in toks]

    def top(self, query: str, k: int = K) -> list[str]:
        q = TOKEN.findall(query.lower())
        scores = []
        for i, tf, n in zip(self.ids, self.tf, self.lens):
            s = sum(self.idf.get(t, 0) * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * n / self.avg))
                    for t in q if t in tf)
            if s > 0:
                scores.append((s, i))
        return [i for _, i in sorted(scores, reverse=True)[:k]]


def documents_dir() -> Path:
    return Path(os.environ["TAU2_DATA_DIR"]) / "tau2" / "domains" / "banking_knowledge" / "documents"


@lru_cache(maxsize=4)
def tool_index(names: frozenset, docdir: str) -> tuple[BM25, dict]:
    """(BM25 over the tool documents, doc_id -> {"title", "content"}) for documents naming any of `names`."""
    docs = {}
    for f in sorted(Path(docdir).glob("*.json")):
        d = json.loads(f.read_text())
        text = d["title"] + "\n" + d["content"]
        if any(re.search(rf"\b{re.escape(n)}\b", text) for n in names):
            docs[d["id"]] = {"title": d["title"], "content": d["content"]}
    return BM25({i: d["title"] + "\n" + d["content"] for i, d in docs.items()}), docs


def query_for(param: str) -> str:
    return f"retrieve {param.replace('_', ' ')} {param} returns list"


def missing_id_params(kb_text: str, params: dict[str, list[str]], known: set[str]) -> list[tuple[str, str]]:
    """(tool, identifier parameter) for agent tools named in `kb_text` that take an identifier not yet held."""
    out = []
    for tool in sorted(params):
        if re.search(rf"\b{re.escape(tool)}\b", kb_text or ""):
            out += [(tool, p) for p in params[tool] if p.endswith("_id") and p != "user_id" and p not in known]
    return out


def format_block(param: str, tools: list[str], hits: list[tuple[str, dict]]) -> str:
    head = (f"\n\n---\nHarness dependency search (added by the harness, not by KB_search). Tools named above "
            f"({', '.join(tools)}) take {param}, which no tool result has given you yet. Documents that may describe "
            f"how to get it:\n\n")
    return head + "\n".join(f"{n}. {d['title']}\n   ID: {i}\n   Content: {d['content']}\n"
                            for n, (i, d) in enumerate(hits, 1))


class DependencySearch:
    """Per-conversation state: which parameters were searched, and how many queries were spent."""

    def __init__(self, index: BM25, docs: dict, params: dict[str, list[str]], max_queries: int = MAX_QUERIES):
        self.index, self.docs, self.params, self.max_queries = index, docs, params, max_queries
        self.searched: set[str] = set()
        self.queries = 0
        self.exhausted_logged = False

    def augment(self, kb_text: str, known_ids: set[str], docs_seen: set[str], events: list) -> str:
        """The text to append to one KB_search result ('' for nothing); logs every search in `events`."""
        by_param: dict[str, list[str]] = {}
        for tool, p in missing_id_params(kb_text, self.params, known_ids):
            if p not in self.searched:
                by_param.setdefault(p, []).append(tool)
        extra, seen = "", set(docs_seen) | set(DOC_ID.findall(kb_text or ""))
        for p, tools in by_param.items():
            if self.queries >= self.max_queries:
                if not self.exhausted_logged:
                    events.append({"event": EVENT + "_budget_exhausted", "param": p, "queries": self.queries})
                    self.exhausted_logged = True
                break
            self.searched.add(p)
            self.queries += 1
            q = query_for(p)
            ranked = self.index.top(q)
            new = [d for d in ranked if d not in seen]
            seen |= set(new)
            block = format_block(p, tools, [(d, self.docs[d]) for d in new]) if new else ""
            extra += block
            events.append({"event": EVENT, "param": p, "tools": tools, "query": q, "ranked": ranked,
                           "docs_added": new, "added_chars": len(block), "appended_text": block})
        return extra
