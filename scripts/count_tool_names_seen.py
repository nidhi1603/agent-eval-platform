"""Executable definition of the "tool names seen" count in T001 and the write-up. Zero cost.

For each of the 19 live conversations (S001, S002, S003), count whether any discoverable tool name from the
benchmark's own registry appears in tool results the AGENT received (not the customer's tool traffic).
Seeing a name does not mean the tool was relevant or authorized for that conversation.

    uv run --extra bench python scripts/count_tool_names_seen.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR
from bench import REPO_ROOT
from bench.continuation import agent_visible
from bench.diagnostics import live_traces


def main() -> None:
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench.independence import fresh_env

    env = fresh_env(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"),
                    get_tasks("banking_knowledge", task_ids=["task_047"])[0])
    agent_tools = set(env.tools.get_discoverable_tools())
    user_tools = set(env.user_tools.get_discoverable_tools())
    word = re.compile(r"\b[a-z][a-z0-9_]*_\d{4}\b|\b[a-z][a-z0-9_]*\b")
    rows = []
    for path in live_traces():
        msgs = agent_visible(json.loads(path.read_text())["messages"], 10**9)
        calls = {tc["id"]: tc["name"] for m in msgs for tc in (m.get("tool_calls") or [])}
        results = [m for m in msgs if m["role"] == "tool"]
        names = lambda ms: set(word.findall(" ".join(m.get("content") or "" for m in ms)))  # noqa: E731
        kb = [m for m in results if calls.get(m.get("tool_call_id")) == "KB_search"]
        rows.append({"trace": str(path.relative_to(REPO_ROOT)),
                     "agent_tool_in_results": bool(names(results) & agent_tools),
                     "agent_tool_in_kb_results": bool(names(kb) & agent_tools),
                     "agent_or_user_tool_in_results": bool(names(results) & (agent_tools | user_tools))})
    n = len(rows)
    for key in ("agent_tool_in_results", "agent_tool_in_kb_results", "agent_or_user_tool_in_results"):
        print(f"{key:<32} {sum(r[key] for r in rows)}/{n}")
    for r in rows:
        if r["agent_or_user_tool_in_results"] != r["agent_tool_in_results"] or not r["agent_tool_in_results"]:
            print("  differs or none:", r)


if __name__ == "__main__":
    main()
