"""Local runner: integrity, spending and trace checks. All zero-cost (scripted responses, no network).

Scripted runs exercise the real tau2 orchestrator, environment, tools and official evaluator; only
the model call is replaced. None of these results are benchmark results.
"""

import json
from pathlib import Path

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

import litellm  # noqa: E402

from bench import agent  # noqa: E402
from bench.budget import Budget, BudgetExceeded, Price  # noqa: E402
from bench.run import RunOptions, run  # noqa: E402
from bench.scripted import AGENT_MODEL, USER_MODEL, ScriptedLLM  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "bench" / "scripts"
DEV_TASK = "task_015"
TEST_TASK = "task_001"  # held out: in the test split


def scripted_run(tmp_path, script="task_015_reference.json", **overrides):
    opts = RunOptions(task_id=overrides.pop("task_id", DEV_TASK), agent_model=AGENT_MODEL, user_model=USER_MODEL,
                      retrieval_config=overrides.pop("retrieval_config", "bm25"), scripted=SCRIPTS / script,
                      out_dir=tmp_path, **overrides)
    trace, path = run(opts)
    assert json.loads(path.read_text())["run_id"] == trace["run_id"]  # the trace on disk is the one returned
    return trace


@pytest.fixture(scope="module")
def task():
    from tau2.runner.helpers import get_tasks

    return get_tasks("banking_knowledge", task_ids=[DEV_TASK])[0]


# --- integrity: what the agent may see -------------------------------------------------------

def test_factory_withholds_the_task(task):
    from tau2.data_model.tasks import Task

    built = agent.factory(tools=[], domain_policy="policy", llm="m", llm_args={}, task=task, audio_native_config=None)
    assert "task" in agent.last_build["withheld"]
    assert agent.task_references(built, Task) == []


def test_leakage_check_flags_reference_actions_and_hidden_instructions(task):
    clean = "You are a customer service agent for Rho-Bank. Search the knowledge base."
    assert agent.leakage_check(task, clean)["passed"]

    action_id = task.evaluation_criteria.actions[0].action_id
    leaked = agent.leakage_check(task, clean + f" expected action {action_id}")
    assert not leaked["passed"] and leaked["findings"][0]["field"] == "reference_actions"

    hidden = " ".join(task.user_scenario.instructions.split()[20:32])
    leaked = agent.leakage_check(task, clean + " " + hidden)
    assert not leaked["passed"] and leaked["findings"][0]["field"] == "user_instructions_or_notes"

    arg = json.loads(task.evaluation_criteria.actions[1].arguments["arguments"])["user_id"]
    assert not agent.leakage_check(task, clean + arg)["passed"]  # values inside JSON-encoded arguments too


def test_test_split_task_is_refused_and_still_traced(tmp_path):
    trace = scripted_run(tmp_path, task_id=TEST_TASK)
    assert trace["outcome"]["class"] == "configuration_failure"
    assert "test split" in trace["outcome"]["detail"]
    assert trace["messages"] == []


def test_golden_retrieval_is_refused(tmp_path):
    trace = scripted_run(tmp_path, retrieval_config="golden_retrieval")
    assert trace["outcome"]["class"] == "configuration_failure"


# --- the real integration path, scripted --------------------------------------------------------

def test_reference_conversation_scores_one_and_trace_is_complete(tmp_path):
    trace = scripted_run(tmp_path)
    assert trace["label"].startswith("MOCK")
    assert trace["outcome"] == {"class": "agent_success", "detail": "user_stop, reward=1.0"}
    assert trace["evaluation"]["db_check"] == {"db_match": True, "db_reward": 1.0}
    assert trace["missing_fields"] == []
    assert trace["agent_inputs"]["passed"] and "task" in trace["agent_inputs"]["withheld"]

    calls = [(c["by"], c["name"]) for c in trace["tool_calls"]]
    assert calls == [("agent", "KB_search"), ("agent", "give_discoverable_user_tool"),
                     ("user", "call_discoverable_user_tool")]
    assert trace["retrievals"][0]["doc_ids_returned"]  # retrieval results are recorded, not just queries
    assert trace["models_observed"] == {"assistant": [AGENT_MODEL], "user": [USER_MODEL]}

    spend = trace["spend"]
    roles = {c["role"] for c in spend["ledger"]}
    assert roles == {"agent", "user_simulator"}  # every call attributed
    assert spend["incurred"]["confirmed_usd"] > 0  # fake prices, real arithmetic
    assert spend["reported_by_benchmark"]["agent_cost"] == 0.0  # tau2's price lookup can't see what we count


def test_refusal_scores_zero_and_is_an_agent_failure(tmp_path):
    trace = scripted_run(tmp_path, script="task_015_refusal.json")
    assert trace["outcome"]["class"] == "agent_failure"
    assert trace["evaluation"]["reward"] == 0.0
    assert trace["missing_fields"] == []


# --- failure classes ------------------------------------------------------------------------

def test_budget_stops_the_run_before_the_cap_and_keeps_the_partial_trace(tmp_path):
    trace = scripted_run(tmp_path, budget_usd=0.015)
    assert trace["outcome"]["class"] == "interrupted"
    assert "BudgetExceeded" in trace["outcome"]["detail"]
    assert not trace["complete"] and len(trace["messages"]) > 1
    assert trace["spend"]["incurred"]["complete_incurred_upper_bound_usd"] <= 0.015


def test_provider_errors_are_retried_counted_and_classified(tmp_path, monkeypatch):
    def rate_limited(self, model, messages, **kwargs):
        raise litellm.RateLimitError("429 from provider", llm_provider="openai", model=model)

    monkeypatch.setattr(ScriptedLLM, "__call__", rate_limited)
    monkeypatch.setattr("bench.budget.time.sleep", lambda s: None)
    trace = scripted_run(tmp_path)
    assert trace["outcome"]["class"] == "provider_failure"
    ledger = trace["spend"]["ledger"]
    assert [c["attempt"] for c in ledger] == [1, 2, 3] and all(c["status"] == "failed" for c in ledger)
    # a failed request may still be billed, so its reservation stays counted as an upper bound
    assert trace["spend"]["incurred"]["unconfirmed_upper_bound_usd"] == pytest.approx(
        sum(c["reserved_usd"] for c in ledger))


def test_exhausted_script_is_a_harness_error_not_an_agent_result(tmp_path):
    short = tmp_path / "short.json"
    short.write_text(json.dumps({"agent": [], "user": [{"say": "Hi, I need help with a referral link."}]}))
    trace = scripted_run(tmp_path, script=short)
    assert trace["outcome"]["class"] == "harness_error"


def test_live_run_without_approved_budget_is_refused(tmp_path):
    opts = RunOptions(task_id=DEV_TASK, agent_model="some-model", user_model="some-model", out_dir=tmp_path)
    trace, _ = run(opts)
    assert trace["outcome"]["class"] == "configuration_failure"
    assert "budget" in trace["outcome"]["detail"]


def test_live_run_with_unpriced_model_is_refused_before_any_call(tmp_path):
    opts = RunOptions(task_id=DEV_TASK, agent_model="unpriced-model", user_model="unpriced-model",
                      budget_usd=0.5, out_dir=tmp_path)
    trace, _ = run(opts)
    assert trace["outcome"]["class"] == "configuration_failure"
    assert "PriceMissing" in trace["outcome"]["detail"]
    assert trace["spend"]["ledger"] == []


# --- budget arithmetic ----------------------------------------------------------------------

def test_budget_counts_in_flight_reservations():
    b = Budget(1.0, {"m": Price(1.0, 1.0, "test")})
    b.reserve("chat", "m", 1, 0.6)  # still in flight
    with pytest.raises(BudgetExceeded):
        b.reserve("chat", "m", 1, 0.5)


def test_failed_call_keeps_its_reservation_and_success_settles_at_usage():
    b = Budget(1.0, {"m": Price(1.0, 2.0, "test")})
    failed = b.reserve("chat", "m", 1, 0.3)
    b.settle_failed(failed, TimeoutError("no response"), started=0.0)
    ok = b.reserve("chat", "m", 2, 0.3)
    b.settle_ok(ok, input_tokens=100_000, output_tokens=10_000, provider_model="m-2026", started=0.0)
    s = b.summary()
    assert s["unconfirmed_upper_bound_usd"] == pytest.approx(0.3)
    assert s["confirmed_usd"] == pytest.approx(0.12)
    assert s["complete_incurred_upper_bound_usd"] == pytest.approx(0.42)
