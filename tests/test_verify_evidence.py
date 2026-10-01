"""v3.2's identity-verification evidence check (bench/verify_evidence.py) and its gate. $0."""

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR
from bench import agent, harness, verify_evidence
from bench.guard import Evidence

KENJI = ("Found 1 record(s) in 'users':\n\n1. Record ID: 6680a37184\n   name: Kenji Tanaka\n   user_id: 6680a37184\n"
         "   address: 1847 Cherry Blossom Lane, Seattle, WA 98101\n   email: kenji.tanaka@outlook.com\n"
         "   phone_number: 206-555-0293\n   date_of_birth: 07/22/1985\n")
OTHER = KENJI.replace("6680a37184", "aa11bb22cc").replace("Kenji Tanaka", "Ann Lee").replace(
    "kenji.tanaka@outlook.com", "ann.lee@mail.com").replace("206-555-0293", "312-555-0101").replace("07/22/1985", "01/02/1990")


def user(text):
    return {"role": "user", "content": text}


def lookup(n, content, name="get_user_information_by_name"):
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": f"l{n}", "name": name, "arguments": {}}]},
            {"role": "tool", "tool_call_id": f"l{n}", "content": content, "error": False}]


def verify(uid="6680a37184", **logged):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "v", "name": "log_verification", "arguments": {"user_id": uid, **logged}}]}


def assess(msgs, uid="6680a37184"):
    return verify_evidence.assess(uid, msgs)


# ---- the rule --------------------------------------------------------------------------------------------------------

def test_two_customer_stated_matching_fields_allow_verification():
    msgs = [user("Hi, I'm Kenji Tanaka."), *lookup(1, KENJI),
            user("My date of birth is July 22, 1985 and my phone is (206) 555-0293.")]
    a = assess(msgs)
    assert a.allowed and a.supported == ["date_of_birth", "phone_number"]


@pytest.mark.parametrize("dob", ["07/22/1985", "7/22/1985", "1985-07-22", "July 22nd, 1985", "22 July 1985", "Jul 22 1985"])
def test_date_forms(dob):
    msgs = [*lookup(1, KENJI), user(f"Born {dob}. Email kenji.tanaka@OUTLOOK.com")]
    assert assess(msgs).supported == ["date_of_birth", "email"]


def test_address_street_line_with_suffix_variants():
    msgs = [*lookup(1, KENJI), user("I live at 1847 Cherry Blossom Ln, Seattle. Phone 206.555.0293")]
    assert assess(msgs).supported == ["phone_number", "address"]


def test_address_after_a_date_in_the_same_message():
    """Regression (replay of H008/H009 task_023): a date before the address must not swallow the house number."""
    msgs = [*lookup(1, KENJI), user("Date of birth: 07/22/1985 - Address: 1847 Cherry Blossom Lane, Seattle, WA 98101")]
    assert assess(msgs).supported == ["date_of_birth", "address"]


@pytest.mark.parametrize("phone", ["206-555-0293", "(206) 555-0293", "+1 206 555 0293", "2065550293", "206.555.0293"])
def test_phone_groupings(phone):
    msgs = [*lookup(1, KENJI), user(f"Phone {phone}, born 07/22/1985")]
    assert assess(msgs).supported == ["date_of_birth", "phone_number"]


def test_a_phone_at_the_end_of_a_line_does_not_run_into_the_next_line():
    """Regression (replay, H008 task_017): '206-555-0293\n\n3) Date range' must read as 10 digits."""
    msgs = [*lookup(1, KENJI), user("- Date of birth: 07/22/1985  \n- Phone number: 206-555-0293  \n\n3) Date range: June")]
    assert assess(msgs).supported == ["date_of_birth", "phone_number"]


def test_non_us_phone_grouping():
    """Regression (blind review of the replay, task_095): a 4-3-3 grouped number."""
    rec = KENJI.replace("206-555-0293", "0412-555-947")
    msgs = [*lookup(1, rec), user("DOB 07/22/1985 and phone 0412-555-947")]
    assert assess(msgs).supported == ["date_of_birth", "phone_number"]


def test_values_the_agent_showed_first_and_the_customer_typed_back_do_not_count():
    """Regression (blind review, task_061): the agent wrote the record's values as an 'example'; an echo is not evidence."""
    msgs = [*lookup(1, KENJI),
            {"role": "assistant", "content": "Please reply like this: DOB 07/22/1985, phone 206-555-0293."},
            user("DOB 07/22/1985, phone 206-555-0293")]
    assert not assess(msgs).allowed
    honest = [*lookup(1, KENJI), user("DOB 07/22/1985, phone 206-555-0293"),
              {"role": "assistant", "content": "Thanks, I have DOB 07/22/1985 and phone 206-555-0293."}]
    assert assess(honest).allowed            # the agent repeating values AFTER the customer said them is fine


def test_customer_repeating_values_the_agent_read_back_is_not_a_correction():
    """Regression (replay, H008 task_019): customer states, agent reads back, customer repeats -> still supported."""
    msgs = [*lookup(1, KENJI), user("Date of birth: 07/22/1985, phone number: 206-555-0293"),
            {"role": "assistant", "content": "I'll use DOB 07/22/1985 and phone 206-555-0293. OK?"},
            user("Yes, use my date of birth 07/22/1985 and phone number 206-555-0293.")]
    assert assess(msgs).allowed


def test_one_field_is_not_enough_and_repeating_it_does_not_count_twice():
    msgs = [*lookup(1, KENJI), user("My phone is 206-555-0293."), user("Again, 2065550293.")]
    a = assess(msgs)
    assert not a.allowed and a.supported == ["phone_number"]


def test_name_and_user_id_never_count():
    msgs = [*lookup(1, KENJI), user("I'm Kenji Tanaka, user id 6680a37184. Email kenji.tanaka@outlook.com")]
    assert not assess(msgs).allowed


# ---- false evidence ----------------------------------------------------------------------------------------------------

def test_another_customers_record_does_not_count():
    msgs = [*lookup(1, OTHER), user("DOB 01/02/1990, phone 312-555-0101")]
    assert not assess(msgs).record_found and not assess(msgs).allowed          # verifying Kenji: no Kenji record
    assert assess(msgs, uid="aa11bb22cc").allowed                             # verifying Ann: fine


def test_record_must_come_from_a_customer_lookup_not_any_tool_or_document():
    fake = [{"role": "assistant", "content": None, "tool_calls": [{"id": "k", "name": "KB_search", "arguments": {}}]},
            {"role": "tool", "tool_call_id": "k", "content": KENJI, "error": False}]
    msgs = [*fake, user("DOB 07/22/1985, phone 206-555-0293")]
    assert not assess(msgs).record_found


def test_values_the_agent_wrote_or_logged_do_not_count():
    msgs = [*lookup(1, KENJI), user("Phone is 206-555-0293."),
            {"role": "assistant", "content": "Is your date of birth 07/22/1985 and email kenji.tanaka@outlook.com?"},
            user("Yes, that's right.")]
    a = assess(msgs)
    assert not a.allowed and a.supported == ["phone_number"]
    ev = Evidence(messages=msgs, tool_type=lambda n: None)
    draft = verify(date_of_birth="07/22/1985", email="kenji.tanaka@outlook.com", phone_number="206-555-0293")
    [f] = harness.gate_verification_evidence(draft, ev, {})          # the call's own arguments are not evidence
    assert f.gate == "verification_evidence"


def test_a_correction_cancels_an_earlier_match_but_a_passing_date_does_not():
    base = [*lookup(1, KENJI), user("DOB 07/22/1985, email kenji.tanaka@outlook.com")]
    corrected = base + [user("Sorry, my email is actually kenji.t@gmail.com")]
    assert assess(corrected).supported == ["date_of_birth"] and assess(corrected).contradicted == ["email"]
    passing = base + [user("The charge was on 11/02/2025 for $500, at 12 Main St.")]
    assert assess(passing).allowed


def test_evidence_after_the_call_is_never_seen():
    """The gate sees the conversation up to the proposal; nothing later exists for it."""
    before = [*lookup(1, KENJI), user("Phone 206-555-0293")]
    ev = Evidence(messages=before, tool_type=lambda n: None)
    assert harness.gate_verification_evidence(verify(), ev, {})
    assert assess(before + [user("DOB 07/22/1985")]).allowed   # only a statement made before the call could help


def test_failed_lookup_is_not_a_record():
    msgs = [*lookup(1, KENJI), user("DOB 07/22/1985, phone 206-555-0293")]
    msgs[1]["error"] = True
    assert not assess(msgs).record_found


# ---- feedback and wiring -------------------------------------------------------------------------------------------------

def test_feedback_names_field_kinds_never_stored_values():
    msgs = [*lookup(1, KENJI), user("Phone 206-555-0293")]
    text = verify_evidence.feedback(assess(msgs))
    assert "Not executed" in text and "phone number" in text and "date of birth" in text
    for stored in ("07/22/1985", "kenji.tanaka@outlook.com", "Cherry Blossom", "206-555-0293", "Kenji"):
        assert stored not in text
    assert "2065550293" not in text
    assert "Kenji" not in harness.WITHHELD["verification_evidence"]


def test_only_log_verification_is_checked_and_writes_are_untouched():
    ev = Evidence(messages=[user("hello")], tool_type=lambda n: None)
    other = {"role": "assistant", "tool_calls": [{"id": "x", "name": "get_current_time", "arguments": {}}]}
    assert harness.gate_verification_evidence(other, ev, {}) == []
    text_reply = {"role": "assistant", "content": "How can I help?"}
    assert harness.gate_verification_evidence(text_reply, ev, {}) == []


def test_v3_2_is_v3_1_plus_the_check_and_older_versions_are_unchanged():
    v31, v32 = agent.harness_record({"version": "v3.1"}), agent.harness_record({"version": "v3.2"})
    assert v32["gates"] == v31["gates"] + ["verification_evidence"]
    assert v32["capability_search"] and v32["transfer_hold_once"] and v32["name"] == "harness_v3.2"
    for v in ("v1", "v2", "v3", "v3.1"):
        assert "verification_evidence" not in agent.harness_record({"version": v})["gates"]
    assert "verification_evidence" in harness.HARD


# ---- end to end (scripted model, real tau2 path) ---------------------------------------------------------------------

def test_end_to_end_v3_2_holds_an_unsupported_verification_then_allows_it_once_the_customer_gives_two_fields(tmp_path):
    from tests.test_harness import LOG_089, _run

    agent_steps = [{"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
                   {"call": "get_current_time", "args": {}},
                   {"call": "log_verification", "args": LOG_089},           # held: the customer has stated nothing
                   {"say": "Could you confirm your date of birth and the phone number on your account?"},
                   {"call": "log_verification", "args": LOG_089},           # allowed: two matching fields stated
                   {"say": "Thank you, you're verified. How can I help with your card?"},
                   {"say": "Goodbye."}, {"say": "Goodbye."}]
    user_steps = [{"say": "Hi, I'm David Martinez, user id dm42f8c3a7. My debit card was declined."},
                  {"say": "Sure: born June 18, 1983, and my phone is 303-555-7294."},
                  {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3
    t = _run(tmp_path, agent_steps, {"version": "v3.2"}, user_steps)
    held = [e for e in t["harness"]["events"] if e["event"] == "held"]
    assert [e["gate"] for e in held] == ["verification_evidence"]
    assert held[0]["detail"]["supported"] == [] and held[0]["detail"]["record_found"]
    verifications = [m for m in t["messages"] if m["role"] == "assistant"
                     for c in m.get("tool_calls") or [] if c["name"] == "log_verification"]
    assert len(verifications) == 1                                       # the held call never reached the trajectory
    results = [m.get("content") or "" for m in t["messages"] if m["role"] == "tool"]
    assert any(r.startswith("Verification logged successfully") for r in results)
    said = " ".join(m.get("content") or "" for m in t["messages"] if m["role"] == "assistant")
    assert "date of birth" in said and "06/18/1983" not in said
    assert t["execution"]["finished"]


def test_end_to_end_v3_1_does_not_run_the_check(tmp_path):
    from tests.test_harness import LOG_089, _run

    agent_steps = [{"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
                   {"call": "get_current_time", "args": {}},
                   {"call": "log_verification", "args": LOG_089},
                   {"say": "You're verified."}, {"say": "Goodbye."}, {"say": "Goodbye."}]
    t = _run(tmp_path, agent_steps, {"version": "v3.1"})
    assert not [e for e in t["harness"]["events"] if e["event"] == "held"]


# ---- retries, the fallback reply, failure handling (second review) ---------------------------------------------------

def test_withheld_reply_asks_only_for_what_is_missing_and_reveals_nothing():
    F = harness.Finding
    one = harness.withheld_reply(F("verification_evidence", "m", ["v"], {"record_found": True, "supported": ["phone_number"]}))
    assert "one more" in one and "phone number" not in one and all(x in one for x in ("date of birth", "email", "address"))
    none = harness.withheld_reply(F("verification_evidence", "m", ["v"], {"record_found": True, "supported": []}))
    assert "two of these" in none
    nobody = harness.withheld_reply(F("verification_evidence", "m", ["v"], {"record_found": False, "supported": []}))
    assert "full name or the email" in nobody
    for text in (one, none, nobody):
        assert harness.is_withheld_reply(text) and not any(ch.isdigit() for ch in text)
    assert harness.withheld_reply(F("ids_observed", "m", ["x"], {})) == harness.WITHHELD["ids_observed"]


def test_a_checker_defect_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("parser bug")
    monkeypatch.setattr(verify_evidence, "assess", boom)
    msgs = [*lookup(1, KENJI), user("DOB 07/22/1985, phone 206-555-0293")]
    ctx = {"events": []}
    [f] = harness.gate_verification_evidence(verify(), Evidence(messages=msgs, tool_type=lambda n: None), ctx)
    assert f.gate == "verification_evidence" and ctx["events"][0]["event"] == "checker_error"


def test_end_to_end_retries_never_execute_an_unsupported_verification(tmp_path):
    """The correction budget limits model retries; it never lets the next invalid call execute. After the budget the
    customer gets the fixed reply asking for what is missing; verification executes only once evidence exists."""
    from tests.test_harness import LOG_089, _run

    agent_steps = [{"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
                   {"call": "get_current_time", "args": {}},
                   {"call": "log_verification", "args": LOG_089},     # held (1 field so far)
                   {"call": "log_verification", "args": LOG_089},     # retry: budget spent -> withheld, fixed reply sent
                   {"call": "log_verification", "args": LOG_089},     # next turn: held again
                   {"call": "log_verification", "args": LOG_089},     # retry -> withheld again
                   {"call": "log_verification", "args": LOG_089},     # customer has now given 2 fields -> executes
                   {"say": "Thanks, you're verified."}, {"say": "Goodbye."}, {"say": "Goodbye."}]
    user_steps = [{"say": "Hi, I'm David Martinez (dm42f8c3a7). My phone is 303-555-7294. My card was declined."},
                  {"say": "I already told you my phone."},
                  {"say": "Fine: my date of birth is 06/18/1983."},
                  {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3
    t = _run(tmp_path, agent_steps, {"version": "v3.2"}, user_steps)
    ev = t["harness"]["events"]
    assert [e["event"] for e in ev if e["event"] in ("held", "withheld")] == ["held", "withheld", "held", "withheld"]
    executed = [i for i, m in enumerate(t["messages"]) if m["role"] == "assistant"
                for c in m.get("tool_calls") or [] if c["name"] == "log_verification"]
    assert len(executed) == 1
    said_before = [m["content"] for m in t["messages"][:executed[0]] if m["role"] == "user"]
    assert any("06/18/1983" in s for s in said_before)                    # the second field came first
    fixed = [m["content"] for m in t["messages"] if m["role"] == "assistant" and harness.is_withheld_reply(m.get("content"))]
    assert len(fixed) == 2 and all("one more" in x and "phone number" not in x for x in fixed)


def _db_users():
    import json
    import os
    from pathlib import Path

    path = Path(os.environ["TAU2_DATA_DIR"]) / "tau2" / "domains" / "banking_knowledge" / "db.json"
    return list(json.loads(path.read_text())["users"]["data"].values())


def test_fallback_and_feedback_never_contain_any_stored_value_of_any_customer():
    """The fallback reply and the model-facing feedback are fixed templates filled with field NAMES only. Checked
    against every customer in the bank's database (names, emails and addresses contain letters, so 'no digits' is not
    enough)."""
    import itertools

    users = _db_users()
    assert len(users) >= 30
    F = harness.Finding
    for u in users:
        stored = [u[k] for k in ("name", "email", "phone_number", "date_of_birth", "address") if u.get(k)]
        stored += [u["address"].split(",")[0]] if u.get("address") else []
        for found in (True, False):
            for n in range(3):
                for sup in itertools.combinations(verify_evidence.FIELDS, n):
                    reply = harness.withheld_reply(F("verification_evidence", "m", ["v"],
                                                     {"record_found": found, "supported": list(sup)}))
                    a = verify_evidence.Assessment(user_id=u["user_id"], record_found=found, supported=list(sup))
                    text = verify_evidence.feedback(a)
                    for v in stored:
                        assert v.lower() not in reply.lower(), (u["user_id"], v)
                        assert v.lower() not in text.lower(), (u["user_id"], v)
