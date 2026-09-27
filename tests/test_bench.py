"""Local runner: integrity, spend admission control and trace checks. All zero-cost (no network).

Scripted runs exercise the real tau2 orchestrator, environment, tools and official evaluator; only
the model call is replaced. None of these results are benchmark results.
"""

import json
import math
from pathlib import Path

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

import litellm  # noqa: E402

from bench import agent  # noqa: E402
from bench import budget as B  # noqa: E402
from bench.run import RunOptions, run  # noqa: E402
from bench.scripted import AGENT_MODEL, USER_MODEL, ScriptedLLM  # noqa: E402
from bench.trace import attribute  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "bench" / "scripts"
DEV_TASK = "task_015"
TEST_TASK = "task_001"  # held out: in the test split
PRICES = {"m": B.Price(1.0, 2.0, "test")}


def scripted_run(tmp_path, script="task_015_reference.json", **overrides):
    opts = RunOptions(task_id=overrides.pop("task_id", DEV_TASK), agent_model=AGENT_MODEL, user_model=USER_MODEL,
                      retrieval_config=overrides.pop("retrieval_config", "bm25"), scripted=SCRIPTS / script,
                      out_dir=tmp_path, **overrides)
    trace, path = run(opts)
    return trace, path.parent


@pytest.fixture(scope="module")
def task():
    from tau2.runner.helpers import get_tasks

    return get_tasks("banking_knowledge", task_ids=[DEV_TASK])[0]


# --- what the agent may see -------------------------------------------------------------------

def test_factory_withholds_the_task(task):
    from tau2.data_model.tasks import Task

    built = agent.factory(tools=[], domain_policy="policy", llm="m", llm_args={}, task=task, audio_native_config=None)
    assert "task" in agent.last_build["withheld"]
    assert agent.task_references(built, Task) == []
    assert agent.task_references({"deep": [{"x": task}]}, Task)  # the bounded search does find a planted Task


def test_string_scan_flags_planted_reference_content(task):
    clean = "You are a customer service agent for Rho-Bank. Search the knowledge base."
    assert agent.leakage_check(task, clean)["passed"]
    action_id = task.evaluation_criteria.actions[0].action_id
    assert agent.leakage_check(task, clean + f" expected action {action_id}")["findings"][0]["field"] == "reference_actions"
    hidden = " ".join(task.user_scenario.instructions.split()[20:32])
    assert agent.leakage_check(task, clean + " " + hidden)["findings"][0]["field"] == "user_instructions_or_notes"
    arg = json.loads(task.evaluation_criteria.actions[1].arguments["arguments"])["user_id"]
    assert not agent.leakage_check(task, clean + arg)["passed"]  # values inside JSON-encoded arguments too


def test_public_overlap_is_reported_for_review_not_used_to_drop_the_task(tmp_path):
    # task_085's reference arguments contain a timestamp that also appears in the (task-independent) policy.
    trace, _ = scripted_run(tmp_path, script="task_085_side_channel.json", task_id="task_085")
    inputs = trace["agent_inputs"]
    assert inputs["passed"] and inputs["system_prompt_identical_without_answer_key"] and inputs["tool_schemas_identical_without_answer_key"]
    assert inputs["string_scan"]["findings"] and inputs["string_scan"]["interpretation"]
    assert trace["execution"]["finished"]


def test_test_split_task_is_refused_and_still_traced(tmp_path):
    trace, _ = scripted_run(tmp_path, task_id=TEST_TASK)
    assert trace["attribution"]["cause"] == "configuration"
    assert "test split" in trace["attribution"]["evidence"]


def test_golden_retrieval_is_refused(tmp_path):
    trace, _ = scripted_run(tmp_path, retrieval_config="golden_retrieval")
    assert trace["attribution"]["cause"] == "configuration"


def test_disallowed_model_arguments_are_refused(tmp_path):
    trace, _ = scripted_run(tmp_path, agent_llm_args={"n": 3})
    assert trace["attribution"]["cause"] == "configuration"
    assert "RequestNotAllowed" in trace["attribution"]["evidence"]


# --- answer independence (differential replay) ------------------------------------------------

def test_side_channel_is_detected_per_trajectory_and_flagged_not_dropped(tmp_path):
    trace, _ = scripted_run(tmp_path, script="task_085_side_channel.json", task_id="task_085")
    dep = trace["answer_independence"]["agent_visible_outputs_depending_on_hidden_reference"]
    assert [d["tool"] for d in dep] == ["list_discoverable_agent_tools"]
    assert trace["answer_independence"]["nondeterministic_outputs"] == []
    assert any("side channel" in f for f in trace["research_eligibility"]["flags"])
    assert trace["counts"]["side_channel_tool_calls"] == 1


def test_reference_run_has_no_answer_dependent_outputs(tmp_path):
    trace, _ = scripted_run(tmp_path)
    ind = trace["answer_independence"]
    assert ind["agent_visible_outputs_depending_on_hidden_reference"] == []
    assert ind["replay_matches_recorded"] and ind["conclusive"] and ind["normalized"] == ["kb_search_timing_footer"]


# --- the real integration path, scripted ------------------------------------------------------

def test_reference_conversation_scores_one_and_trace_is_complete(tmp_path):
    trace, run_dir = scripted_run(tmp_path)
    assert trace["label"].startswith("MOCK")
    assert trace["evaluation"]["reward"] == 1.0 and trace["evaluation"]["db_check"]["db_match"]
    assert trace["termination_reason"] == "user_stop"
    assert trace["attribution"]["cause"] == "none"
    assert trace["trace_complete"] and trace["missing_fields"] == []
    elig = trace["research_eligibility"]
    assert elig["reliability"] == {"eligible": False, "reasons": ["mock run (scripted responses)"]}
    assert elig["cost"] == {"eligible": False, "reasons": ["mock run (scripted responses)"]}
    assert trace["persisted"] is True

    calls = [(c["by"], c["name"]) for c in trace["tool_calls"]]
    assert calls == [("agent", "KB_search"), ("agent", "give_discoverable_user_tool"),
                     ("user", "call_discoverable_user_tool")]
    assert trace["retrievals"][0]["doc_ids_returned"]
    assert trace["models_observed"] == {"assistant": [AGENT_MODEL], "user": [USER_MODEL]}
    assert trace["config"]["user_simulator"]["llm_args"] == {"reasoning_effort": "low"}  # applied, not only noted

    spend = trace["spend"]
    assert {c["role"] for c in spend["ledger"]} == {"agent", "user_simulator"}
    assert spend["incurred"]["unresolved_calls"] == 0
    assert spend["reported_by_benchmark"]["agent_cost"] == 0.0  # tau2's lookup can't price what we count

    # persisted artefacts: manifest first, journal with a reserve before every settle
    assert json.loads((run_dir / "manifest.json").read_text())["state"] == "finalized"
    events = [json.loads(line) for line in (run_dir / "ledger.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["reserve", "settle"] * len(spend["ledger"])
    assert all(r["status"] == "in_flight" for r in events[::2])


def test_refusal_is_an_agent_failure_per_the_official_evaluator(tmp_path):
    trace, _ = scripted_run(tmp_path, script="task_015_refusal.json")
    assert trace["evaluation"]["reward"] == 0.0
    assert trace["attribution"]["cause"] == "agent_per_official_evaluator"


def test_run_directories_are_unique_even_within_one_second(tmp_path):
    dirs = {scripted_run(tmp_path, task_id=TEST_TASK)[1] for _ in range(3)}
    assert len(dirs) == 3


def test_finalization_failure_is_recorded_and_fails_the_command(tmp_path, monkeypatch, capsys):
    def broken(trace):
        raise RuntimeError("injected finalization error")  # a raised error, not a real full disk

    monkeypatch.setattr("bench.run.research_eligibility", broken)
    trace, run_dir = scripted_run(tmp_path)
    assert trace["persisted"] is False and trace["execution"]["finished"]  # the conversation itself finished
    assert (run_dir / "trace_error.json").exists() and not (run_dir / "trace.json").exists()
    assert json.loads((run_dir / "manifest.json").read_text())["state"] == "finalization_failed"
    assert (run_dir / "ledger.jsonl").exists()

    from bench.run import main
    code = main(["--task", DEV_TASK, "--retrieval-config", "bm25", "--out-dir", str(tmp_path),
                 "--scripted", str(SCRIPTS / "task_015_reference.json")])
    assert code == 2  # the command fails when the required trace was not saved


# --- failure attribution ------------------------------------------------------------------------

def test_budget_stops_the_run_and_keeps_the_partial_trace(tmp_path):
    trace, _ = scripted_run(tmp_path, budget_usd=0.03)
    assert trace["attribution"]["cause"] == "interrupted"
    assert "BudgetExceeded" in trace["attribution"]["evidence"]
    assert not trace["execution"]["finished"] and len(trace["messages"]) > 1
    assert trace["spend"]["incurred"]["upper_bound_usd"] <= 0.03


def test_provider_errors_are_retried_reserved_and_attributed(tmp_path, monkeypatch):
    def rate_limited(self, model, messages, **kwargs):
        raise litellm.RateLimitError("429 from provider", llm_provider="openai", model=model)

    monkeypatch.setattr(ScriptedLLM, "__call__", rate_limited)
    monkeypatch.setattr("bench.budget.time.sleep", lambda s: None)
    trace, _ = scripted_run(tmp_path)
    assert trace["attribution"]["cause"] == "provider"
    assert trace["execution"]["error_in_role"] == "user_simulator"
    ledger = trace["spend"]["ledger"]
    assert [c["attempt"] for c in ledger] == [1, 2, 3] and all(c["status"] == "failed" for c in ledger)
    assert trace["spend"]["incurred"]["unresolved_reservations_usd"] == pytest.approx(sum(c["reserved_usd"] for c in ledger))


def test_context_window_error_is_attributed_to_the_failing_caller(tmp_path, monkeypatch):
    def too_long(self, model, messages, **kwargs):
        raise litellm.ContextWindowExceededError("context too long", model=model, llm_provider="openai")

    monkeypatch.setattr(ScriptedLLM, "__call__", too_long)
    trace, _ = scripted_run(tmp_path)
    assert trace["attribution"]["cause"] == "user_simulator"  # the user simulator speaks first


def test_usage_over_the_reserved_bound_stops_the_run(tmp_path, monkeypatch):
    real_call = ScriptedLLM.__call__

    def ignores_max_tokens(self, model, messages, **kwargs):
        response = real_call(self, model, messages, **kwargs)
        response.usage.completion_tokens = kwargs["max_tokens"] + 1
        return response

    monkeypatch.setattr(ScriptedLLM, "__call__", ignores_max_tokens)
    trace, _ = scripted_run(tmp_path)
    assert trace["attribution"]["cause"] == "harness" and "bound" in trace["attribution"]["evidence"]
    assert [c["status"] for c in trace["spend"]["ledger"]] == ["bound_violation"]  # no further calls


def test_missing_usage_keeps_the_reservation(tmp_path, monkeypatch):
    real_call = ScriptedLLM.__call__

    def no_usage(self, model, messages, **kwargs):
        response = real_call(self, model, messages, **kwargs)
        response.usage = None
        return response

    monkeypatch.setattr(ScriptedLLM, "__call__", no_usage)
    trace, _ = scripted_run(tmp_path)
    inc = trace["spend"]["incurred"]
    assert inc["usage_based_estimate_usd"] == 0 and inc["unresolved_calls"] == len(trace["spend"]["ledger"]) > 0
    assert inc["upper_bound_usd"] == pytest.approx(sum(c["reserved_usd"] for c in trace["spend"]["ledger"]))
    elig = trace["research_eligibility"]
    assert "spend has unresolved calls" in elig["cost"]["reasons"]
    assert "spend has unresolved calls" not in elig["reliability"]["reasons"]  # outcome still usable


def test_attribution_of_termination_reasons():
    tool_err = lambda who: {"role": "tool", "error": True, "requestor": who}  # noqa: E731
    assert attribute("too_many_errors", 0.0, None, [tool_err("assistant")] * 3, [])["cause"] == "agent"
    assert attribute("too_many_errors", 0.0, None, [tool_err("user")] * 3, [])["cause"] == "user_simulator"
    assert attribute("too_many_errors", 0.0, None, [tool_err("user"), tool_err("assistant")], [])["cause"] == "mixed"
    assert attribute("timeout", 0.0, None, [], [{"role": "agent", "duration_s": 3.0}])["cause"] == "unattributed"
    assert attribute("max_steps", 0.0, None, [], [])["cause"] == "unattributed"
    assert attribute("something_new", 0.0, None, [], [])["cause"] == "unclassified"
    assert attribute("user_stop", None, None, [], [])["cause"] == "unclassified"


def test_live_run_without_approved_budget_is_refused(tmp_path):
    trace, _ = run(RunOptions(task_id=DEV_TASK, agent_model="some-model", out_dir=tmp_path))
    assert trace["attribution"]["cause"] == "configuration" and "budget" in trace["attribution"]["evidence"]


def test_live_run_with_unpriced_model_is_refused_before_any_call(tmp_path):
    trace, run_dir = run(RunOptions(task_id=DEV_TASK, agent_model="unpriced-model", budget_usd=0.5, out_dir=tmp_path))
    assert "PriceMissing" in trace["attribution"]["evidence"]
    assert trace["spend"]["ledger"] == [] and not (run_dir / "ledger.jsonl").exists()


# --- budget arithmetic and validation --------------------------------------------------------

@pytest.mark.parametrize("cap", [math.nan, math.inf, -1.0, 0.0, "1"])
def test_invalid_caps_are_rejected(cap):
    with pytest.raises(B.InvalidValue):
        B.Budget(cap, PRICES)


@pytest.mark.parametrize("price", [math.nan, math.inf, -0.1])
def test_invalid_prices_are_rejected(price):
    with pytest.raises(B.InvalidValue):
        B.Price(price, 1.0, "bad")


def test_invalid_limits_are_rejected():
    for bad in ({"max_output_tokens": 0}, {"max_attempts": 0}, {"request_timeout_s": math.nan}):
        with pytest.raises(B.InvalidValue):
            B.Limits(**bad)


def test_in_flight_reservations_count_toward_the_cap_and_the_totals():
    b = B.Budget(1.0, PRICES)
    b.reserve("chat", "m", 1, in_bound=200_000, out_bound=100_000)  # $0.40, still in flight
    assert b.summary()["upper_bound_usd"] == pytest.approx(0.4)
    with pytest.raises(B.BudgetExceeded):
        b.reserve("chat", "m", 1, in_bound=500_000, out_bound=100_000)  # $0.70 more


def test_failed_call_keeps_its_reservation_and_success_settles_at_usage():
    b = B.Budget(1.0, PRICES)
    failed = b.reserve("chat", "m", 1, 100_000, 50_000)
    b.settle_unresolved(failed, TimeoutError("no response"), started=0.0)
    ok = b.reserve("chat", "m", 2, 100_000, 50_000)
    b.settle_ok(ok, {"prompt_tokens": 100_000, "completion_tokens": 10_000}, "m-2026", started=0.0)
    s = b.summary()
    assert s["unresolved_reservations_usd"] == pytest.approx(0.2)
    assert s["usage_based_estimate_usd"] == pytest.approx(0.12)
    assert s["upper_bound_usd"] == pytest.approx(0.32)


def test_outgoing_chat_request_carries_the_enforced_limits():
    sent = {}

    def capture(**kwargs):
        sent.update(kwargs)
        return litellm.ModelResponse(model="m", choices=[{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
                                     usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11})

    limits = B.Limits(max_output_tokens=256, request_timeout_s=30.0)
    complete = B.metered_completion(B.Budget(1.0, PRICES), limits, capture)
    complete("m", [{"role": "user", "content": "hello"}], temperature=0.0, num_retries=3)
    assert sent["max_tokens"] == 256 and sent["num_retries"] == 0 and sent["max_retries"] == 0 and sent["timeout"] == 30.0
    with pytest.raises(B.RequestNotAllowed):
        complete("m", [{"role": "user", "content": "hello"}], n=2)


def test_embedding_sdk_retries_are_disabled_and_each_request_reserved(monkeypatch):
    monkeypatch.setattr("bench.budget.time.sleep", lambda s: None)

    class RateLimitError(Exception):
        pass

    class FakeClient:
        options = {}
        fail_first = True

        def with_options(self, **kw):
            FakeClient.options = kw
            return self

        @property
        def embeddings(self):
            return self

        def create(self, input, model):
            if FakeClient.fail_first:
                FakeClient.fail_first = False
                raise RateLimitError("429")
            usage = type("U", (), {"total_tokens": 7})()
            return type("R", (), {"usage": usage, "data": [type("D", (), {"embedding": [0.1, 0.2]})()]})()

    class Base:
        def __init__(self, model="emb"):
            self.model, self.client = model, FakeClient()

    b = B.Budget(1.0, {"emb": B.Price(0.1, 0.0, "test")})
    embedder = B.metered_embedder(b, B.Limits(), Base)()
    embedder.embed(["hello"])
    assert FakeClient.options["max_retries"] == 0
    assert [(c.attempt, c.status) for c in b.calls] == [(1, "failed"), (2, "ok")]


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": 100},  # completion count missing
    {"prompt_tokens": 100, "completion_tokens": None},
    {"prompt_tokens": 100.9, "completion_tokens": 4},
    {"prompt_tokens": 100, "completion_tokens": 4.9},
    {"prompt_tokens": True, "completion_tokens": 4},
    {"prompt_tokens": -1, "completion_tokens": 4},
    None,
])
def test_malformed_usage_keeps_the_reservation(usage):
    b = B.Budget(1.0, PRICES)
    call = b.reserve("chat", "m", 1, 1000, 100)
    b.settle_ok(call, usage, "m", started=0.0)
    assert call.status == "usage_unresolved" and call.cost_usd is None
    assert b.summary()["unresolved_reservations_usd"] == pytest.approx(call.reserved_usd)


def test_timing_normalization_only_touches_the_search_footer():
    from bench.independence import normalize

    body = "1. Doc\n   Content: see [Timing: this is document text]\n"
    assert normalize("KB_search", body + "[Timing: retrieval=1ms, total=1ms]") == body + "[Timing: <normalized>]"
    assert normalize("KB_search", body + "[Timing: retrieval=1ms, reranking=2ms, total=3ms]") == body + "[Timing: <normalized>]"
    assert normalize("KB_search", body) == body  # mid-text match left alone
    assert normalize("get_user_information_by_id", "x [Timing: 1ms]") == "x [Timing: 1ms]"


def test_failed_diagnostic_does_not_fail_a_finished_trial(tmp_path, monkeypatch):
    def broken(config, task, messages):
        raise RuntimeError("diagnostic crashed")

    monkeypatch.setattr("bench.independence.check", broken)
    trace, _ = scripted_run(tmp_path)
    assert trace["execution"]["finished"] and trace["evaluation"]["reward"] == 1.0
    assert trace["attribution"]["cause"] == "none"
    assert trace["answer_independence"]["conclusive"] is False
    assert any("inconclusive" in f for f in trace["research_eligibility"]["flags"])


def test_diagnostic_can_be_rerun_from_a_saved_run(tmp_path):
    from bench.independence import recheck

    trace, run_dir = scripted_run(tmp_path, script="task_085_side_channel.json", task_id="task_085")
    again = recheck(run_dir)
    assert [d["tool"] for d in again["agent_visible_outputs_depending_on_hidden_reference"]] == ["list_discoverable_agent_tools"]


def test_cache_aware_estimate_reproduces_the_s001_call():
    # S001 call 3: gpt-5-mini, prompt 6157 (2560 cached), completion 250; tau2 recorded $0.001463
    b = B.Budget(1.0, {"gpt-5-mini": B.Price(0.25, 2.0, "test", cached_input_per_mtok=0.025)})
    call = b.reserve("chat", "gpt-5-mini", 1, 30_000, 4096)
    b.settle_ok(call, {"prompt_tokens": 6157, "completion_tokens": 250,
                       "prompt_tokens_details": {"cached_tokens": 2560}}, "gpt-5-mini-2025-08-07", started=0.0)
    assert call.cost_with_cache_usd == pytest.approx(0.001463, abs=1e-6)
    assert call.cost_usd > call.cost_with_cache_usd  # budgeting keeps the conservative full-price figure
    assert b.summary()["cache_aware_estimate_usd"] == pytest.approx(0.001463, abs=1e-6)


def test_batch_shares_one_allocation_and_records_every_scheduled_task(monkeypatch, tmp_path):
    from bench import batch

    caps = []

    def fake_run(opts):
        caps.append(opts.budget_usd)
        spent = min(0.45, opts.budget_usd)  # each run uses up to $0.45 of upper-bound spend
        exposed = [{"tool": "list_discoverable_agent_tools"}] if opts.task_id == "b" else []
        trace = {"run_id": opts.task_id, "execution": {"finished": spent == 0.45}, "evaluation": {"reward": 0.0},
                 "spend": {"incurred": {"upper_bound_usd": spent}}, "persisted": True,
                 "answer_independence": {"conclusive": opts.task_id != "c",  # c: nondeterministic outputs
                                         "agent_visible_outputs_depending_on_hidden_reference": exposed}}
        return trace, tmp_path / f"{opts.task_id}.json"

    monkeypatch.setattr(batch, "run", fake_run)
    plan = {"batch_id": "T", "tasks": ["a", "b", "c", "d"], "budget_usd_total": 1.0,
            "settings": {"agent_model": "m", "agent_args": {}, "user_model": "u", "user_args": {},
                         "retrieval_config": "bm25", "seed": 300, "max_steps": 200}}
    summary = batch.run_batch(plan, 1.0)
    assert caps == [1.0, 0.55, pytest.approx(0.1)]  # each cap = allocation minus earlier upper-bound spend
    assert [r["status"] for r in summary["results"]] == ["finished", "finished", "interrupted_or_failed", "not_run"]
    assert summary["spend_upper_bound_usd"] <= 1.0 and summary["scheduled"] == 4
    # exposed runs keep their official outcome and are counted, not dropped
    assert [r.get("answer_dependent_outputs_seen") for r in summary["results"]] == [0, 1, 0, None]
    assert summary["exposed_runs"] == 1 and summary["results"][1]["official_reward"] == 0.0
    # an inconclusive diagnostic is unknown, not "no exposure"; a not-run task has no status
    assert [r.get("exposure_status") for r in summary["results"]] == ["not_observed", "exposed", "unknown", None]
    assert summary["exposure_unknown_runs"] == 1
    with pytest.raises(SystemExit):
        batch.run_batch(plan, 2.0)  # the approval must match the committed plan
