"""Offline tool-discovery check on saved failures (T001). Zero-cost: no model calls.

Question: when the agent retrieved a document naming the tool it needed and then said it could not act,
was the discoverable-tool interface broken, or did the agent not use it? Each case restores the exact
environment state at the agent's denial (replaying the trace's tool calls in a fresh environment) and
scripts the documented unlock-and-call sequence.
"""

import json
import re
from pathlib import Path

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT  # noqa: E402
from bench.independence import fresh_env  # noqa: E402


@pytest.fixture(scope="module")
def config():
    from tau2.data_model.simulation import TextRunConfig

    return TextRunConfig(domain="banking_knowledge", retrieval_config="bm25")


def _task(task_id):
    from tau2.runner.helpers import get_tasks

    return get_tasks("banking_knowledge", task_ids=[task_id])[0]


def _call(env, name, args):
    from tau2.data_model.message import ToolCall

    return env.get_response(ToolCall(id="s", name=name, arguments=args, requestor="assistant"))


def _restore(config, task_id, trace_file, upto):
    """Fresh environment, then every tool call the saved trajectory made before message `upto`."""
    from tau2.data_model.message import ToolCall

    trace = json.loads((REPO_ROOT / trace_file).read_text())
    env = fresh_env(config, _task(task_id))
    for m in trace["messages"][:upto]:
        for c in m.get("tool_calls") or []:
            env.get_response(ToolCall(id=c.get("id") or "x", name=c["name"], arguments=c["arguments"],
                                      requestor="assistant" if m["role"] == "assistant" else "user"))
    return env, trace


def _unlock_and_call(env, tool, args):
    unlocked = _call(env, "unlock_discoverable_agent_tool", {"agent_tool_name": tool})
    called = _call(env, "call_discoverable_agent_tool", {"agent_tool_name": tool, "arguments": json.dumps(args)})
    return unlocked, called


def test_case1_denied_tool_works_from_the_saved_state(config):
    # S003 task_095 baseline: at msg 26 the agent says it has no access to the tool its own search found.
    env, trace = _restore(config, "task_095", "results/S003/task_095_baseline/trace.json", 26)
    denial = trace["messages"][26]["content"]
    assert "don’t have access to the internal tool" in denial and "get_all_user_accounts_by_user_id_3847" in denial
    found = [m["i"] for m in trace["messages"][:26] if m["role"] == "tool"
             and "get_all_user_accounts_by_user_id_3847" in (m.get("content") or "")]
    assert found  # the tool name was in results the agent received before denying it
    user_id = re.search(r"user_id: (\w+)", json.dumps(trace["messages"][:26])).group(1)
    unlocked, called = _unlock_and_call(env, "get_all_user_accounts_by_user_id_3847", {"user_id": user_id})
    assert not unlocked.error and "Parameters" in unlocked.content  # unlocking returns usable parameter info
    assert not called.error and "Accounts for user" in called.content and "Record ID" in called.content


def test_case2_documented_sequence_completes_from_the_saved_state(config):
    # S002 task_080: at msg 22 the agent says it cannot complete the freezes from here.
    env, trace = _restore(config, "task_080", "results/S002/task_080/trace.json", 22)
    assert "can’t complete the freezes" in trace["messages"][22]["content"]
    steps = [("get_all_user_accounts_by_user_id_3847", {"user_id": "tm92c4d7e8"}, "Accounts for user"),
             ("get_debit_cards_by_account_id_7823", {"account_id": "chk_tm92c4d7e8_blue"}, "dbc_tm92c4d7e8_blue"),
             ("freeze_debit_card_3892", {"card_id": "dbc_tm92c4d7e8_blue"}, "Frozen Successfully")]
    for tool, args, expected in steps:
        unlocked, called = _unlock_and_call(env, tool, args)
        assert not unlocked.error and not called.error and expected in called.content, tool


def test_authorization_is_policy_only_and_invented_tools_are_rejected(config):
    # Discovery and authorization are separate: the interface executes a write with no identity
    # verification in the conversation. Only the written policy requires verification first.
    env = fresh_env(config, _task("task_080"))
    _, called = _unlock_and_call(env, "freeze_debit_card_3892", {"card_id": "dbc_tm92c4d7e8_blue"})
    assert not called.error and "Frozen Successfully" in called.content
    bad = _call(env, "unlock_discoverable_agent_tool", {"agent_tool_name": "made_up_tool_9999"})
    assert "Unknown agent tool" in bad.content
