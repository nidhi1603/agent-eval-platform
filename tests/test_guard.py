"""Proposal-time rewards guard (bench/guard.py). Zero-cost: scripted models and replayed states."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, guard  # noqa: E402
from bench.independence import fresh_env  # noqa: E402
from tests.test_bench import scripted_run  # noqa: E402

RULE = "rewards_update_requires_approved_dispute"


@pytest.fixture(scope="module")
def config():
    from tau2.data_model.simulation import TextRunConfig

    return TextRunConfig(domain="banking_knowledge", retrieval_config="bm25")


def _task(task_id):
    from tau2.runner.helpers import get_tasks

    return get_tasks("banking_knowledge", task_ids=[task_id])[0]


def _tc(name, args, requestor="assistant"):
    from tau2.data_model.message import ToolCall

    return ToolCall(id="g", name=name, arguments=args, requestor=requestor)


def test_blocks_the_s003_unauthorized_write_from_its_saved_state(config):
    # S003 task_019 (variant arm): msg 24 updated rewards although no dispute existed.
    trace = json.loads((REPO_ROOT / "results/S003/task_019_denial_check_v1/trace.json").read_text())
    env = fresh_env(config, _task("task_019"))
    for m in trace["messages"][:24]:
        for c in m.get("tool_calls") or []:
            env.get_response(_tc(c["name"], c["arguments"], "assistant" if m["role"] == "assistant" else "user"))
    proposed = trace["messages"][24]["tool_calls"][0]
    assert json.loads(proposed["arguments"]["arguments"])["transaction_id"] == "txn_d398545ca1a2"
    decision = guard.check(_tc(proposed["name"], proposed["arguments"]), env.tools.db)
    assert not decision.allowed and decision.rule == RULE


def test_allows_the_legitimate_write_after_an_approved_dispute(config):
    # Dev task_028: disputes are submitted (and auto-resolved as APPROVED by the task's settings), then updated.
    task = _task("task_028")
    env = fresh_env(config, task)
    actions = task.evaluation_criteria.actions
    first_update = next(i for i, a in enumerate(actions) if a.name == "call_discoverable_agent_tool")
    for a in actions[:first_update]:
        env.get_response(_tc(a.name, dict(a.arguments or {}), a.requestor))
    update = actions[first_update]
    assert guard.check(_tc(update.name, dict(update.arguments)), env.tools.db).allowed
    # the same write for a transaction with no approved dispute is still blocked
    other = dict(update.arguments, arguments=json.dumps({"transaction_id": "txn_d398545ca1a2",
                                                         "new_rewards_earned": "1 points"}))
    assert not guard.check(_tc(update.name, other), env.tools.db).allowed


def test_a_submitted_but_unapproved_dispute_does_not_satisfy_the_rule(config):
    env = fresh_env(config, _task("task_028"))
    env.tools.db.cash_back_disputes.data["d1"] = {"dispute_id": "d1", "transaction_id": "txn_57ecc6da56c2",
                                                  "status": "SUBMITTED"}
    call = _tc("call_discoverable_agent_tool", {"agent_tool_name": guard.REWARDS_TOOL, "arguments": json.dumps(
        {"transaction_id": "txn_57ecc6da56c2", "new_rewards_earned": "950 points"})})
    assert not guard.check(call, env.tools.db).allowed
    env.tools.db.cash_back_disputes.data["d1"].update(status="RESOLVED", resolution="APPROVED")
    assert guard.check(call, env.tools.db).allowed  # evidence is re-read on every call, not cached


def test_other_tools_are_not_affected():
    assert guard.check(_tc("KB_search", {"query": "x"}), None).allowed
    assert guard.check(_tc("call_discoverable_agent_tool", {"agent_tool_name": "freeze_debit_card_3892",
                                                            "arguments": "{}"}), None).allowed


def _update_calls(trace):
    return [c for c in trace["tool_calls"] if c["name"] == "call_discoverable_agent_tool"
            and "update_transaction_rewards_3847" in json.dumps(c["arguments"])]


def test_end_to_end_blocked_proposal_never_enters_the_trajectory_and_grading_still_runs(tmp_path):
    script = "task_028_unapproved_rewards_update.json"
    guarded, _ = scripted_run(tmp_path / "g", script=script, task_id="task_028", agent_guard=(RULE,))
    unguarded, _ = scripted_run(tmp_path / "u", script=script, task_id="task_028")
    # without the guard the write executes and is in the trajectory
    assert len(_update_calls(unguarded)) == 1 and "updated successfully" in json.dumps(unguarded["messages"])
    # with it: blocked, logged, not executed, not in the trajectory, and the official evaluation completed
    assert _update_calls(guarded) == []
    assert [e["event"] for e in guarded["guard"]["events"]] == ["blocked"]
    assert guarded["guard"]["events"][0]["rule"] == RULE
    assert "updated successfully" not in json.dumps(guarded["messages"])
    assert guarded["evaluation"] is not None and guarded["termination_reason"] == "user_stop"
    assert any("agent proposal guard" in f for f in guarded["research_eligibility"]["flags"])
    assert guarded["agent_inputs"]["passed"]
