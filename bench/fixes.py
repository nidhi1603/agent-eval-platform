"""Local, opt-in fix for the banking_knowledge answer-dependent listing (tau2 v1.0.1).

The defect: `call_discoverable_agent_tool` writes a READ call to the `agent_discoverable_tools` table
only when the tool is in the task's reference trajectory (`read_log_allowlist`, derived from the
answer key), and the agent-visible `list_discoverable_agent_tools` prints that table. So the listing
reveals whether a read the agent made is part of the reference solution.

The fix separates the two roles of that table:
- grading keeps the table exactly as tau2 writes it (the call path is unchanged; we only observe it);
- the agent-visible listing is rebuilt from agent-facing state: every discoverable call that
  reached tau2's logging point, read or write, in call order, regardless of the allowlist.

It changes the benchmark environment, so it is opt-in and every run that uses it must disclose it.
It is not a replacement for the official environment in leaderboard-comparable runs.
"""

import functools
import json
from contextlib import contextmanager
from unittest import mock

FIX_NAME = "listing_from_agent_state"
_CALLS_ATTR = "_aep_called_agent_tools"


def _reached_logging_point(toolkit, name: str, arguments: str, result: str) -> bool:
    """True when tau2's call_discoverable_agent_tool got past all early returns (the same point at
    which it decides whether to write the evaluation log)."""
    if not toolkit.has_discoverable_tool(name) or name not in toolkit.get_agent_discoverable_tools_state():
        return False
    try:
        json.loads(arguments, parse_int=float)
    except (json.JSONDecodeError, TypeError):
        return False
    return not (isinstance(result, str) and result.startswith("Error: Invalid arguments:"))


@contextmanager
def listing_from_agent_state():
    from tau2.domains.banking_knowledge.tools import KnowledgeTools

    original_call = KnowledgeTools.call_discoverable_agent_tool
    original_list = KnowledgeTools.list_discoverable_agent_tools

    @functools.wraps(original_call)  # keeps tau2's tool markers, docstring and signature (schema unchanged)
    def call_discoverable_agent_tool(self, agent_tool_name, arguments="{}"):
        result = original_call(self, agent_tool_name, arguments)  # unchanged behaviour, including the eval log
        if _reached_logging_point(self, agent_tool_name, arguments, result):
            self.__dict__.setdefault(_CALLS_ATTR, []).append(agent_tool_name)
        return result

    @functools.wraps(original_list)
    def list_discoverable_agent_tools(self):
        called = self.__dict__.get(_CALLS_ATTR, [])
        if not called:
            return "No agent tools have been called yet. Search the knowledge base to discover available tools."
        lines = [f"{i}. {name} (status: CALLED)" for i, name in enumerate(called, 1)]
        return "Your called agent tools:\n" + "\n".join(lines)

    with mock.patch.object(KnowledgeTools, "call_discoverable_agent_tool", call_discoverable_agent_tool), \
         mock.patch.object(KnowledgeTools, "list_discoverable_agent_tools", list_discoverable_agent_tools):
        yield FIX_NAME
