"""Three-way action outcome (bench.metrics.outcome), after the H009 review: a "Failed ..." text is not a success,
and an unrecognised result is unknown, never a success. $0."""

import pytest

from bench import metrics


def _r(text, error=False):
    return {"role": "tool", "content": text, "error": error}


@pytest.mark.parametrize("text", [
    "Verification logged successfully.\n  - User: K",
    "Temporary Daily ATM Withdrawal Limit Increase Granted Successfully\nCard",
    "Bank account opened successfully!\n  - Account ID: x",
    "Transfer successful (reason: technical_system_error). A human agent will",
    "Tool given to user: get_referral_link\nDescription: Generate",
    "Debit Card Order Confirmed\nOrder ID: dcord_f70a304ee8c8",
    "Order ID: ccord_929ac3028316\nCard Account: cc_x_silver",
    "Dispute ID: dsp_8aa70a7acbbf\nTransaction: btxn_70fb52ef4e29",
])
def test_success_receipts(text):
    assert metrics.outcome(_r(text)) == "success"


@pytest.mark.parametrize("text", [
    "Failed to log verification: Record may already exist.",
    "Error: Requested limit $500 is not higher than the current limit of $500",
    "  error: something",
])
def test_failure_texts(text):
    assert metrics.outcome(_r(text)) == "failure"


def test_error_flag_missing_result_and_unrecognised_text():
    assert metrics.outcome(_r("Verification logged successfully.", error=True)) == "failure"
    assert metrics.outcome(None) == "unknown"
    assert metrics.outcome(_r("Done.")) == "unknown"          # no receipt: never counted as executed
    assert metrics.outcome(_r("The request is pending.")) == "unknown"


def _types(name):
    return {"log_verification": "write", "get_user_information_by_id": "read"}.get(name)


def test_progress_counts_attempted_successful_failed_and_unknown_writes_apart():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "a", "name": "log_verification", "arguments": {}}]},
        _r("Failed to log verification: Record may already exist.") | {"tool_call_id": "a"},
        {"role": "assistant", "tool_calls": [{"id": "b", "name": "log_verification", "arguments": {}}]},
        _r("Verification logged successfully.") | {"tool_call_id": "b"},
        {"role": "assistant", "tool_calls": [{"id": "c", "name": "log_verification", "arguments": {}}]},
        _r("OK") | {"tool_call_id": "c"},
        {"role": "assistant", "tool_calls": [{"id": "d", "name": "get_user_information_by_id", "arguments": {}}]},
        _r("name: K") | {"tool_call_id": "d"},
    ]
    p = metrics.progress(msgs, [], _types)
    assert (p["attempted_writes"], p["successful_writes"], p["failed_writes"], p["unknown_outcome_writes"]) == (3, 1, 1, 1)
    assert p["read_calls"] == 1


def test_reads_keep_the_permissive_rule_but_not_failed_texts():
    assert metrics.call_ok("get_user_information_by_id", {}, _r("name: K"), _types)
    assert not metrics.call_ok("get_user_information_by_id", {}, _r("Failed to find user"), _types)
    assert not metrics.call_ok("log_verification", {}, _r("OK"), _types)   # an action needs a receipt
