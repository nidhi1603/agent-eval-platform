"""H009's two adapter options ($0): offer only non-mutating tools automatically; expose tools the model unlocks itself.
Unit checks plus scripted runs through the real tau2 path."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, agent  # noqa: E402
from tests.test_harness import LOG_089  # noqa: E402

EFFECTS = json.loads((REPO_ROOT / "research" / "h009" / "tool_effects.json").read_text())
FULL = {"version": "v3.1", "expose_model_unlocks": True}
READ = {"version": "v3.1", "expose_model_unlocks": True, "auto_offer": "non_mutating"}
WRITE_TOOL = "freeze_debit_card_3892"


def test_the_specs():
    full, read = agent.harness_record(FULL), agent.harness_record(READ)
    assert full["gates"] == read["gates"] and full["capability_search"] and read["transfer_hold_once"]
    assert "auto_offer" not in full and read["auto_offer"] == "non_mutating"
    assert full["expose_model_unlocks"] and read["expose_model_unlocks"]
    assert "auto_offer" not in agent.harness_record({"version": "v3.1"})     # v3.1 itself is unchanged
    with pytest.raises(ValueError, match="auto_offer"):
        agent.harness_record({"version": "v3.1", "auto_offer": "reads"})
    assert agent.register(harness=READ).endswith("_harness_v3.1_offer-nonmutating_expose-unlocks")


def test_the_classification_is_tau2s_effect_flag_and_matches_observed_effects():
    from tau2.environment.toolkit import MUTATES_STATE_ATTR

    tools = EFFECTS["tools"]
    assert all(v["classification"] == ("mutating" if v["mutates_state_flag"] else "non_mutating") for v in tools.values())
    observed = [v for v in tools.values() if v["observed"]]
    assert len(observed) >= 25
    # the only disagreement is conservative: flagged mutating, no change observed (kept as mutating)
    assert set(EFFECTS["disagreements"]) <= {"submit_interest_discrepancy_report_7294"}
    assert tools["emergency_credit_bureau_incident_transfer_1114"]["classification"] == "non_mutating"
    assert tools[WRITE_TOOL]["classification"] == "mutating" and MUTATES_STATE_ATTR


STEPS = [{"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
         {"call": "get_current_time", "args": {}},
         {"call": "log_verification", "args": LOG_089},
         {"call": "KB_search", "args": {"query": "freeze debit card lost stolen"}},
         {"call": "unlock_discoverable_agent_tool", "args": {"agent_tool_name": WRITE_TOOL}},
         {"say": "Done looking."}, {"say": "Goodbye."}, {"say": "Goodbye."}, {"say": "Goodbye."}]


def _run(tmp_path, spec):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "s.json"
    script.write_text(json.dumps({"agent": STEPS, "user": [{"say": "Hi, my debit card is lost."}, {"say": "OK."},
                                                            {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3}))
    trace, _ = run(RunOptions(task_id="task_089", agent_model=AGENT_MODEL, user_model=USER_MODEL,
                              retrieval_config="bm25", scripted=script, out_dir=tmp_path, agent_harness=spec,
                              budget_usd=20.0))
    return trace


def _adapter_unlocks(trace):
    return [c["arguments"]["agent_tool_name"] for m in trace["messages"] if m["role"] == "assistant"
            for c in m.get("tool_calls") or [] if c["name"] == "unlock_discoverable_agent_tool" and c["id"].startswith("adapter_unlock")]


def test_end_to_end_the_read_arm_withholds_mutating_tools_until_the_model_unlocks_one(tmp_path):
    tools = EFFECTS["tools"]
    t = _run(tmp_path, READ)
    auto = _adapter_unlocks(t)
    assert auto and all(tools[n]["classification"] == "non_mutating" for n in auto)
    events = t["harness"]["events"] + (t["harness"].get("adapter_events") or [])
    assert WRITE_TOOL in t["harness"]["offered"]                       # offered only after the model's own unlock
    assert WRITE_TOOL not in auto
    assert t["execution"]["finished"] and t["evaluation"] is not None


def test_end_to_end_the_full_arm_offers_mutating_tools_automatically(tmp_path):
    t = _run(tmp_path, FULL)
    tools = EFFECTS["tools"]
    assert any(tools[n]["classification"] == "mutating" for n in _adapter_unlocks(t))
    assert t["execution"]["finished"] and t["evaluation"] is not None
