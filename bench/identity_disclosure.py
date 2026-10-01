"""Identity-value disclosure check (flag `disclosure_check`; after D005).

**Why.** D005: after v3.2 held an unsupported verification, gpt-5-mini asked for the missing fields but in 3 of 30
replies gave "examples" built from the customer's REAL stored values, although the feedback forbade it. The bank's
rule (tau2 prompts/components/additional_instructions.md, "Authenticating Users"): "Do not leak any information about
the user before they are verified."

**What it checks.** Every customer-facing text the agent proposes (also text that accompanies tool calls), BEFORE it
is delivered, throughout the conversation. A text is prohibited if it contains a stored identity value (date of birth,
email, phone number, street address) from a customer record retrieved in this conversation, when
- that customer is not yet verified (no successful log_verification receipt for that user_id), and
- the value was not supplied INDEPENDENTLY by the customer (verify_evidence.provenance: the customer wrote it before
  any agent message showed it). A value the agent showed first stays prohibited even after the customer echoes it.
Read-backs of values the customer gave independently are allowed. After a valid verification the restriction for that
customer is released.

**Coverage, stated narrowly.** It enforces ONE part of the disclosure rule: the four stored identity fields, in the
formats verify_evidence recognises (dates in common written forms, phones by digits, emails, street lines). It does
not cover other account information (balances, card digits, transactions), partial values (the last 4 digits of a
phone), or reformatted values it does not recognise.

**Handling** (bench/harness.py): a VERIFICATION-RELATED text-only draft is replaced at once, without regeneration,
by the fixed request for the missing fields (`withheld_reply`, which contains field names only). Any other caught
draft gets one regeneration with feedback; if it still leaks, a fixed apology that does not ask for identity fields.
The rejected draft and the customer-visible replacement are logged separately.
"""

from __future__ import annotations

import re

from bench import verify_evidence as ve

RECEIPT = re.compile(r"Verification logged successfully\.\s*\n\s*- User: .*\(ID: ([^)\s]+)\)")
VERIFICATION_TALK = re.compile(r"\bverif|\bidentity\b|\bconfirm\b|\bmatch(?:es|ing)?\b", re.I)
FIELD_WORD = re.compile(r"\b(?:date of birth|birth ?date|DOB|e-?mail|phone|address)\b", re.I)


def verified_user_ids(messages: list[dict]) -> set[str]:
    """user_ids with a successful log_verification receipt in `messages`."""
    calls = {c["id"]: c["name"] for m in messages if m.get("role") == "assistant" for c in m.get("tool_calls") or []}
    out = set()
    for m in messages:
        if m.get("role") == "tool" and not m.get("error") and calls.get(m.get("tool_call_id")) == "log_verification":
            out |= set(RECEIPT.findall(m.get("content") or ""))
    return out


def prohibited(text: str | None, messages: list[dict]) -> list[dict]:
    """Stored identity values in `text` that may not be shown yet (see the module docstring). Fields only, no values."""
    if not text:
        return []
    verified = verified_user_ids(messages)
    out = []
    for uid, rec in ve.records(messages).items():
        if uid in verified:
            continue
        for f in ve.FIELDS:
            want = ve.record_value(f, rec.get(f, ""))
            if want is None or not any(ve.matches(f, v, want) for v in ve.stated(f, text)):
                continue
            origin = ve.provenance(f, want, messages)
            if origin != "customer":
                out.append({"user_id": uid, "field": f, "origin": origin or "new"})
    return out


def verification_related(text: str | None) -> bool:
    return bool(text) and bool(FIELD_WORD.search(text)) and bool(VERIFICATION_TALK.search(text))


def feedback(found: list[dict]) -> str:
    kinds = sorted({ve.LABEL[x["field"]] for x in found})
    return ("Not sent: your message contained the customer's stored " + ", ".join(kinds) + " from their record, which "
            "the customer has not given you themselves. They are not verified yet: do not reveal anything from their "
            "record, not even as an example. Ask for identity fields by name only, and let the customer supply the values.")
