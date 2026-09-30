"""Harness v3 = v1's checks + capability search (bench/capability.py). $0: unit tests and scripted runs through
the real tau2 path with the official evaluator."""

import json
import shutil

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import agent, capability, harness  # noqa: E402
from tests.test_harness import LOG_089, _Conv, _ctx, _draft  # noqa: E402

LOOKUP = "get_all_user_accounts_by_user_id_3847"


def _msgs(*pairs):
    out = []
    for n, (name, out_text) in enumerate(pairs):
        out.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{n}", "name": name, "arguments": {}}]})
        out.append({"role": "tool", "tool_call_id": f"c{n}", "content": out_text, "error": False})
    return out


VERIFIED = ("log_verification", "Verification logged successfully.\n  - User: D (ID: u1)")


# ---- the triggers ---------------------------------------------------------------------------------------------------

def test_after_verification_searches_for_the_account_lookup_once():
    s = capability.after_verification(_msgs(VERIFIED), set())
    assert s.kind == "accounts" and s.query == capability.QUERIES["accounts"] and s.trigger == "after_verification"
    assert capability.after_verification(_msgs(VERIFIED), {"accounts"}) is None          # once per conversation
    assert capability.after_verification(_msgs(("get_current_time", "now")), set()) is None  # not before verification
    failed = [dict(m, error=True) if m["role"] == "tool" else m for m in _msgs(VERIFIED)]
    assert capability.after_verification(failed, set()) is None


def test_no_search_when_the_agent_already_has_an_account_id():
    msgs = _msgs(VERIFIED, ("get_credit_card_accounts_by_user", "1. Record ID: cc1\n   account_id: cc1"))
    assert capability.after_verification(msgs, set()) is None
    assert capability.before_asking({"content": "What is your account number?"}, msgs, set()) is None


def test_parameter_names_in_documents_and_unlock_receipts_are_not_known_identifiers():
    docs = _msgs(VERIFIED, ("KB_search", "1. Doc\n   ID: doc_x\n   Content: use the tool with card_id: string"),
                 ("unlock_discoverable_agent_tool", "Tool unlocked: t\nParameters:\n  - account_id: string (required)"))
    assert capability.known_ids(docs) == set()
    assert capability.before_asking({"content": "What is the card number?"}, docs, set()).kind == "cards"


@pytest.mark.parametrize("text,kind", [
    ("Could you give me the account number or the checking account ID?", "accounts"),
    ("Which card is this? I need the last 4 digits.", "cards"),
    ("Please share the transaction ID.", "transactions")])
def test_asking_the_customer_for_an_identifier_triggers_the_matching_search(text, kind):
    s = capability.before_asking({"content": text}, _msgs(VERIFIED), set())
    assert s.kind == kind and s.trigger == "before_asking" and "was not sent" in s.note
    assert capability.before_asking({"content": text}, _msgs(VERIFIED), {kind}) is None   # once per kind


def test_ordinary_replies_and_tool_calls_never_trigger():
    msgs = _msgs(VERIFIED)
    assert capability.before_asking({"content": "Your card is frozen. Anything else?"}, msgs, set()) is None
    assert capability.before_asking({"content": "What is your date of birth and email?"}, msgs, set()) is None
    call = {"content": "account number?", "tool_calls": [{"id": "x", "name": "KB_search", "arguments": {}}]}
    assert capability.before_asking(call, msgs, set()) is None


def test_searches_use_the_benchmarks_own_tools():
    s = capability.after_verification(_msgs(VERIFIED), set())
    both = capability.search_calls(s, {"KB_search_bm25", "KB_search_dense", "shell"}, 1)
    assert [(c["name"], c["arguments"]) for c in both] == [
        ("KB_search_bm25", {"query": s.query, "k": capability.K}), ("KB_search_dense", {"query": s.query, "k": capability.K})]
    [one] = capability.search_calls(s, {"KB_search"}, 1)
    assert one["name"] == "KB_search" and one["arguments"] == {"query": s.query}
    assert capability.search_calls(s, {"shell"}, 1) == []


def test_queries_are_fixed_templates_with_no_task_or_document_names():
    src = (bench.REPO_ROOT / "bench" / "capability.py").read_text().split('"""', 2)[2]
    assert "doc_" not in src and "task_" not in src and "_3847" not in src and "required_documents" not in src


# ---- the spec --------------------------------------------------------------------------------------------------------

def test_v3_is_v1s_checks_plus_capability_search():
    v1, v3 = agent.harness_record({}), agent.harness_record({"version": "v3"})
    assert v3["gates"] == v1["gates"] and v3["capability_search"] is True and v3["name"] == "harness_v3"
    assert "capability_search" not in v1 and "capability_search" not in agent.harness_record({"version": "v2"})
    with pytest.raises(ValueError, match="needs the adapter"):
        agent.harness_record({"version": "v3", "adapter": False})
    assert agent.register(harness={"version": "v3"}).endswith("_harness_v3")


def test_the_give_up_advisory_adds_capability_wording_only_in_v3():
    conv = _Conv().search("debit card", "1. Doc\n   ID: doc_x\n   Content: text")
    transfer = _draft(calls=[("transfer_to_human_agents", {"summary": "s"})])
    [f1] = harness.review(transfer, conv.ev(), _ctx())
    [f3] = harness.review(transfer, conv.ev(), {**_ctx(), "capability_advice": True})
    assert capability.ADVICE not in f1.message and capability.ADVICE in f3.message


# ---- end to end -------------------------------------------------------------------------------------------------------

STEPS = [{"call": "get_user_information_by_id", "args": {"user_id": "dm42f8c3a7"}},
         {"call": "get_current_time", "args": {}},
         {"call": "log_verification", "args": LOG_089},
         {"say": "Which card is it? Please give me the card number."},   # v3: held, a search runs instead
         {"say": "Let me look that up."}, {"say": "Goodbye."}, {"say": "Goodbye."}]


def _run(tmp_path, spec, retrieval="bm25"):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "s.json"
    script.write_text(json.dumps({"agent": STEPS, "user": [{"say": "Hi, my debit card was declined."}, {"say": "OK."},
                                                            {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3}))
    trace, _ = run(RunOptions(task_id="task_089", agent_model=AGENT_MODEL, user_model=USER_MODEL,
                              retrieval_config=retrieval, scripted=script, out_dir=tmp_path, agent_harness=spec,
                              budget_usd=20.0))
    return trace


def _searches(trace):
    return [(c["name"], c["arguments"].get("query")) for c in trace["tool_calls"] if c["name"].startswith("KB_search")]


def test_end_to_end_v3_searches_after_verification_and_before_asking_for_an_identifier(tmp_path):
    t = _run(tmp_path, {"version": "v3"})
    assert _searches(t) == [("KB_search", capability.QUERIES["accounts"]), ("KB_search", capability.QUERIES["cards"])]
    events = [e for e in t["harness"]["events"] if e["event"] == "capability_search"]
    assert [(e["trigger"], e["kind"]) for e in events] == [("after_verification", "accounts"), ("before_asking", "cards")]
    assert "card number" in events[1]["draft_not_sent"]
    # the question was never sent to the customer; the account lookup became callable; the model was told why
    said = " ".join(m.get("content") or "" for m in t["messages"] if m["role"] == "assistant")
    assert "Please give me the card number" not in said and "Let me look that up." in said
    assert LOOKUP in t["harness"]["offered"]
    view = json.dumps(t["harness"]["model_view"])
    assert "the customer is verified" in view and "was not sent" in view
    assert t["execution"]["finished"] and t["evaluation"] is not None and t["agent_inputs"]["passed"]
    assert t["answer_independence"]["conclusive"]


def test_end_to_end_v1_runs_no_capability_search_and_sends_the_question(tmp_path):
    t = _run(tmp_path, {})
    assert _searches(t) == [] and not any(e["event"].startswith("capability") for e in t["harness"]["events"])
    assert "Please give me the card number" in " ".join(m.get("content") or "" for m in t["messages"])


@pytest.mark.skipif(not (shutil.which("srt") and shutil.which("rg")), reason="needs sandbox-runtime and ripgrep")
def test_end_to_end_under_alltools_both_search_tools_run(tmp_path):
    t = _run(tmp_path, {"version": "v3"}, retrieval="alltools")
    q = capability.QUERIES["accounts"]
    assert _searches(t)[:2] == [("KB_search_bm25", q), ("KB_search_dense", q)]
    assert all(c["arguments"].get("k") == capability.K for c in t["tool_calls"] if c["name"].startswith("KB_search"))
    assert t["execution"]["finished"] and t["evaluation"] is not None
