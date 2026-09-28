"""Argument-evidence check (bench/evidence.py): positive and negative controls built from the saved D001
continuations. Zero cost: no model calls; the checker is not wired into any run."""

import copy
import inspect
import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR
from bench import REPO_ROOT, evidence
from bench.guard import Evidence

PLAN = json.loads((REPO_ROOT / "experiments/D001_plan.json").read_text())
RESULTS = json.loads((REPO_ROOT / "experiments/D001_results.json").read_text())
CASES = {c["id"]: c for c in PLAN["cases"]}
RUNS = {r["run"]: r for r in RESULTS["results"]}


def _before(run: int, proposal: int) -> list[dict]:
    r = RUNS[run]
    case = CASES[r["case"]]
    trace = json.loads((REPO_ROOT / case["source_trace"]).read_text())["messages"]
    return evidence.messages_before(trace, case["prefix_end"], r["calls"], proposal)


def _credit(amount, account="sav_lm83h7k2p5_gold"):
    return {"name": "call_discoverable_agent_tool", "arguments": {
        "agent_tool_name": "apply_savings_account_credit_6831",
        "arguments": json.dumps({"account_id": account, "amount": amount, "credit_type": "interest_correction"})}}


def _amount(a):
    return next(f for f in a.findings if f["kind"] == "amount")


# D001 run 01 (P1, interface package), just before its $100 credit (proposal 7)
P1 = _before(1, 7)


def test_control_substring_collision_100_in_2100_is_not_evidence():
    context = " ".join(m.get("content") or "" for m in P1)
    assert "100.0" in context and "2100.00" in context  # what the frozen substring flag accepted
    a = evidence.check_arguments(_credit(100.0), None, Evidence(messages=P1))
    assert not a.allowed
    assert _amount(a)["basis"] is None
    assert next(f for f in a.findings if f["kind"] == "id")["basis"] == "record"  # the account itself is grounded


def test_control_the_recorded_credit_proposals_are_blocked_as_executed():
    assert RUNS[1]["proposals"][7]["text"] is None and RUNS[3]["proposals"][6]["text"] is None
    for run, n in [(1, 7), (3, 6)]:
        tc = RUNS[run]["proposals"][n]["tool_calls"][0]
        assert not evidence.check_arguments(tc, None, Evidence(messages=_before(run, n))).allowed


def test_control_legitimate_calculated_amount_passes_with_policy_flag():
    draft = "Calculation: 96,000 × (5.5% + 0.75% + 0.6%) ÷ 12 − 450 = 98.00"
    a = evidence.check_arguments(_credit(98.0), draft, Evidence(messages=P1))
    assert a.allowed, a.findings
    assert _amount(a)["basis"] == "derivation"
    assert a.flags == ["policy_applicability_not_checked"]


def test_control_unresolved_policy_conflict_is_not_decided_by_the_checker():
    """$100 includes the Gold card's 0.025%, which doc _045 treats as a non-stacking card bonus and
    doc gold_account_013 as a stacking relationship bonus. A correct derivation from received numbers passes,
    flagged; which amount policy intends is not the checker's call, and it holds no reference answer."""
    draft = "Calculation: 96000 × (5.5% + 0.025% + 0.75% + 0.6%) ÷ 12 − 450 = 100.00"
    a = evidence.check_arguments(_credit(100.0), draft, Evidence(messages=P1))
    assert a.allowed and a.flags == ["policy_applicability_not_checked"]
    assert "98" not in inspect.getsource(evidence)


def test_control_wrong_arithmetic_and_unreceived_operands_are_blocked():
    wrong = evidence.check_arguments(_credit(100.0), "Calculation: 96000 × (5.5% + 0.75% + 0.6%) ÷ 12 − 450 = 100",
                                     Evidence(messages=P1))
    assert not wrong.allowed and "evaluates to 98.00" in _amount(wrong)["problem"]
    invented = evidence.check_arguments(_credit(126.0), "Calculation: 96000 × 7.2% ÷ 12 − 450 = 126",
                                        Evidence(messages=P1))
    assert not invented.allowed and "7.2" in _amount(invented)["problem"]


def test_control_another_customers_valid_id_is_not_evidence():
    other = copy.deepcopy(P1) + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x1", "name": "get_user_information_by_name",
                                                               "arguments": {"name": "Taylor Morrison"}}]},
        {"role": "tool", "tool_call_id": "x1", "error": False, "content":
            "Found 1 record(s) in 'accounts':\n\n1. Record ID: chk_tm92c4d7e8_blue\n   account_id: chk_tm92c4d7e8_blue\n"
            "   user_id: tm92c4d7e8\n   current_holdings: 100.00\n"}]
    a = evidence.check_arguments(_credit(100.0, "chk_tm92c4d7e8_blue"), None, Evidence(messages=other))
    ident = next(f for f in a.findings if f["kind"] == "id")
    assert not a.allowed and "another customer (tm92c4d7e8)" in ident["problem"]
    assert _amount(a)["basis"] is None  # the matching 100.00 is in a record the verified customer does not own


def test_control_guessed_and_error_echoed_ids_are_not_evidence():
    """D001 run 05 (P2): the agent guessed account IDs. A guess is not evidence even when it happens to exist,
    and an ID echoed back in an error message must not become evidence for the next attempt."""
    lookup = lambda acct: {"name": "call_discoverable_agent_tool", "arguments": {  # noqa: E731
        "agent_tool_name": "get_debit_cards_by_account_id_7823", "arguments": json.dumps({"account_id": acct})}}
    first = evidence.check_arguments(lookup("chk_tm92c4d7e8_blue"), None, Evidence(messages=_before(5, 1)))
    assert not first.allowed and first.findings[0]["problem"] == "identifier not in any successful record"
    after_error = _before(5, 3)
    assert any("chk_tm92c4d7e8_green_fee_free' not found" in (m.get("content") or "") for m in after_error)
    echoed = evidence.check_arguments(lookup("chk_tm92c4d7e8_green_fee_free"), None, Evidence(messages=after_error))
    assert not echoed.allowed and echoed.findings[0]["problem"] == "identifier appears only in an error result"


def test_points_with_units_are_amounts():
    tc = RUNS[10]["proposals"][1]["tool_calls"][0]
    a = evidence.check_arguments(tc, None, Evidence(messages=_before(10, 1)))
    assert _amount(a)["value"] == 1000.0 and not a.allowed


@pytest.mark.parametrize("expr,value", [("96,000 × 6.875% ÷ 12 − 450", 100.0), ("(2 + 3) x 4", 20.0),
                                         ("$1,200.50 - 200.5", 1000.0)])
def test_evaluate(expr, value):
    assert abs(evidence.evaluate(expr)[0] - value) < 1e-6
