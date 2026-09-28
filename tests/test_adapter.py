"""Direct-tool adapter (bench/adapter.py), milestone 1: it works, and it is equivalent where it must be.
Zero cost: scripted model and customer, the official tau2 evaluator, real BM25 retrieval.

Equivalence means: the same task, solved by a scripted agent through the benchmark's wrappers or through the
adapter's direct calls, gets the same official grade and leaves the same graded database."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import adapter  # noqa: E402
from bench.run import RunOptions, run  # noqa: E402
from bench.scripted import AGENT_MODEL, USER_MODEL  # noqa: E402

UNLOCK, CALL = "unlock_discoverable_agent_tool", "call_discoverable_agent_tool"
OPEN = "open_bank_account_4821"
T058_LOG = {"name": "Taylor Brooks", "user_id": "tb58a3c9d2", "address": "2156 Hawthorne Boulevard, Portland, OR 97214",
            "email": "taylor.brooks@gmail.com", "phone_number": "503-555-0847", "date_of_birth": "09/12/1993",
            "time_verified": "2025-11-14 03:40:00 EST"}
T058_CARD_USER = {"card_type": "EcoCard", "customer_name": "Taylor Brooks", "annual_income": 85000, "rho_bank_subscription": False}
T058_OPEN = {"user_id": "tb58a3c9d2", "account_type": "savings", "account_class": "Silver Account"}
KB_058 = {"call": "KB_search", "args": {"query": "open a new checking bank account for an existing customer"}}
EMERGENCY = "emergency_credit_bureau_incident_transfer_1114"
KB_035 = {"call": "KB_search", "args": {"query": "credit bureau incident reported delinquency score drop emergency transfer"}}
USER = [{"say": "Hi, I'd like to open a Silver savings account and apply for an EcoCard."},
        {"call": "apply_for_credit_card", "args": T058_CARD_USER},  # a customer tool: the customer applies
        {"say": "Thanks! ###STOP###"}]


def _run(tmp_path, task_id, agent_steps, user_steps=USER, tool_adapter=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"description": "MOCK adapter equivalence", "agent": agent_steps, "user": user_steps}))
    opts = RunOptions(task_id=task_id, agent_model=AGENT_MODEL, user_model=USER_MODEL, retrieval_config="bm25",
                      scripted=script, out_dir=tmp_path, agent_tool_adapter=tool_adapter)
    trace, _ = run(opts)
    return trace


def _env_calls(trace):
    return [(tc["name"], tc["arguments"]) for m in trace["messages"] if m["role"] == "assistant"
            for tc in (m.get("tool_calls") or [])]


def test_058_wrappers_and_direct_calls_get_the_same_official_grade(tmp_path):
    common = [KB_058, {"call": "log_verification", "args": T058_LOG}]
    wrapped = _run(tmp_path / "w", "task_058", common + [
        {"call": UNLOCK, "args": {"agent_tool_name": OPEN}},
        {"call": CALL, "args": {"agent_tool_name": OPEN, "arguments": json.dumps(T058_OPEN)}},
        {"say": "Your Silver savings account is open and your EcoCard application is submitted."}])
    direct = _run(tmp_path / "d", "task_058", common + [
        {"call": OPEN, "args": T058_OPEN},
        {"say": "Your Silver savings account is open and your EcoCard application is submitted."}],
        tool_adapter="direct_tools")
    assert wrapped["evaluation"]["reward"] == 1.0
    assert direct["evaluation"]["reward"] == 1.0
    events = direct["tool_adapter"]["events"]
    assert {"event": "direct_call_translated", "tools": [OPEN]} in events
    assert OPEN in direct["tool_adapter"]["offered"]
    # the benchmark saw the wrapper call with the same arguments, not a direct call
    calls = _env_calls(direct)
    assert (CALL, {"agent_tool_name": OPEN, "arguments": json.dumps(T058_OPEN)}) in calls
    assert not any(n == OPEN for n, _ in calls)


def test_035_action_graded_task_keeps_its_grade_through_the_adapter(tmp_path):
    """ACTION-graded: extra harness unlocks and the adapter's '{}' argument string must not change the grade."""
    user = [{"say": "My credit score dropped 127 points overnight because of a false 60-day delinquency!"},
            {"say": "Okay, thank you. ###STOP###"}]
    wrapped = _run(tmp_path / "w", "task_035", [KB_035, {"call": UNLOCK, "args": {"agent_tool_name": EMERGENCY}},
                                                {"call": CALL, "args": {"agent_tool_name": EMERGENCY, "arguments": "{}"}},
                                                {"call": "transfer_to_human_agents", "args": {"summary": ""}},
                                                {"say": "You're being transferred to a specialist now."}], user)
    direct = _run(tmp_path / "d", "task_035", [KB_035, {"call": EMERGENCY, "args": {}},
                                               {"call": "transfer_to_human_agents", "args": {"summary": ""}},
                                               {"say": "You're being transferred to a specialist now."}], user,
                  tool_adapter="direct_tools")
    assert wrapped["evaluation"]["reward"] == direct["evaluation"]["reward"]
    assert direct["evaluation"]["reward"] == 1.0


def test_only_names_from_received_kb_results_are_offered_and_customer_tools_never(tmp_path):
    trace = _run(tmp_path, "task_058", [KB_058, {"say": "Let me check."}], tool_adapter="direct_tools")
    offered = set(trace["tool_adapter"]["offered"])
    kb_text = next(m["content"] for m in trace["messages"] if m["role"] == "tool")
    assert offered and all(name in kb_text for name in offered)
    assert not offered & {"get_card_last_4_digits", "submit_cash_back_dispute_0589", "get_referral_link", "deposit_check_3847"}


def test_nothing_is_offered_before_a_search_and_unused_offers_are_never_called(tmp_path):
    trace = _run(tmp_path, "task_058", [{"say": "How can I help?"}], tool_adapter="direct_tools")
    assert trace["tool_adapter"]["offered"] == [] and trace["tool_adapter"]["events"] == []
    trace = _run(tmp_path / "b", "task_058", [KB_058, {"say": "Let me check."}], tool_adapter="direct_tools")
    assert not any(n == CALL for n, _ in _env_calls(trace))  # offered, unlocked, never executed


def test_the_adapter_is_not_combined_with_other_interventions():
    from bench import agent

    with pytest.raises(ValueError, match="tested on its own"):
        agent.factory(tools=[], domain_policy="p", llm="m", llm_args={}, tool_adapter="direct_tools",
                      guard_rules=("verification_time_from_clock",))


def test_names_are_read_only_from_successful_kb_results():
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage

    msgs = [AssistantMessage(role="assistant", content=None, tool_calls=[
                ToolCall(id="k", name="KB_search", arguments={"query": "x"}, requestor="assistant"),
                ToolCall(id="e", name="KB_search", arguments={"query": "y"}, requestor="assistant"),
                ToolCall(id="o", name="get_user_information_by_id", arguments={}, requestor="assistant")]),
            ToolMessage(id="k", role="tool", requestor="assistant", content="use open_bank_account_4821 here"),
            ToolMessage(id="e", role="tool", requestor="assistant", content="Error: freeze_debit_card_3892"),
            ToolMessage(id="o", role="tool", requestor="assistant", content="close_bank_account_7392")]
    names = adapter.names_in_kb_results(msgs, {"open_bank_account_4821", "freeze_debit_card_3892", "close_bank_account_7392"})
    assert names == {"open_bank_account_4821"}


def test_in_continuations_harness_unlock_turns_are_labelled_not_counted_as_model_proposals(tmp_path):
    from bench import REPO_ROOT, continuation
    from bench.budget import Budget, Limits, install
    from bench.scripted import FAKE_PRICES, ScriptedLLM

    case = {c["id"]: c for c in json.loads((REPO_ROOT / "experiments/D002_plan.json").read_text())["cases"]}["X1"]
    acct = "get_all_user_accounts_by_user_id_3847"
    steps = [{"call": "KB_search", "args": {"query": "Gold Account savings base APY rate"}},
             {"call": acct, "args": {"user_id": "wl94k7m3p8"}}, {"say": "Found your accounts."}]
    budget = Budget(1.0, FAKE_PRICES, tmp_path / "l.jsonl")
    with install(budget, Limits(), send=ScriptedLLM({"agent": steps})):
        r = continuation.continue_case(case, "baseline", AGENT_MODEL, {}, max_rounds=12, budget=budget,
                                       tool_adapter="direct_tools")
    by = [p["by"] for p in r["proposals"]]
    assert "adapter" in by and by.count("model") == 3
    assert any(c["underlying"] == acct and c["ok"] and c["name"] == "call_discoverable_agent_tool" for c in r["calls"])


def test_batch_pairs_keep_repeated_attempts_separate():
    from bench.batch import _pairs

    rows = [{"task_id": "t", "arm": a, "attempt": k, "status": "finished", "official_reward": r}
            for k, (x, y) in enumerate([(0.0, 1.0), (1.0, 0.0)]) for a, r in (("baseline", x), ("direct_tools", y))]
    assert [(p["attempt"], p["pair"]) for p in _pairs(rows)] == [(0, "improved"), (1, "regressed")]
