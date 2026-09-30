"""Harness v2: the task ledger (bench/ledger.py) and its checks. Zero cost: synthetic conversations and scripted
runs through the real tau2 path with the official evaluator."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import agent, harness, ledger  # noqa: E402
from tests.test_harness import TIME, TYPES, _Conv, _ctx, _draft, _verified  # noqa: E402

V2 = harness.V2_GATES
FREEZE = ("freeze_debit_card_3892", {"card_id": "dc_1"})
KB_DOC = "1. Freezing a card\n   ID: doc_cards_007\n   Content: use freeze_debit_card_3892"


def _plan(conv, needs):
    """Record a plan through the harness-local tool, the way the agent would."""
    args = {"requests": [{"request": "freeze my card", "needs": needs}]}
    conv.call("task_plan", args, "Plan recorded: 1 request(s)")
    return conv


def _with_card(conv):
    return conv.call("get_debit_cards_by_account_id_7823", {"account_id": "a1"}, "1. Record ID: dc_1\n   card_id: dc_1")


# ---- the ledger -----------------------------------------------------------------------------------------------

def test_the_ledger_is_rebuilt_from_the_conversation():
    conv = _verified(_Conv()).search("freeze card", KB_DOC)
    _with_card(conv).call("freeze_debit_card_3892", {"card_id": "dc_1"}, "Card dc_1 frozen.")
    led = ledger.build(conv.messages, TYPES.get)
    assert led.verified_user == "u1" and led.docs_seen == {"doc_cards_007"}
    assert led.searches == [{"query": "freeze card", "docs": ["doc_cards_007"]}]
    assert [w["tool"] for w in led.writes] == ["freeze_debit_card_3892"] and led.plan is None


def test_a_plan_is_read_back_and_an_invalid_one_is_ignored():
    conv = _plan(_Conv(), [{"need": "freeze procedure", "status": "open"}])
    assert ledger.build(conv.messages, TYPES.get).open_needs() == [("freeze my card", "freeze procedure")]
    conv = _Conv().call("task_plan", {"requests": "nonsense"}, "Plan not recorded: invalid plan")
    assert ledger.build(conv.messages, TYPES.get).plan is None
    assert ledger.parse_plan({"requests": "nonsense"})[1]


# ---- v2 checks ------------------------------------------------------------------------------------------------

def test_an_identical_write_that_already_succeeded_is_held_but_a_different_one_is_not():
    conv = _with_card(_verified(_Conv())).call("freeze_debit_card_3892", {"card_id": "dc_1"}, "Card dc_1 frozen.")
    conv.call("get_debit_cards_by_account_id_7823", {"account_id": "a1"}, "1. Record ID: dc_2\n   card_id: dc_2")
    [f] = harness.review(_draft(calls=[FREEZE]), conv.ev(), _ctx(), V2)
    assert f.gate == "duplicate_write" and "already succeeded" in f.message
    other = ("freeze_debit_card_3892", {"card_id": "dc_2"})
    assert [f.gate for f in harness.review(_draft(calls=[other]), conv.ev(), _ctx(), V2)] == ["plan_before_acting"]


def test_acting_without_a_plan_is_advised_but_reading_or_asking_is_not():
    conv = _with_card(_verified(_Conv()))
    assert [f.gate for f in harness.review(_draft(calls=[FREEZE]), conv.ev(), _ctx(), V2)] == ["plan_before_acting"]
    read = ("get_debit_cards_by_account_id_7823", {"account_id": "a1"})
    assert harness.review(_draft(calls=[read]), conv.ev(), _ctx(), V2) == []
    assert harness.review(_draft("Which card would you like me to freeze?"), conv.ev(), _ctx(), V2) == []


def test_open_needs_and_uncited_sources_are_listed_before_acting():
    conv = _with_card(_verified(_Conv()).search("freeze card", KB_DOC))
    _plan(conv, [{"need": "freeze procedure", "status": "found", "source": "doc_cards_007"},
                 {"need": "replacement fee", "status": "open"},
                 {"need": "fraud rule", "status": "found", "source": "doc_invented_1"}])
    [f] = harness.review(_draft(calls=[FREEZE]), conv.ev(), _ctx(), V2)
    assert f.gate == "needs_covered" and "replacement fee" in f.message and "doc_invented_1" in f.message


def test_a_covered_plan_lets_the_write_through():
    conv = _with_card(_verified(_Conv()).search("freeze card", KB_DOC))
    _plan(conv, [{"need": "freeze procedure", "status": "found", "source": "doc_cards_007"},
                 {"need": "replacement fee", "status": "not_found"}])
    assert harness.review(_draft(calls=[FREEZE]), conv.ev(), _ctx(), V2) == []


def test_a_transfer_is_advised_unless_the_customer_was_asked_first():
    conv = _Conv().search("a").search("b").search("c")
    _plan(conv, [{"need": "x", "status": "not_found"}])
    transfer = ("transfer_to_human_agents", {"summary": "s"})
    assert [f.gate for f in harness.review(_draft(calls=[transfer]), conv.ev(), _ctx(), V2)] == ["transfer_after_asking"]
    conv.messages.append({"role": "assistant", "content": "Would you like me to transfer you to a human agent?"})
    conv.messages.append({"role": "user", "content": "Yes please."})
    assert harness.review(_draft(calls=[transfer]), conv.ev(), _ctx(), V2) == []


def test_a_completion_claim_needs_a_successful_change_or_a_handed_over_tool():
    conv = _verified(_Conv())
    [f] = harness.review(_draft("Done! Your card has been frozen."), conv.ev(), _ctx(), V2)
    assert f.gate == "claims_need_receipts" and f.call_ids == []
    _with_card(conv).call("freeze_debit_card_3892", {"card_id": "dc_1"}, "Card dc_1 frozen.")
    assert harness.review(_draft("Done! Your card has been frozen."), conv.ev(), _ctx(), V2) == []
    handed = _Conv().call("give_discoverable_user_tool", {"discoverable_tool_name": "submit_cash_back_dispute_0589"},
                          "Tool given to user: submit_cash_back_dispute_0589")
    assert harness.review(_draft("Your dispute has been submitted."), handed.ev(), _ctx(), V2) == []


def test_v1_gates_are_unchanged_by_default():
    assert agent.harness_record({})["gates"] == list(harness.GATES)
    assert "version" not in agent.harness_record({})  # H001's recorded spec keeps its shape
    spec = agent.harness_record({"version": "v2"})
    assert spec["gates"] == list(harness.V2_GATES) and spec["name"] == "harness_v2"
    assert agent.harness_record(spec) == spec
    with pytest.raises(ValueError):
        agent.harness_record({"version": "v9"})


# ---- end to end: the plan tool never reaches the environment ---------------------------------------------------

LOG_089 = {"name": "David Martinez", "user_id": "dm42f8c3a7", "address": "4521 Mountain View Drive, Denver, CO 80203",
           "email": "david.martinez.cpa@gmail.com", "phone_number": "303-555-7294", "date_of_birth": "06/18/1983",
           "time_verified": TIME}
PLAN = {"call": "task_plan", "args": {"requests": [{"request": "verify and help with debit card",
                                                    "needs": [{"need": "verification", "status": "not_found"}]}]}}


def _run(tmp_path, agent_steps, spec):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"description": "MOCK harness v2", "agent": agent_steps,
                                  "user": [{"say": "Hi, I need help with my debit card."}, {"say": "OK."},
                                           {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3}))
    trace, _ = run(RunOptions(task_id="task_089", agent_model=AGENT_MODEL, user_model=USER_MODEL, retrieval_config="bm25",
                              scripted=script, out_dir=tmp_path, agent_harness=spec, budget_usd=20.0))
    return trace


def _names(trace):
    return [tc["name"] for m in trace["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]


def test_the_plan_tool_runs_locally_and_never_enters_the_trajectory(tmp_path):
    trace = _run(tmp_path, [{"call": "KB_search", "args": {"query": "debit card"}}, PLAN,
                            {"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
                            {"call": "get_current_time", "args": {}}, {"call": "log_verification", "args": LOG_089},
                            {"say": "You're verified."}, {"say": "Goodbye."}, {"say": "Goodbye."}], {"version": "v2"})
    assert "task_plan" not in _names(trace) and "log_verification" in _names(trace)
    assert [e["event"] for e in trace["harness"]["events"]].count("plan_recorded") == 1
    assert trace["evaluation"] is not None and trace["agent_inputs"]["passed"]


def test_an_invalid_plan_is_reported_to_the_model_and_the_conversation_continues(tmp_path):
    bad = {"call": "task_plan", "args": {"requests": "not a list"}}
    trace = _run(tmp_path, [bad, {"call": "KB_search", "args": {"query": "debit card"}}, {"say": "How can I help?"},
                            {"say": "Goodbye."}, {"say": "Goodbye."}], {"version": "v2"})
    assert "plan_invalid" in [e["event"] for e in trace["harness"]["events"]]
    assert "KB_search" in _names(trace) and trace["evaluation"] is not None


def test_a_plan_call_alongside_a_real_call_runs_both_in_a_valid_order(tmp_path):
    both = {"calls": [PLAN, {"call": "KB_search", "args": {"query": "debit card limit"}}]}
    trace = _run(tmp_path, [both, {"say": "Here is what I found."}, {"say": "Goodbye."}, {"say": "Goodbye."}],
                 {"version": "v2"})
    # the environment saw only the real call (plus the adapter's own unlock turn for tools the search named)
    assert [n for n in _names(trace) if n != "unlock_discoverable_agent_tool"] == ["KB_search"]
    assert trace["execution"]["finished"] and trace["evaluation"] is not None
    assert [e["event"] for e in trace["harness"]["events"]].count("plan_recorded") == 1


# ---- the procedure compiler and its check ----------------------------------------------------------------------

FREEZE_DOC = ("1. Internal: Freezing and Unfreezing a Debit Card\n   ID: doc_cards_026\n   Score: 9.1\n   Content: "
              "Procedure.\n\n## Freezing Requirements\n\n1. Customer must be verified\n2. Card must currently be in ACTIVE "
              "status\n\n## Freezing Steps\n\n1. Ask customer why they want to freeze the card\n2. Use "
              "freeze_debit_card_3892 with the card_id\n\n## Unfreezing Requirements\n\n1. Card must currently be in "
              "FROZEN status\n\n## Unfreezing Steps\n\n1. Use unfreeze_debit_card_3893 with the card_id\n")


def test_the_compiler_builds_one_verbatim_card_per_tool():
    from bench import compiler

    cards = compiler.cards_from_results([FREEZE_DOC], {"freeze_debit_card_3892", "unfreeze_debit_card_3893"})
    freeze, unfreeze = cards["freeze_debit_card_3892"][0], cards["unfreeze_debit_card_3893"][0]
    assert freeze.requirements == ["Customer must be verified", "Card must currently be in ACTIVE status"]
    assert unfreeze.requirements == ["Card must currently be in FROZEN status"]
    assert freeze.customer_points == ["Ask customer why they want to freeze the card"]
    assert all(r in FREEZE_DOC for r in freeze.requirements + freeze.steps)  # nothing paraphrased


def test_the_checklist_is_shown_once_before_first_use_unless_the_plan_cites_it():
    ctx = {**_ctx(), "agent_tools": _ctx()["agent_tools"] | {"unfreeze_debit_card_3893"}}
    conv = _with_card(_verified(_Conv()).search("freeze card", FREEZE_DOC))
    _plan(conv, [{"need": "card status", "status": "not_found"}])
    [f] = harness.review(_draft(calls=[FREEZE]), conv.ev(), dict(ctx), V2)
    assert f.gate == "procedure_checklist" and "ACTIVE status" in f.message and "why they want" in f.message
    assert harness.review(_draft(calls=[FREEZE]), conv.ev(), {**ctx, "checklists_shown": {FREEZE[0]}}, V2) == []
    cited = _with_card(_verified(_Conv()).search("freeze card", FREEZE_DOC))
    _plan(cited, [{"need": "freeze procedure", "status": "found", "source": "doc_cards_026"}])
    assert harness.review(_draft(calls=[FREEZE]), cited.ev(), dict(ctx), V2) == []


# ---- review of 5a06fa5: two execution details confirmed ---------------------------------------------------------

FREEZE_WRAPPED = {"call": "call_discoverable_agent_tool",
                  "args": {"agent_tool_name": "freeze_debit_card_3892", "arguments": json.dumps({"card_id": "dbc_x"})}}


def test_a_real_call_next_to_a_plan_call_still_passes_every_check_before_it_runs(tmp_path):
    # one message: a plan, and a write with no verification logged -> the write is held, then withheld; never executed
    trace = _run(tmp_path, [{"calls": [PLAN, FREEZE_WRAPPED]}, FREEZE_WRAPPED, {"say": "Goodbye."}, {"say": "Goodbye."}],
                 {"version": "v2"})
    executed = [tc for m in trace["messages"] if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])
                if tc["name"] == "call_discoverable_agent_tool"]
    assert executed == []
    events = [(e["event"], e.get("gate") or e.get("gates")) for e in trace["harness"]["events"]]
    assert ("plan_recorded", None) in events
    assert ("held", "verification_before_write") in events and ("withheld", ["verification_before_write"]) in events


def test_a_plan_citing_a_document_changes_no_hard_check():
    """Citing the card's document only suppresses the repeated checklist reminder. Verification, identifiers and
    duplicates are decided exactly as without a plan. (Consent, ownership and eligibility are not enforced by any
    v2 check, so a citation cannot establish them either.)"""
    ctx = {**_ctx(), "agent_tools": _ctx()["agent_tools"] | {"unfreeze_debit_card_3893"}}
    hard = [g for g in V2 if g in harness.HARD]
    cases = [
        ("unverified", _Conv().search("freeze card", FREEZE_DOC), FREEZE),
        ("invented id", _verified(_Conv()).search("freeze card", FREEZE_DOC), ("freeze_debit_card_3892", {"card_id": "dc_zz"})),
        ("duplicate", _with_card(_verified(_Conv()).search("freeze card", FREEZE_DOC))
         .call("freeze_debit_card_3892", {"card_id": "dc_1"}, "Card dc_1 frozen."), FREEZE),
    ]
    for label, conv, call in cases:
        without = [f.gate for f in harness.review(_draft(calls=[call]), conv.ev(), dict(ctx), hard)]
        _plan(conv, [{"need": "freeze procedure", "status": "found", "source": "doc_cards_026"}])
        with_plan = [f.gate for f in harness.review(_draft(calls=[call]), conv.ev(), dict(ctx), hard)]
        assert without == with_plan and without, label
