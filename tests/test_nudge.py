"""Pre-send check (bench/nudge.py). Zero-cost: saved traces and scripted models."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, diagnostics, nudge  # noqa: E402
from bench.continuation import agent_visible  # noqa: E402
from tests.test_bench import scripted_run  # noqa: E402

CHECK = "locked_named_tool_before_denial_or_transfer"


@pytest.fixture(scope="module")
def names():
    return diagnostics._tool_types()[1]


def _at(path, i, names):
    t = json.loads((REPO_ROOT / path).read_text())
    m = t["messages"][i]
    return nudge.trigger({"content": m.get("content"), "tool_calls": m.get("tool_calls")},
                         agent_visible(t["messages"], i), names)


def test_fires_on_the_measured_failures_and_ranks_the_needed_tool_first(names):
    # S003 task_095: denied having the tool its own search found; that tool is now named first
    assert _at("results/S003/task_095_baseline/trace.json", 26, names)[0] == "get_all_user_accounts_by_user_id_3847"
    # S002 task_035: plain transfer although the retrieved protocol required the incident tool first
    assert "emergency_credit_bureau_incident_transfer_1114" in _at("results/S002/task_035/trace.json", 8, names)


def test_does_not_fire_on_ordinary_messages_or_after_a_successful_unlock(names):
    assert _at("results/S002/task_047/trace.json", 4, names) is None  # not a denial or transfer
    msgs = [{"role": "tool", "tool_call_id": "a", "content": "1. Doc  Use freeze_debit_card_3892 to freeze."},
            {"role": "assistant", "tool_calls": [{"id": "u", "name": "unlock_discoverable_agent_tool",
                                                  "arguments": {"agent_tool_name": "freeze_debit_card_3892"}}]},
            {"role": "tool", "tool_call_id": "u", "content": "Tool unlocked: freeze_debit_card_3892"}]
    assert nudge.trigger({"content": "Sorry, I don't have access to that."}, msgs, names) is None


def test_a_failed_unlock_leaves_the_tool_locked(names):
    # review reproduction: a failed unlock followed by a denial used to suppress the check
    msgs = [{"role": "tool", "tool_call_id": "a", "content": "1. Doc  Use freeze_debit_card_3892 to freeze."},
            {"role": "assistant", "tool_calls": [{"id": "u", "name": "unlock_discoverable_agent_tool",
                                                  "arguments": {"agent_tool_name": "freeze_debit_card_3892"}}]},
            {"role": "tool", "tool_call_id": "u", "content": "Error: Unknown agent tool 'freeze_debit_card_3892'."}]
    assert nudge.trigger({"content": "Sorry, I don't have access to that."}, msgs, names) == ["freeze_debit_card_3892"]


def test_note_separates_agent_and_customer_tools_and_keeps_prerequisites():
    text = nudge.note(["freeze_debit_card_3892", "submit_cash_back_dispute_0589"], {"freeze_debit_card_3892"})
    assert "unlock_discoverable_agent_tool" in text and "give_discoverable_user_tool" in text
    assert "prerequisites are met" in text and "If none applies" in text


def test_end_to_end_the_draft_is_withheld_and_the_check_fires_once(tmp_path):
    trace, _ = scripted_run(tmp_path, script="task_028_nudge_after_denial.json", task_id="task_028",
                            agent_nudges=(CHECK,))
    events = trace["guard"]["events"]
    assert [e["event"] for e in events] == ["nudged"]
    assert "update_transaction_rewards_3847" in events[0]["names"]
    text = json.dumps(trace["messages"])
    assert "don't have access to a tool that can change rewards" not in text  # the first draft never reached the customer
    assert "has to be submitted and approved" in text
    assert "anything else for this" in text  # fired once; the later denial went out unchanged
    assert trace["evaluation"] is not None and any("pre-send checks" in f for f in trace["research_eligibility"]["flags"])
