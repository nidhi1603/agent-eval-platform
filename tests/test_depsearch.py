"""Dependency-following tool search (bench/depsearch.py), the harness option {"dep_search": true}. Zero cost: the real
knowledge-base documents, and scripted runs through the real tau2 path with the official evaluator."""

import json
import sys
from pathlib import Path

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import adapter, agent, compiler, depsearch, harness, ledger  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_TOOL = "get_debit_cards_by_account_id_7823"   # an agent tool whose input is account_id
KB_NAMING_IT = f"1. Debit cards\n   ID: doc_x_1\n   Content: look up cards with {ACCOUNT_TOOL}.\n"


@pytest.fixture(scope="module")
def registry():
    sys.path.insert(0, str(ROOT / "research" / "h002"))
    from tool_retrieval_probe import registry as probe_registry

    names, tool_type, params = probe_registry()
    index, docs = depsearch.tool_index(frozenset(names), str(depsearch.documents_dir()))
    return {"names": names, "params": params, "index": index, "docs": docs}


def _search(registry, max_queries=depsearch.MAX_QUERIES):
    return depsearch.DependencySearch(registry["index"], registry["docs"], registry["params"], max_queries)


# ---- the mechanism is the one the offline probe measured ---------------------------------------------------------

def test_the_index_and_rankings_are_the_offline_probes(registry):
    from tool_retrieval_probe import BM25 as ProbeBM25

    assert len(registry["docs"]) == 45
    probe = ProbeBM25({i: d["title"] + "\n" + d["content"] for i, d in registry["docs"].items()})
    params = sorted({p for v in registry["params"].values() for p in v if p.endswith("_id") and p != "user_id"})
    assert len(params) >= 5
    for p in params:
        assert registry["index"].top(depsearch.query_for(p)) == probe.top(depsearch.query_for(p)), p


def test_no_document_or_task_is_special_cased():
    src = (ROOT / "bench" / "depsearch.py").read_text()
    code = src.split('"""', 2)[2]  # the module body, without the docstring that names the known limit
    assert "_009" not in code and "task_" not in code and "required_documents" not in code


# ---- a missing identifier triggers the intended search ------------------------------------------------------------

def test_a_missing_identifier_triggers_one_search_whose_documents_are_appended(registry):
    events = []
    extra = _search(registry).augment(KB_NAMING_IT, known_ids=set(), docs_seen=set(), events=events)
    [e] = [x for x in events if x["event"] == depsearch.EVENT and x["param"] == "account_id"]
    assert e["tools"] == [ACCOUNT_TOOL] and e["query"] == depsearch.query_for("account_id")
    assert e["docs_added"] and set(e["docs_added"]) <= set(e["ranked"]) and len(e["ranked"]) <= depsearch.K
    assert "added by the harness, not by KB_search" in extra
    for d in e["docs_added"]:
        assert f"ID: {d}" in extra


def test_an_identifier_already_held_or_user_id_triggers_nothing(registry):
    events = []
    extra = _search(registry).augment(KB_NAMING_IT, known_ids={"account_id"}, docs_seen=set(), events=events)
    assert extra == "" and events == []
    assert ("x", "user_id") not in depsearch.missing_id_params("x", {"x": ["user_id"]}, set())


def test_documents_the_agent_has_already_seen_are_not_added_again(registry):
    ranked = registry["index"].top(depsearch.query_for("account_id"))
    events = []
    extra = _search(registry).augment(KB_NAMING_IT, known_ids=set(), docs_seen=set(ranked), events=events)
    e = next(x for x in events if x["param"] == "account_id")
    assert e["docs_added"] == [] and all(f"ID: {d}" not in extra for d in ranked)


# ---- repeated searches stop within a fixed budget -------------------------------------------------------------------

def test_each_identifier_is_searched_once_per_conversation(registry):
    s, events = _search(registry), []
    s.augment(KB_NAMING_IT, set(), set(), events)
    n = len(events)
    assert s.augment(KB_NAMING_IT, set(), set(), events) == "" and len(events) == n


def test_the_query_budget_caps_a_conversation(registry):
    two_params = KB_NAMING_IT + "and dispute with file_credit_card_transaction_dispute_4829 or similar\n"
    params = {ACCOUNT_TOOL: ["account_id"], "tool_b_0001": ["transaction_id"]}
    s = depsearch.DependencySearch(registry["index"], registry["docs"], params, max_queries=1)
    events = []
    s.augment(KB_NAMING_IT + " tool_b_0001 ", set(), set(), events)
    kinds = [e["event"] for e in events]
    assert kinds == [depsearch.EVENT, depsearch.EVENT + "_budget_exhausted"] and s.queries == 1
    assert s.augment(two_params + " tool_b_0001 ", set(), set(), events) == ""   # nothing more once spent
    assert s.queries == 1


# ---- returned documents become available to the agent ----------------------------------------------------------------

def test_appended_documents_read_as_search_results_to_the_ledger_compiler_and_adapter(registry):
    events = []
    text = KB_NAMING_IT + _search(registry).augment(KB_NAMING_IT, set(), set(), events)
    added = next(e["docs_added"] for e in events if e["param"] == "account_id")
    assert set(added) <= set(ledger.DOC_ID.findall(text))
    assert set(added) <= {d for d, _, _ in compiler.split_results(text)}
    named = adapter.WORD.findall("\n".join(registry["docs"][d]["content"] for d in added))
    assert named, "the added documents name tools, which the adapter can then offer"
    assert set(named) & set(adapter.WORD.findall(text)) == set(named)


def test_the_spec_records_the_option_only_when_on_and_needs_the_adapter():
    assert "dep_search" not in agent.harness_record({})
    assert agent.harness_record({"dep_search": True})["dep_search"] is True
    with pytest.raises(ValueError, match="needs the adapter"):
        agent.harness_record({"dep_search": True, "adapter": False})
    assert agent.register(harness={"dep_search": True}).endswith("_harness_v1_dep-search")


# ---- end to end: the model sees the documents, the trajectory does not, every check still applies ----------------------

TIME = "2025-11-14 03:40:00 EST"


def _run(tmp_path, agent_steps, spec, monkeypatch):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL, ScriptedLLM

    seen = []
    original = ScriptedLLM.__call__

    def recording(self, model, messages, tools=None, **kw):
        from bench.budget import current_role

        if current_role.get() == "agent":
            seen.append(json.dumps(messages, default=str))
        return original(self, model, messages, tools=tools, **kw)

    monkeypatch.setattr(ScriptedLLM, "__call__", recording)
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"description": "MOCK dependency search", "agent": agent_steps,
                                  "user": [{"say": "Hi, I need help with my debit card."}, {"say": "OK."},
                                           {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3}))
    trace, _ = run(RunOptions(task_id="task_089", agent_model=AGENT_MODEL, user_model=USER_MODEL,
                              retrieval_config="bm25", scripted=script, out_dir=tmp_path, agent_harness=spec,
                              budget_usd=20.0))
    return trace, seen


SEARCH = {"call": "KB_search", "args": {"query": "debit card freeze lost card"}}
WRITE = {"call": "call_discoverable_agent_tool", "args": {"agent_tool_name": "freeze_debit_card_3892",
                                                          "arguments": json.dumps({"card_id": "dc_x"})}}


def test_end_to_end_the_model_sees_the_added_documents_but_the_trajectory_does_not(tmp_path, monkeypatch):
    trace, seen = _run(tmp_path, [SEARCH, {"say": "Let me check."}, {"say": "Goodbye."}, {"say": "Goodbye."}],
                       {"dep_search": True}, monkeypatch)
    dep = [e for e in trace["harness"]["events"] if e["event"] == depsearch.EVENT]
    assert dep, "the search result names a tool whose identifier the agent does not hold"
    added = [d for e in dep for d in e["docs_added"]]
    assert added
    assert any("added by the harness" in s and all(d in s for d in added) for s in seen[1:])
    kb = [m for m in trace["messages"] if m["role"] == "tool" and "ID: doc_" in (m.get("content") or "")]
    assert kb and not any("added by the harness" in (m["content"] or "") for m in trace["messages"])
    # tools named only in the added documents are offered too: the documents became usable, not just visible
    named_by_kb = set(adapter.WORD.findall("\n".join(m["content"] or "" for m in kb)))
    assert set(trace["harness"]["offered"]) - named_by_kb
    # the audit record: exactly what was appended, where, and which tools it made available
    h = trace["harness"]
    assert set(h["offered_only_via_dep_search"]) == set(h["offered"]) - named_by_kb
    view = json.dumps(h["model_view"])
    for e in dep:
        assert e["kb_call_id"] and (not e["docs_added"] or json.dumps(e["appended_text"])[1:-1] in view)
    kb_ids = {m["tool_call_id"] for m in h["model_view"] if m["role"] == "tool" and "added by the harness" in
              (m["content"] or "")}
    assert kb_ids == {e["kb_call_id"] for e in dep if e["docs_added"]}
    assert trace["execution"]["finished"] and trace["evaluation"] is not None and trace["agent_inputs"]["passed"]
    assert trace["harness"]["dep_search"] is True


def test_end_to_end_without_the_option_nothing_is_added(tmp_path, monkeypatch):
    trace, seen = _run(tmp_path, [SEARCH, {"say": "Let me check."}, {"say": "Goodbye."}, {"say": "Goodbye."}],
                       {}, monkeypatch)
    assert not any(e["event"].startswith(depsearch.EVENT) for e in trace["harness"]["events"])
    assert not any("added by the harness" in s for s in seen)
    assert trace["harness"]["model_view"] and trace["harness"]["offered_only_via_dep_search"] is None


def test_end_to_end_verification_and_identifier_checks_still_apply(tmp_path, monkeypatch):
    trace, _ = _run(tmp_path, [SEARCH, {"call": "KB_search", "args": {"query": "identity verification"}},
                               {"call": "KB_search", "args": {"query": "transfer"}}, WRITE, WRITE,
                               {"say": "Goodbye."}, {"say": "Goodbye."}], {"dep_search": True}, monkeypatch)
    calls = [(tc["name"], tc["arguments"]) for m in trace["messages"] if m["role"] == "assistant"
             for tc in (m.get("tool_calls") or [])]
    assert not any(a.get("agent_tool_name") == "freeze_debit_card_3892" for n, a in calls
                   if n == "call_discoverable_agent_tool")
    events = [e["event"] for e in trace["harness"]["events"] if e["event"] in ("held", "withheld")]
    assert events == ["held", "withheld"]
    assert harness.WITHHELD["verification_before_write"] in json.dumps(trace["messages"])
