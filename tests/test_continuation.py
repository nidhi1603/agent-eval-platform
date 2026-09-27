"""Agent-only continuations from saved prefixes (bench/continuation.py). Zero-cost: scripted model."""

import json
from pathlib import Path

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, continuation  # noqa: E402
from bench.budget import Budget, Limits, install  # noqa: E402
from bench.scripted import AGENT_MODEL, FAKE_PRICES, ScriptedLLM  # noqa: E402

PLAN = json.loads((REPO_ROOT / "experiments" / "D001_plan.json").read_text())
CASES = {c["id"]: c for c in PLAN["cases"]}


def _run(case_id, agent_steps, tmp_path, variant="baseline"):
    budget = Budget(1.0, FAKE_PRICES, tmp_path / f"{case_id}_{variant}.jsonl")
    with install(budget, Limits(), send=ScriptedLLM({"agent": agent_steps})):
        return continuation.continue_case(CASES[case_id], variant, AGENT_MODEL, {})


def test_agent_view_excludes_the_customers_own_tool_traffic():
    trace = json.loads((REPO_ROOT / "results/S002/task_029/trace.json").read_text())
    seen = continuation.agent_visible(trace["messages"], len(trace["messages"]))
    assert all(not (m["role"] == "tool" and m.get("requestor") == "user") for m in seen)
    assert all(not (m["role"] == "user" and m.get("tool_calls")) for m in seen)


def test_prefixes_end_where_the_customer_just_spoke():
    for case in PLAN["cases"]:
        trace = json.loads((REPO_ROOT / case["source_trace"]).read_text())
        seen = continuation.agent_visible(trace["messages"], case["prefix_end"])
        assert seen[-1]["role"] == "user", case["id"]
        # the saved agent's next step is the observed failure, and it is NOT included in the prefix
        assert trace["messages"][case["prefix_end"]]["role"] == "assistant", case["id"]


def test_permitted_case_scores_a_correct_unlock_and_call(tmp_path):
    tool = "get_all_user_accounts_by_user_id_3847"
    r = _run("P1", [{"call": "unlock_discoverable_agent_tool", "args": {"agent_tool_name": tool}},
                    {"call": "call_discoverable_agent_tool",
                     "args": {"agent_tool_name": tool, "arguments": json.dumps({"user_id": "lm83h7k2p5"})}},
                    {"say": "I found your accounts."}], tmp_path)
    assert r["stopped"] == "text" and r["score"]["invoked_expected_tool"]
    assert r["score"]["possible_invented_values"] == [] and "Accounts for user" in r["calls"][1]["result"]


def test_invented_argument_values_are_flagged(tmp_path):
    tool = "get_all_user_accounts_by_user_id_3847"
    r = _run("P1", [{"call": "unlock_discoverable_agent_tool", "args": {"agent_tool_name": tool}},
                    {"call": "call_discoverable_agent_tool",
                     "args": {"agent_tool_name": tool, "arguments": json.dumps({"user_id": "zz_made_up_99"})}},
                    {"say": "Done."}], tmp_path)
    assert "zz_made_up_99" in r["score"]["possible_invented_values"]


def test_prerequisite_case_records_a_forbidden_write(tmp_path):
    tool = "update_transaction_rewards_3847"
    r = _run("M1", [{"call": "unlock_discoverable_agent_tool", "args": {"agent_tool_name": tool}},
                    {"call": "call_discoverable_agent_tool", "args": {"agent_tool_name": tool, "arguments": json.dumps(
                        {"transaction_id": "txn_d398545ca1a2", "new_rewards_earned": "1000 points"})}},
                    {"say": "Updated."}], tmp_path)
    assert r["score"]["forbidden_proposed"] == [tool] and r["score"]["forbidden_executed"] == [tool]


def test_a_text_reply_ends_the_continuation_and_variants_apply(tmp_path):
    r = _run("A1", [{"say": "I can't look up accounts by phone. Could you share your email or user ID?"}],
             tmp_path, variant="discovery_both_v1")
    assert r["stopped"] == "text" and r["calls"] == [] and r["variant"] == "discovery_both_v1"


def test_main_runs_the_frozen_plan_end_to_end_with_a_scripted_model(tmp_path, monkeypatch):
    import contextlib

    from bench import budget as B

    plan = dict(PLAN, budget_usd_total=1.0)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    real_install = B.install
    scripted = ScriptedLLM({"agent": [{"say": "Could you share your email or user ID?"}] * len(plan["runs"])})

    @contextlib.contextmanager
    def fake_install(budget, limits, send=None, embedder_cls=None):
        with real_install(budget, limits, send=scripted):
            yield budget

    monkeypatch.setattr(B, "install", fake_install)
    monkeypatch.setattr(B, "load_prices", lambda: FAKE_PRICES | {"gpt-5-mini": FAKE_PRICES[AGENT_MODEL]})
    assert continuation.main([str(plan_file), "--approved-usd", "1.0", "--out-dir", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "D001_results.json").read_text())
    assert len(out["results"]) == 48 and all(r.get("stopped") == "text" for r in out["results"])
    assert {r["variant"] for r in out["results"]} == set(PLAN["variants"])
    with pytest.raises(SystemExit):  # the approval must match the plan
        continuation.main([str(plan_file), "--approved-usd", "2.0", "--out-dir", str(tmp_path / "x")])
