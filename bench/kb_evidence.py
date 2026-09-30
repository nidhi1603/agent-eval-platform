"""One evidence record for every retrieval tool: what knowledge-base text actually reached the model.

Under `alltools` the agent has three retrieval tools (KB_search_bm25, KB_search_dense, shell) instead of KB_search.
The search tools return whole documents in one format ("N. <title> / ID: <doc_id> / Score / Content: <text>"). The
shell returns whatever a command prints. The harness must not treat these differently, and it must not credit the
agent with text it never received. So every successful retrieval result becomes observations:

    Observation(doc_id, level, text, call_id, step, tool)

    level "full"        the document's complete content reached the model, identifiably: every word of it is in
                        the text attributed to that document (a whole search result, or `cat` of its file)
          "partial"     some of it reached the model: a truncated search result, grep lines attributed to its file,
                        head/sed/tail of that one file, or a `cat` whose output does not contain all of it
          "discovered"  only its name reached the model: ls, find, INDEX listings, grep -l
    text  the text that was shown for that document (empty for "discovered")

The level is decided by what reached the model, never by which command produced it. Several files printed together
count as "full" each only when each one's complete content is present and attributable.

Tool discovery uses the *output* text of successful retrieval calls only, never a shell command's own text: a tool
name the agent typed is not evidence that it read the tool's documentation.

Documents are identified in shell output by their sandbox file names. tau2 exports each document as
`<sanitized doc id>.md` containing "# <title>\\n\\n<content>" (tau2.knowledge.sandbox_manager).
"""

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SEARCH_TOOLS = ("KB_search", "KB_search_bm25", "KB_search_dense", "grep")
SHELL = "shell"
RETRIEVAL_TOOLS = SEARCH_TOOLS + (SHELL,)
RESULT = re.compile(r"^\d+\.\s+(?P<title>.*)\n\s+ID:\s*(?P<id>doc_\S+)\n(?:\s+Score:.*\n)?\s+Content:\s?", re.M)
FAILED = re.compile(r"^(Error|Command failed|Command blocked|No matches found\.|\(no output\)|No relevant documents)")
WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Observation:
    doc_id: str
    level: str      # "full" | "partial" | "discovered"
    text: str
    call_id: str
    step: int       # index of the tool result message in the conversation
    tool: str


def sanitize(doc_id: str) -> str:
    """tau2's sandbox file stem for a document id (SandboxManager._sanitize_filename)."""
    safe = doc_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in safe)[:255]


@lru_cache(maxsize=2)
def corpus(docdir: str | None = None) -> dict[str, dict]:
    """doc_id -> {"title", "content", "file"} for the knowledge base (the same corpus every retrieval tool serves)."""
    d = Path(docdir or Path(os.environ["TAU2_DATA_DIR"]) / "tau2" / "domains" / "banking_knowledge" / "documents")
    out = {}
    for f in sorted(d.glob("*.json")):
        x = json.loads(f.read_text())
        out[x["id"]] = {"title": x["title"], "content": x["content"], "file": sanitize(x["id"]) + ".md"}
    return out


def _norm(s: str) -> str:
    return WS.sub(" ", s or "").strip()


def succeeded(result: dict) -> bool:
    text = (result.get("content") or "").lstrip()
    return not result.get("error") and not FAILED.match(text)


def _complete(doc_id: str, shown: str, docs: dict) -> bool:
    body = _norm((docs.get(doc_id) or {}).get("content", ""))
    return bool(body) and body in _norm(shown)


def _search_obs(text, call_id, step, tool, docs):
    ms = list(RESULT.finditer(text))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = re.sub(r"\n\n\[Timing:.*\]\s*$", "", text[m.end():end]).strip()
        level = "full" if _complete(m.group("id"), body, docs) else ("partial" if body else "discovered")
        out.append(Observation(m.group("id"), level, body if level != "discovered" else "", call_id, step, tool))
    return out


def _own_lines(output: str, body: str, min_len: int = 20) -> list[str]:
    """Substantive output lines that occur in this document's text (so they are attributable to it)."""
    nb = _norm(body)
    return [ln for ln in output.splitlines() if len(ln.strip()) >= min_len and _norm(ln) in nb]


def _shell_obs(command: str, output: str, call_id: str, step: int, docs: dict) -> list[Observation]:
    by_file = {d["file"]: i for i, d in docs.items()}
    stem_re = re.compile(r"(?<![\w.-])(" + "|".join(map(re.escape, sorted(by_file, key=len, reverse=True))) + r")\b") \
        if by_file else None
    if stem_re is None:
        return []
    named_in_output = [m.group(1) for m in stem_re.finditer(output)]
    named_in_command = list(dict.fromkeys(m.group(1) for m in stem_re.finditer(command or "")))
    # grep-style attribution: "<file>:<line>" or "<file>-<line>" (context lines)
    attributed: dict[str, list[str]] = {}
    for line in output.splitlines():
        head = line[2:] if line.startswith("./") else line
        f = next((x for x in by_file if head.startswith(x) and head[len(x):len(x) + 1] in (":", "-")), None)
        if f:
            attributed.setdefault(f, []).append(re.sub(r"^[:-](\d+[:-])?", "", head[len(f):]))
    norm_out = _norm(output)
    out = []
    for f in dict.fromkeys(list(attributed) + named_in_command + named_in_output):
        doc = by_file[f]
        body = docs[doc]["content"]
        if f in attributed:
            shown = "\n".join(attributed[f])
        elif len(named_in_command) == 1 and f == named_in_command[0] and not attributed:
            shown = output            # cat/head/sed/tail of that one file: the output is its text
        elif f in named_in_command and (_norm(body) in norm_out or _own_lines(output, body)):
            # several files printed together: attribute to this document only the output lines that belong to it
            shown = body if _norm(body) in norm_out else "\n".join(_own_lines(output, body))
        else:
            shown = ""
        if shown and _norm(body) and _norm(body) in _norm(shown):
            level = "full"
        elif shown and len(_norm(shown)) > 0 and _norm(shown) != _norm(f):
            level = "partial"
        else:
            level, shown = "discovered", ""
        out.append(Observation(doc, level, shown, call_id, step, SHELL))
    return out


def observations(messages: list[dict], docs: dict | None = None) -> list[Observation]:
    """Every document observation in a conversation (model-view dicts, as bench.guard.messages_as_dicts gives)."""
    docs = corpus() if docs is None else docs
    calls = {c["id"]: c for m in messages if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])}
    out = []
    for step, m in enumerate(messages):
        if m.get("role") != "tool":
            continue
        c = calls.get(m.get("tool_call_id"))
        if not c or c["name"] not in RETRIEVAL_TOOLS or not succeeded(m):
            continue
        text = m.get("content") or ""
        if c["name"] == SHELL:
            out += _shell_obs(str((c.get("arguments") or {}).get("command", "")), text, c["id"], step, docs)
        else:
            out += _search_obs(text, c["id"], step, c["name"], docs)
    return out


def retrieval_calls(messages: list[dict]) -> list[tuple[dict, dict]]:
    """(call, result) for successful retrieval calls, in order."""
    by_id = {m.get("tool_call_id"): m for m in messages if m.get("role") == "tool"}
    return [(c, by_id[c["id"]]) for m in messages if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])
            if c["name"] in RETRIEVAL_TOOLS and c["id"] in by_id and succeeded(by_id[c["id"]])]


def shown_text(messages: list[dict]) -> list[str]:
    """Output texts of successful retrieval calls: where tool names may be discovered (never the command text)."""
    return [r.get("content") or "" for _, r in retrieval_calls(messages)]


def query_of(call: dict) -> str:
    args = call.get("arguments") or {}
    return str(args.get("query") or args.get("command") or args.get("pattern") or "")
