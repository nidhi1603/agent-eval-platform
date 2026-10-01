"""Progress metrics for a conversation, with reads and writes kept apart.

This module exists because of a bug. research/h002/analyze.py counted every `call_discoverable_agent_tool`
reference action as a "reference write", so lookups made through that wrapper (read tools such as
get_all_user_accounts_by_user_id_3847) were counted as writes. The error ran through H002–H004
(research/h004/relabel_progress.py). Here every reference action and every agent call is classified by the
UNDERLYING tool's read/write type, seen through the discoverable wrappers.

Matching rules are H002's, unchanged. A reference action counts as matched when a successful call exists with the
same requestor and underlying tool, and all compared arguments are equal after str().strip().lower(). The compared
arguments are the action's compare_args minus wrapper keys, or all inner arguments for discoverable calls whose
compare_args are only wrapper keys. Order is ignored. A match is a diagnostic: it is not evidence of consent, order
or policy compliance.
"""

import json
import re

WRAPPER_KEYS = {"agent_tool_name", "arguments", "discoverable_tool_name"}
CALL_AGENT, CALL_USER = "call_discoverable_agent_tool", "call_discoverable_user_tool"
UNLOCK, GIVE = "unlock_discoverable_agent_tool", "give_discoverable_user_tool"


def _inner(args):
    a = (args or {}).get("arguments")
    if isinstance(a, str):
        try:
            return json.loads(a)
        except ValueError:
            return {}
    return dict(a or {})


def key(requestor, name, args):
    """(requestor, underlying tool, comparable args), through the wrappers."""
    args = args or {}
    if name == CALL_AGENT:
        return requestor, args.get("agent_tool_name"), _inner(args)
    if name == CALL_USER:
        return requestor, args.get("discoverable_tool_name"), _inner(args)
    if name == UNLOCK:
        return requestor, "UNLOCK:" + str(args.get("agent_tool_name")), {}
    if name == GIVE:
        return requestor, "GIVE:" + str(args.get("discoverable_tool_name")), {}
    return requestor, name, dict(args)


def matched(ref, calls) -> bool:
    r_req, r_name, r_args = key(ref.requestor, ref.name, ref.arguments)
    cmp = ref.compare_args
    for req, name, args in calls:
        if (req, name) != (r_req, r_name):
            continue
        keys = [k for k in (cmp if cmp is not None else r_args.keys()) if k not in WRAPPER_KEYS]
        if ref.name in (CALL_AGENT, CALL_USER) and (cmp is None or set(cmp) <= WRAPPER_KEYS):
            keys = list(r_args.keys())
        if all(str(args.get(k)).strip().lower() == str(r_args.get(k)).strip().lower() for k in keys):
            return True
    return False


def underlying(name: str, args: dict | None) -> str | None:
    return key("x", name, args)[1]


def kind(name: str, args: dict | None, tool_type) -> str:
    """'write' | 'read' | 'other' by the UNDERLYING tool's type (the wrappers themselves are not typed as the tool).
    Unlocks and hand-overs are 'other': they change nothing in the database."""
    if name in (UNLOCK, GIVE):
        return "other"
    t = tool_type(underlying(name, args))
    return t if t in ("read", "write") else "other"


# Execution outcome of an ACTION (a write, a customer-tool handover, a transfer). tau2 reports most failures as text,
# not as errors, and its failure texts do not all begin with "Error" ("Failed to log verification: Record may already
# exist."). Failure is checked first: the error flag, or text beginning "Error"/"Failed". Success then needs the tool's
# OWN receipt (RECEIPTS: the opening of each action tool's success text, from tau2's banking tool source and every
# action result in all 240 local traces, research/execution_outcomes/README.md). A tool not in RECEIPTS falls back to
# a generic receipt word ("successful(ly)", "confirmed") unless negated ("not successful", "unsuccessful").
# Anything else is "unknown" and is never counted as a success.
FAILURE = re.compile(r"^(error|failed|failure)\b", re.I)
RECEIPTS = {name: re.compile(p) for name, p in {
    "activate_debit_card_8291": r"^New Debit Card Activation Successful",
    "activate_debit_card_8292": r"^Replacement Debit Card Activation Successful",
    "apply_credit_card_account_flag_6147": r"^Account flag applied successfully",
    "apply_savings_account_credit_6831": r"^Credit applied successfully",
    "apply_statement_credit_8472": r"^Statement credit applied successfully",
    "change_user_email": r"^Email updated successfully",
    "clear_debit_card_fraud_alert_4892": r"^(?:Fraud Alert|Velocity Block) Cleared Successfully",
    "close_bank_account_7392": r"^Bank account closed successfully",
    "close_credit_card_account_7834": r"^Credit card account closed successfully",
    "close_debit_card_4721": r"^Debit Card Closed Successfully",
    "file_credit_card_transaction_dispute_4829": r"^Credit card transaction dispute filed successfully",
    "file_debit_card_transaction_dispute_6281": r"^Dispute ID: \S+",
    "freeze_debit_card_3892": r"^Debit Card Frozen Successfully",
    "give_discoverable_user_tool": r"^Tool given to user: \S+",
    "log_credit_card_closure_reason_4521": r"^Closure reason logged successfully",
    "log_verification": r"^Verification logged successfully",
    "open_bank_account_4821": r"^Bank account opened successfully",
    "order_debit_card_5739": r"^Debit Card Order Confirmed",
    "order_replacement_credit_card_7291": r"^Order ID: \S+",
    "request_temporary_debit_card_limit_increase_8374": r"^Temporary Daily ATM Withdrawal Limit Increase Granted Successfully",
    "submit_credit_limit_increase_request_7392": r"^Credit limit increase request submitted successfully",
    "submit_interest_discrepancy_report_7294": r"^Interest Discrepancy Report Submitted Successfully",
    "transfer_to_human_agents": r"^Transfer successful \(reason: ",
    "unfreeze_debit_card_3893": r"^Debit Card Unfrozen Successfully",
    "update_transaction_rewards_3847": r"^Transaction rewards updated successfully",
}.items()}
GENERIC_RECEIPT = re.compile(r"\bsuccessful(?:ly)?\b|\bconfirmed\b", re.I)
NEGATED = re.compile(r"\b(?:not|never|no longer|un)[\s-]*(?:been\s+)?(?:successful(?:ly)?|confirmed)\b|\bunsuccessful", re.I)
TRANSFER = "transfer_to_human_agents"


def outcome(result: dict | None, tool: str | None = None) -> str:
    """'success' | 'failure' | 'unknown' for an action's tool result. `tool` is the underlying tool name (or
    give_discoverable_user_tool / transfer_to_human_agents); without it, or for a tool not in RECEIPTS, the generic
    receipt rule applies."""
    if not result:
        return "unknown"
    text = (result.get("content") or "").lstrip()
    if result.get("error") or FAILURE.match(text):
        return "failure"
    if tool in RECEIPTS:
        return "success" if RECEIPTS[tool].match(text) else "unknown"
    return "success" if GENERIC_RECEIPT.search(text) and not NEGATED.search(text) else "unknown"


def action_tool(name: str, args: dict | None) -> str | None:
    """The name RECEIPTS is keyed by: the underlying tool, or the handover / transfer tool itself."""
    return name if name in (GIVE, TRANSFER) else underlying(name, args)


def is_action(name: str, args: dict | None, tool_type) -> bool:
    """Writes (by the underlying tool's type), customer-tool handovers and transfers."""
    return name in (GIVE, TRANSFER) or kind(name, args, tool_type) == "write"


def call_ok(name: str, args: dict | None, result: dict | None, tool_type) -> bool:
    """Whether a call executed. Actions need a success receipt (outcome() == 'success'); reads and other calls have no
    receipt format, so for them any result that is not an error or an "Error"/"Failed" text counts."""
    if is_action(name, args, tool_type):
        return outcome(result, action_tool(name, args)) == "success"
    r = result or {}
    return bool(result) and not r.get("error") and not FAILURE.match((r.get("content") or "").lstrip())


def progress(messages: list[dict], refs: list, tool_type) -> dict:
    """Per conversation (trajectory dicts: role, tool_calls [{id, name, arguments}], tool results with
    tool_call_id / content / error). `tool_type` maps an underlying tool name to 'read' | 'write' | other."""
    results = {m.get("tool_call_id"): m for m in messages if m.get("role") == "tool"}
    ok_calls, agent = [], {"read_calls": 0, "attempted_writes": 0, "successful_writes": 0, "failed_writes": 0,
                           "unknown_outcome_writes": 0}
    for m in messages:
        for c in m.get("tool_calls") or []:
            res = results.get(c["id"])
            ok = call_ok(c["name"], c["arguments"], res, tool_type)
            if ok:
                ok_calls.append(key(m["role"] if m["role"] == "user" else "assistant", c["name"], c["arguments"]))
            if m["role"] == "assistant":
                k = kind(c["name"], c["arguments"], tool_type)
                if k == "read":
                    agent["read_calls"] += 1
                elif k == "write":
                    o = outcome(res, action_tool(c["name"], c["arguments"]))
                    agent["attempted_writes"] += 1
                    agent["successful_writes"] += o == "success"
                    agent["failed_writes"] += o == "failure"
                    agent["unknown_outcome_writes"] += o == "unknown"
    out = dict(agent)
    for bucket in BUCKETS:
        out[f"ref_{bucket}"], out[f"ref_{bucket}_matched"] = 0, 0
    for a in refs:
        b = bucket_of(a, tool_type)
        out[f"ref_{b}"] += 1
        out[f"ref_{b}_matched"] += matched(a, ok_calls)
    return out


# Reference actions by who acts, through which channel, and the underlying tool's type:
#   discoverable_writes  the agent's writes through call_discoverable_agent_tool (what H002-H004 meant by "writes")
#   discoverable_reads   the agent's lookups through the same wrapper (miscounted as writes in H002-H004)
#   base_writes          e.g. log_verification;  base_reads: e.g. get_user_information_by_email
#   customer             actions the customer performs with its own tools;  other: unlocks and hand-overs
BUCKETS = ("discoverable_writes", "discoverable_reads", "base_writes", "base_reads", "customer", "other")


def bucket_of(ref, tool_type) -> str:
    if ref.requestor == "user":
        return "customer"
    k = kind(ref.name, ref.arguments, tool_type)
    if k == "other":
        return "other"
    return ("discoverable_" if ref.name == CALL_AGENT else "base_") + k + "s"
