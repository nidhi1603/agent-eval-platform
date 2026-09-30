"""Harness v3.1 = v3 + a transfer hold that fires at most once per conversation and says the call was not executed
and that a repeat will be (research/v3_1/README.md). $0: unit tests and scripted runs through the real tau2 path."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import agent, harness  # noqa: E402
from tests.test_harness import TRANSFER, _Conv, _calls, _ctx, _draft, _run  # noqa: E402

V31 = {"transfer_hold_once": True, "transfer_holds": 0}


# ---- the check -------------------------------------------------------------------------------------------------------

def test_a_held_transfer_says_it_was_not_executed_and_that_a_repeat_will_be():
    ev = _Conv().search("freeze my card").ev()
    [f] = harness.review(_draft(calls=[TRANSFER]), ev, {**_ctx(), **V31})
    assert f.gate == "search_before_giving_up" and f.detail["trigger"] == "transfer"
    assert f.message.startswith(harness.TRANSFER_NOT_EXECUTED) and f.message.endswith(harness.TRANSFER_STILL_OPEN)
    assert "NOT executed" in f.message and "has not been transferred" in f.message and "will be executed" in f.message
    assert '"freeze my card"' in f.message            # the v1 remediation is still there
    assert "does not authorize any action" not in f.message  # it would contradict "call it again"


def test_a_transfer_is_held_at_most_once_per_conversation():
    ev = _Conv().search("freeze my card").ev()
    assert harness.review(_draft(calls=[TRANSFER]), ev, {**_ctx(), **V31, "transfer_holds": 1}) == []
    # v1 and v3 are unchanged: the same transfer is held again, with the original text
    [f] = harness.review(_draft(calls=[TRANSFER]), ev, {**_ctx(), "transfer_holds": 1})
    assert f.message.startswith("Harness check (not shown to the customer): you are about to transfer")
    assert f.message.endswith("This check does not authorize any action.")


def test_a_denial_is_unchanged_in_v3_1():
    ev = _Conv().search("a").ev()
    denial = _draft("I don't have access to account-level tools here.")
    [old] = harness.review(denial, ev, _ctx())
    [new] = harness.review(denial, ev, {**_ctx(), **V31, "transfer_holds": 1})   # a held transfer does not exempt it
    assert new.message == old.message and new.detail["trigger"] == "denial"


# ---- the spec --------------------------------------------------------------------------------------------------------

def test_v3_1_is_v3_plus_the_once_only_transfer_hold():
    v3, v31 = agent.harness_record({"version": "v3"}), agent.harness_record({"version": "v3.1"})
    assert v31["gates"] == v3["gates"] and v31["capability_search"] is True and v31["transfer_hold_once"] is True
    assert v31["name"] == "harness_v3.1" and "transfer_hold_once" not in v3
    assert "transfer_hold_once" not in agent.harness_record({}) and "transfer_hold_once" not in agent.harness_record({"version": "v2"})
    with pytest.raises(ValueError, match="needs the adapter"):
        agent.harness_record({"version": "v3.1", "adapter": False})
    assert agent.register(harness={"version": "v3.1"}).endswith("_harness_v3.1")


# ---- end to end -------------------------------------------------------------------------------------------------------

T = {"call": "transfer_to_human_agents", "args": {"summary": "needs help"}}
# one search, a transfer (held), a reply to the customer, then a transfer again in a LATER turn
STEPS = [{"call": "KB_search", "args": {"query": "debit card"}}, T, {"say": "Let me check one more thing."},
         T, {"say": "Goodbye."}, {"say": "Goodbye."}, {"say": "Goodbye."}]


def _held(trace):
    return [e for e in trace["harness"]["events"] if e["event"] == "held"]


def test_end_to_end_v3_1_holds_the_transfer_once_then_executes_it(tmp_path):
    t = _run(tmp_path, STEPS, harness_spec={"version": "v3.1"})
    assert [n for n, _ in _calls(t)].count("transfer_to_human_agents") == 1
    [h] = _held(t)
    assert h["gate"] == "search_before_giving_up" and h["message"].startswith(harness.TRANSFER_NOT_EXECUTED)
    view = json.dumps(t["harness"]["model_view"])
    assert "NOT executed" in view and "will be executed" in view
    assert "Harness check" not in json.dumps(t["messages"])      # private: never in the benchmark trajectory
    assert t["execution"]["finished"] and t["evaluation"] is not None and t["agent_inputs"]["passed"]


def test_end_to_end_v3_holds_the_later_transfer_again(tmp_path):
    t = _run(tmp_path, STEPS, harness_spec={"version": "v3"})
    assert [n for n, _ in _calls(t)].count("transfer_to_human_agents") == 0
    assert [e["gate"] for e in _held(t)] == ["search_before_giving_up"] * 2
    assert "NOT executed" not in json.dumps(t["harness"]["model_view"])


def test_end_to_end_v3_1_an_immediate_repeat_still_goes_through(tmp_path):
    t = _run(tmp_path, [STEPS[0], T, T, {"say": "Goodbye."}, {"say": "Goodbye."}], harness_spec={"version": "v3.1"})
    assert [n for n, _ in _calls(t)].count("transfer_to_human_agents") == 1 and len(_held(t)) == 1
