"""Harness v1 (bench/harness.py). Zero cost: synthetic evidence, saved traces, and scripted runs through the real tau2
path with the official evaluator."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, agent, harness  # noqa: E402
from bench.guard import Evidence, GuardConfigError  # noqa: E402

TYPES = {"KB_search": "read", "get_current_time": "read", "get_user_information_by_id": "read",
         "log_verification": "write", "transfer_to_human_agents": "generic",
         "get_all_user_accounts_by_user_id_3847": "read", "freeze_debit_card_3892": "write",
         "apply_savings_account_credit_6831": "write"}
AGENT_TOOLS = {"get_all_user_accounts_by_user_id_3847", "freeze_debit_card_3892", "apply_savings_account_credit_6831"}
USER_TOOLS = {"get_card_last_4_digits"}
TIME = "2025-11-14 03:40:00 EST"


def _ctx():
    return {"agent_tools": AGENT_TOOLS, "user_tools": USER_TOOLS, "tool_type": TYPES.get, "events": [],
            "offered_reads": ["get_all_user_accounts_by_user_id_3847"]}


class _Conv:
    def __init__(self):
        self.messages, self.n = [], 0

    def call(self, name, args, result, error=False):
        self.n += 1
        cid = f"c{self.n}"
        self.messages.append({"role": "assistant", "content": None,
                              "tool_calls": [{"id": cid, "name": name, "arguments": args}]})
        self.messages.append({"role": "tool", "tool_call_id": cid, "content": result, "error": error})
        return self

    def search(self, q, result="1. doc_x\nNothing relevant."):
        return self.call("KB_search", {"query": q}, result)

    def ev(self):
        return Evidence(messages=list(self.messages), tool_type=TYPES.get)


def _draft(text=None, calls=()):
    return {"role": "assistant", "content": text,
            "tool_calls": [{"id": f"p{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(calls)]}


TRANSFER = ("transfer_to_human_agents", {"summary": "customer needs help"})


# ---- search_before_giving_up (soft) ---------------------------------------------------------------------------

def test_transfer_after_one_search_is_held_with_the_queries_it_ran():
    ev = _Conv().search("freeze my card").ev()
    [f] = harness.review(_draft(calls=[TRANSFER]), ev, _ctx())
    assert f.gate == "search_before_giving_up" and f.detail["searches"] == 1 and f.detail["trigger"] == "transfer"
    assert '"freeze my card"' in f.message and "does not authorize" in f.message


def test_a_capability_denial_is_held_but_an_ordinary_reply_is_not():
    ev = _Conv().search("a").ev()
    assert harness.review(_draft("I don't have access to account-level tools here."), ev, _ctx())
    assert harness.review(_draft("Your card is now frozen."), ev, _ctx()) == []


def test_enough_searches_and_no_unused_tools_pass():
    ev = _Conv().search("a").search("b").search("c").ev()
    assert harness.review(_draft(calls=[TRANSFER]), ev, _ctx()) == []


def test_unused_named_reads_and_customer_tools_are_listed_but_never_writes():
    kb = ("1. doc_cards\nUse get_all_user_accounts_by_user_id_3847 to look up accounts, then freeze_debit_card_3892. "
          "The customer can run get_card_last_4_digits.")
    ev = _Conv().search("a", kb).search("b").search("c").ev()
    [f] = harness.review(_draft("I can't freeze cards from here."), ev, _ctx())
    assert f.detail["unused_reads"] == ["get_all_user_accounts_by_user_id_3847"]
    assert f.detail["unused_customer_tools"] == ["get_card_last_4_digits"]
    assert "freeze_debit_card_3892" not in f.message  # a write is never suggested


def test_an_agent_following_a_discovered_procedure_is_not_held_for_other_named_tools():
    kb = "1. doc_x\nget_all_user_accounts_by_user_id_3847 lists accounts."
    ev = (_Conv().search("a", kb).search("b").search("c")
          .call("call_discoverable_agent_tool", {"agent_tool_name": "freeze_debit_card_3892", "arguments": "{}"},
                "Card frozen.").ev())
    assert harness.review(_draft(calls=[TRANSFER]), ev, _ctx()) == []


def test_names_in_error_results_do_not_count():
    ev = _Conv().search("a", "Error: get_all_user_accounts_by_user_id_3847 unavailable").search("b").search("c").ev()
    assert harness.review(_draft(calls=[TRANSFER]), ev, _ctx()) == []


# ---- hard gates ------------------------------------------------------------------------------------------------

def _verified(conv):
    return (conv.call("get_user_information_by_id", {"user_id": "u1"}, "1. Record ID: u1\n   user_id: u1\n   name: A")
            .call("get_current_time", {}, f"The current time is {TIME}.")
            .call("log_verification", {"user_id": "u1", "time_verified": TIME}, "Verification logged successfully"))


def test_an_invented_verification_time_is_held_with_the_clock_reading_to_use():
    ev = _Conv().call("get_user_information_by_id", {"user_id": "u1"}, "1. Record ID: u1\n   user_id: u1") \
        .call("get_current_time", {}, f"The current time is {TIME}.").ev()
    [f] = harness.review(_draft(calls=[("log_verification", {"user_id": "u1", "time_verified": "2026-09-27 17:06:00 UTC"})]),
                         ev, _ctx())
    assert f.gate == "clock_before_verification" and TIME in f.message


def test_without_a_clock_reading_the_fix_is_to_read_the_clock():
    ev = _Conv().call("get_user_information_by_id", {"user_id": "u1"}, "1. Record ID: u1\n   user_id: u1").ev()
    [f] = harness.review(_draft(calls=[("log_verification", {"user_id": "u1", "time_verified": TIME})]), ev, _ctx())
    assert f.gate == "clock_before_verification" and "Call get_current_time" in f.message


def test_verification_of_a_user_id_never_retrieved_is_held():
    ev = _Conv().call("get_current_time", {}, f"The current time is {TIME}.").ev()
    [f] = harness.review(_draft(calls=[("log_verification", {"user_id": "invented", "time_verified": TIME})]), ev, _ctx())
    assert f.gate == "ids_observed" and "invented" in f.message


def test_a_write_before_verification_is_held_and_names_the_steps():
    ev = _Conv().search("a").ev()
    [f] = harness.review(_draft(calls=[("freeze_debit_card_3892", {"card_id": "dc_1"})]), ev, _ctx())
    assert f.gate == "verification_before_write"
    assert "get_current_time" in f.message and "log_verification" in f.message


def test_a_write_with_an_identifier_not_in_any_record_is_held():
    ev = _verified(_Conv()).ev()
    [f] = harness.review(_draft(calls=[("freeze_debit_card_3892", {"card_id": "dc_made_up"})]), ev, _ctx())
    assert f.gate == "ids_observed" and "dc_made_up" in f.message
    assert "get_all_user_accounts_by_user_id_3847" in f.message  # where to look it up


def test_identifiers_the_customer_stated_or_a_receipt_created_count_as_observed():
    conv = _verified(_Conv()).call("call_discoverable_agent_tool", {"agent_tool_name": "open_bank_account_4821",
                                                                     "arguments": "{}"}, "Account opened: chk_new_1")
    conv.messages.append({"role": "user", "content": "The last 4 digits are 5320."})
    call = ("freeze_debit_card_3892", {"account_id": "chk_new_1", "last_4_digits": "5320"})
    assert harness.review(_draft(calls=[call]), conv.ev(), _ctx()) == []


def test_an_identifier_seen_only_in_an_error_or_as_a_substring_is_not_observed():
    conv = _verified(_Conv()).call("get_all_user_accounts_by_user_id_3847", {"user_id": "u1"},
                                   "Error: account chk_9 not found")
    conv.call("KB_search", {"query": "x"}, "1. doc\naccount chk_99 example")
    [f] = harness.review(_draft(calls=[("freeze_debit_card_3892", {"account_id": "chk_9"})]), conv.ev(), _ctx())
    assert f.detail["unobserved"] == [["account_id", "chk_9"]] or f.detail["unobserved"] == [("account_id", "chk_9")]


def test_a_write_with_an_owned_identifier_passes_and_amounts_are_only_logged():
    conv = _verified(_Conv()).call("get_all_user_accounts_by_user_id_3847", {"user_id": "u1"},
                                   "1. Record ID: sav_1\n   account_id: sav_1\n   user_id: u1\n   current_holdings: 100")
    ctx = _ctx()
    call = ("apply_savings_account_credit_6831", {"account_id": "sav_1", "amount": 55.0})
    assert harness.review(_draft(calls=[call]), conv.ev(), ctx) == []
    [e] = ctx["events"]
    assert e["event"] == "evidence_assessed" and e["enforced"] is False


def test_reads_are_never_held_by_the_hard_gates():
    ev = _Conv().ev()
    assert harness.review(_draft(calls=[("get_all_user_accounts_by_user_id_3847", {"user_id": "zzz"})]), ev, _ctx()) == []


def test_a_hard_finding_suppresses_the_soft_advisory_in_the_same_draft():
    ev = _Conv().ev()
    found = harness.review(_draft(calls=[("freeze_debit_card_3892", {"card_id": "x"}), TRANSFER]), ev, _ctx())
    assert [f.gate for f in found] == ["verification_before_write"]


def test_missing_tool_metadata_fails_loudly():
    with pytest.raises(GuardConfigError):
        harness.review(_draft(calls=[TRANSFER]), Evidence(messages=[]), _ctx())


def test_feedback_modes_and_block_mode_drops_the_soft_gate():
    f = harness.Finding("verification_before_write", "specific remediation")
    assert harness.feedback_text(f, "structured") == "specific remediation"
    assert harness.feedback_text(f, "generic") == harness.GENERIC_FEEDBACK
    assert harness.feedback_text(f, "block") == harness.BLOCK_FEEDBACK
    assert "search_before_giving_up" not in harness.active_gates(harness.GATES, "block")
    assert harness.active_gates(harness.GATES, "generic") == harness.GATES


# ---- configuration ---------------------------------------------------------------------------------------------

def test_harness_spec_defaults_and_validation():
    spec = agent.harness_record({})
    assert spec == {"name": "harness_v1", "gates": list(harness.GATES), "feedback": "structured", "adapter": True}
    assert agent.harness_record(spec) == spec  # a recorded spec round-trips
    with pytest.raises(ValueError):
        agent.harness_record({"gates": ["nope"]})
    with pytest.raises(ValueError):
        agent.harness_record({"feedback": "loud"})
    with pytest.raises(ValueError):
        agent.harness_record({"extra": 1})


def test_harness_cannot_be_combined_with_other_interventions():
    with pytest.raises(ValueError):
        agent.factory([], "policy", harness={}, tool_adapter="direct_tools", llm="x")
    with pytest.raises(ValueError):
        agent.factory([], "policy", harness={}, guard_rules=("write_requires_verification_log",), llm="x")


# ---- positive controls on saved failures -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry():
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.build import build_text_orchestrator
    from tau2.runner.helpers import get_tasks

    from bench.guard import toolkit_type_lookup

    task = get_tasks("banking_knowledge", task_ids=["task_035"])[0]
    cfg = TextRunConfig(domain="banking_knowledge", agent=agent.register("baseline"), llm_agent="gpt-5-mini",
                        llm_user="gpt-5.2", retrieval_config="bm25")
    env = build_text_orchestrator(cfg, task, seed=300).environment
    return (set(env.tools.get_discoverable_tools()), set(env.user_tools.get_discoverable_tools()),
            toolkit_type_lookup(env.tools))


@pytest.mark.parametrize("run,gate,index", [
    ("S002/task_089", "clock_before_verification", 8),     # R001: invented time at [8]
    ("S003/task_087_baseline", "clock_before_verification", 10),
    ("S002/task_035", "search_before_giving_up", 8),        # R001: plain transfer at [8]
    ("S002/task_080", "search_before_giving_up", 22),       # R001: "can't freeze" at [22]
    ("S003/task_095_baseline", "search_before_giving_up", 26),  # R001: denies the tool at [26]
])
def test_checks_fire_at_the_r001_failure_points(registry, run, gate, index):
    trace = json.loads((REPO_ROOT / "results" / run / "trace.json").read_text())
    fires = harness.replay_saved(trace["messages"], *registry)
    assert any(f["gate"] == gate and f["i"] == index for f in fires)


# ---- end to end (scripted model, real tau2 path, official evaluator) -------------------------------------------

LOG_089 = {"name": "David Martinez", "user_id": "dm42f8c3a7", "address": "4521 Mountain View Drive, Denver, CO 80203",
           "email": "david.martinez.cpa@gmail.com", "phone_number": "303-555-7294", "date_of_birth": "06/18/1983",
           "time_verified": TIME}
KB3 = [{"call": "KB_search", "args": {"query": q}} for q in ("identity verification", "debit card limit", "transfer")]


def _run(tmp_path, agent_steps, harness_spec=None, user_steps=None):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"description": "MOCK harness v1", "agent": agent_steps,
                                  "user": user_steps or [{"say": "Hi, I need help with my debit card."},
                                                         {"say": "OK."}, {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3}))
    trace, _ = run(RunOptions(task_id="task_089", agent_model=AGENT_MODEL, user_model=USER_MODEL, retrieval_config="bm25",
                              scripted=script, out_dir=tmp_path, agent_harness=harness_spec))
    return trace


def _calls(trace):
    return [(tc["name"], tc["arguments"]) for m in trace["messages"] if m["role"] == "assistant"
            for tc in (m.get("tool_calls") or [])]


def test_an_invented_time_is_corrected_and_never_reaches_the_trajectory(tmp_path):
    bad = dict(LOG_089, time_verified="2026-09-27 17:06:00 UTC")
    trace = _run(tmp_path, KB3 + [
        {"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
        {"call": "log_verification", "args": bad},              # held: invented time
        {"call": "get_current_time", "args": {}},               # the regenerated proposal follows the remediation
        {"call": "log_verification", "args": LOG_089},
        {"say": "You're verified."}, {"say": "Goodbye."}, {"say": "Goodbye."}], harness_spec={})
    logs = [a for n, a in _calls(trace) if n == "log_verification"]
    assert logs == [LOG_089]
    held = [e for e in trace["harness"]["events"] if e["event"] == "held"]
    assert [e["gate"] for e in held] == ["clock_before_verification"]
    assert trace["harness"]["regenerations"] == 1
    assert trace["evaluation"] is not None and trace["agent_inputs"]["passed"]


def test_a_write_before_verification_is_withheld_after_one_correction(tmp_path):
    write = {"call": "call_discoverable_agent_tool", "args": {"agent_tool_name": "freeze_debit_card_3892",
                                                              "arguments": json.dumps({"card_id": "dc_x"})}}
    trace = _run(tmp_path, KB3 + [write, write, {"say": "Goodbye."}, {"say": "Goodbye."}], harness_spec={})
    assert not any(a.get("agent_tool_name") == "freeze_debit_card_3892" for n, a in _calls(trace)
                   if n == "call_discoverable_agent_tool")
    events = [e["event"] for e in trace["harness"]["events"] if e["event"] in ("held", "withheld")]
    assert events == ["held", "withheld"]
    assert harness.WITHHELD["verification_before_write"] in json.dumps(trace["messages"])


def test_a_repeated_give_up_is_released_after_one_advisory(tmp_path):
    transfer = {"call": "transfer_to_human_agents", "args": {"summary": "needs help"}}
    trace = _run(tmp_path, [{"call": "KB_search", "args": {"query": "debit card"}}, transfer, transfer,
                            {"say": "Goodbye."}], harness_spec={})
    assert [n for n, _ in _calls(trace)].count("transfer_to_human_agents") == 1
    held = [e for e in trace["harness"]["events"] if e["event"] == "held"]
    assert [e["gate"] for e in held] == ["search_before_giving_up"]
    # the held draft and the advisory are private: the trajectory has one transfer and no harness note
    assert "Harness check" not in json.dumps(trace["messages"])
