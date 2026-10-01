"""Three-way action outcome (bench.metrics.outcome), after the H009 review: a "Failed ..." text is not a success,
and an unrecognised result is unknown, never a success. $0."""

import pytest

from bench import metrics


def _r(text, error=False):
    return {"role": "tool", "content": text, "error": error}


@pytest.mark.parametrize("tool,text", [
    ("log_verification", "Verification logged successfully.\n  - User: K"),
    ("request_temporary_debit_card_limit_increase_8374", "Temporary Daily ATM Withdrawal Limit Increase Granted Successfully\nCard"),
    ("open_bank_account_4821", "Bank account opened successfully!\n  - Account ID: x"),
    ("transfer_to_human_agents", "Transfer successful (reason: kb_search_unsuccessful_customer_requests_transfer). A human"),
    ("give_discoverable_user_tool", "Tool given to user: get_referral_link\nDescription: Generate"),
    ("order_debit_card_5739", "Debit Card Order Confirmed\nOrder ID: dcord_f70a304ee8c8"),
    ("order_replacement_credit_card_7291", "Order ID: ccord_929ac3028316\nCard Account: cc_x_silver"),
    ("file_debit_card_transaction_dispute_6281", "Dispute ID: dsp_8aa70a7acbbf\nTransaction: btxn_70fb52ef4e29"),
])
def test_tool_specific_receipts(tool, text):
    assert metrics.outcome(_r(text), tool) == "success"


def test_every_receipt_tool_has_a_pattern_anchored_at_the_start():
    assert all(p.pattern.startswith("^") for p in metrics.RECEIPTS.values())


def test_a_receipt_of_another_tool_or_negated_wording_is_not_a_success():
    assert metrics.outcome(_r("Statement credit applied successfully."), "log_verification") == "unknown"
    assert metrics.outcome(_r("The verification was not successful."), "log_verification") == "unknown"
    # fallback for a tool with no known receipt: receipt words count, negated ones do not
    assert metrics.outcome(_r("Widget reset successfully."), "reset_widget_0001") == "success"
    for text in ("The reset was not successful.", "Reset unsuccessful.", "Order not confirmed.", "Never confirmed."):
        assert metrics.outcome(_r(text), "reset_widget_0001") == "unknown", text


@pytest.mark.parametrize("text", [
    "Failed to log verification: Record may already exist.",
    "Error: Requested limit $500 is not higher than the current limit of $500",
    "  error: something",
])
def test_failure_texts_take_precedence(text):
    assert metrics.outcome(_r(text), "log_verification") == "failure"
    assert metrics.outcome(_r(text + " Verification logged successfully."), "log_verification") == "failure"


def test_error_flag_missing_result_and_unrecognised_text():
    assert metrics.outcome(_r("Verification logged successfully.", error=True), "log_verification") == "failure"
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
