"""alltools compatibility, $0 and offline (sandbox-runtime is not required).

Covers: the evidence record across retrieval tools (bench/kb_evidence.py); tool discovery and v1 checks under
KB_search_bm25 / KB_search_dense / shell; sandbox read containment (bench/sandbox_policy.py); the metric regression
(bench/metrics.py); and the standard agent staying the benchmark's own."""

import json
from pathlib import Path

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import adapter, harness, kb_evidence, metrics, sandbox_policy  # noqa: E402
from bench.guard import Evidence  # noqa: E402

DOC = "doc_bank_accounts_bank_accounts_(general)_028"      # "Internal: Retrieving Debit Card Information"
TOOL = "get_debit_cards_by_account_id_7823"
OTHER = "doc_bank_accounts_bank_accounts_(general)_009"    # the account lookup


@pytest.fixture(scope="module")
def docs():
    return kb_evidence.corpus()


def _conv(*pairs):
    """[(tool name, arguments, output), ...] -> model-view dicts."""
    msgs = []
    for n, (name, args, out) in enumerate(pairs):
        cid = f"c{n}"
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": cid, "name": name, "arguments": args}]})
        msgs.append({"role": "tool", "tool_call_id": cid, "content": out, "error": False})
    return msgs


def _search_output(docs, *ids):
    return "\n".join(f"{i}. {docs[d]['title']}\n   ID: {d}\n   Score: 9.1\n   Content: {docs[d]['content']}\n"
                     for i, d in enumerate(ids, 1)) + "\n\n[Timing: retrieval=3ms, total=3ms]"


def _file(docs, d):
    return docs[d]["file"]


# ---- the evidence record -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["KB_search", "KB_search_bm25", "KB_search_dense"])
def test_search_results_are_full_observations_with_their_source(docs, tool):
    obs = kb_evidence.observations(_conv((tool, {"query": "debit card"}, _search_output(docs, DOC, OTHER))), docs)
    assert [(o.doc_id, o.level, o.tool, o.call_id, o.step) for o in obs] == [
        (DOC, "full", tool, "c0", 1), (OTHER, "full", tool, "c0", 1)]
    assert kb_evidence._norm(docs[DOC]["content"]) in kb_evidence._norm(obs[0].text)
    assert "[Timing" not in obs[1].text


def test_empty_or_failed_retrieval_yields_nothing(docs):
    conv = _conv(("KB_search_dense", {"query": "x"}, "No relevant documents found.\n\n[Timing: total=1ms]"),
                 ("shell", {"command": f"cat {_file(docs, DOC)}"}, "Error (exit code 2): no such file"),
                 ("shell", {"command": "cat \"$HOME\"/x"}, "Error: Command blocked - contains '~'"))
    assert kb_evidence.observations(conv, docs) == []


def test_shell_cat_of_one_file_is_full_and_head_is_an_excerpt(docs):
    whole = f"# {docs[DOC]['title']}\n\n{docs[DOC]['content']}"
    first = "\n".join(whole.splitlines()[:3])
    obs = kb_evidence.observations(_conv(("shell", {"command": f"cat {_file(docs, DOC)}"}, whole),
                                         ("shell", {"command": f"head -3 {_file(docs, OTHER)}"}, first)), docs)
    assert [(o.doc_id, o.level) for o in obs] == [(DOC, "full"), (OTHER, "excerpt")]
    assert obs[1].text == first


def test_shell_grep_lines_are_excerpts_of_the_files_they_came_from(docs):
    out = (f"./{_file(docs, DOC)}:12:Use {TOOL} with the account_id\n"
           f"{_file(docs, OTHER)}-3-Some context line\n")
    obs = kb_evidence.observations(_conv(("shell", {"command": "grep -rn -C1 account_id ."}, out)), docs)
    got = {o.doc_id: (o.level, o.text) for o in obs}
    assert got[DOC] == ("excerpt", f"Use {TOOL} with the account_id")
    assert got[OTHER] == ("excerpt", "Some context line")


def test_a_listing_only_discovers_documents(docs):
    out = f"INDEX.md\n{_file(docs, DOC)}\n{_file(docs, OTHER)}\n"
    obs = kb_evidence.observations(_conv(("shell", {"command": "ls"}, out)), docs)
    assert {(o.doc_id, o.level, o.text) for o in obs} == {(DOC, "discovered", ""), (OTHER, "discovered", "")}


# ---- tool discovery and the v1 checks see every retrieval tool, but only output ---------------------------------------

def _tau2_msgs(conv):
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage

    out = []
    for m in conv:
        if m["role"] == "assistant":
            out.append(AssistantMessage(role="assistant", content=None, tool_calls=[
                ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"], requestor="assistant")
                for c in m["tool_calls"]]))
        else:
            out.append(ToolMessage(id=m["tool_call_id"], role="tool", requestor="assistant", content=m["content"],
                                   error=m["error"]))
    return out


@pytest.mark.parametrize("tool,args,out_kind", [("KB_search_dense", {"query": "cards"}, "search"),
                                                 ("shell", {"command": "grep -rn account_id ."}, "grep")])
def test_the_adapter_offers_tools_named_in_any_retrieval_output(docs, tool, args, out_kind):
    out = _search_output(docs, DOC) if out_kind == "search" else f"./{_file(docs, DOC)}:5:call {TOOL}\n"
    assert adapter.names_in_kb_results(_tau2_msgs(_conv((tool, args, out))), {TOOL}) == {TOOL}


def test_a_tool_named_only_in_a_shell_command_is_not_discovered():
    conv = _conv(("shell", {"command": f"grep -rn {TOOL} ."}, "No matches found."),
                 ("shell", {"command": f"echo {TOOL}"}, "(no output)"))
    assert adapter.names_in_kb_results(_tau2_msgs(conv), {TOOL}) == set()
    ev = Evidence(messages=conv, tool_type=lambda n: "read")
    assert harness.kb_names(ev, {TOOL}) == [] and harness.searches(ev) == []


def test_searches_count_every_retrieval_tool_and_kb_search_is_unchanged(docs):
    conv = _conv(("KB_search", {"query": "a"}, _search_output(docs, DOC)),
                 ("KB_search_bm25", {"query": "b"}, _search_output(docs, OTHER)),
                 ("KB_search_dense", {"query": "c"}, "No relevant documents found."),
                 ("shell", {"command": "ls"}, f"{_file(docs, DOC)}\n"))
    ev = Evidence(messages=conv, tool_type=lambda n: "read")
    # KB searches count as before (any non-error result, even an empty one); a shell command counts if it produced output
    assert harness.searches(ev) == ["a", "b", "c", "ls"]
    assert TOOL in harness.kb_names(ev, {TOOL})


# ---- containment (shared infrastructure) ------------------------------------------------------------------------

def test_the_sandbox_denies_reads_of_the_answer_key_and_this_repo(tmp_path):
    from tau2.knowledge.sandbox_manager import SandboxManager

    assert sandbox_policy.patch() and sandbox_policy.patch()   # idempotent
    sm = SandboxManager.__new__(SandboxManager)                 # no srt needed to write the settings file
    sm.sandbox_dir, sm.kb_dir, sm.allow_writes = tmp_path, tmp_path / "knowledge_base", False
    sm.settings_path = tmp_path / "srt-settings.json"
    sm._create_srt_settings()
    fs = json.loads(sm.settings_path.read_text())["filesystem"]
    deny = fs["denyRead"]
    assert "~/.ssh" in deny                                     # tau2's own entries are kept
    assert str(bench.REPO_ROOT.resolve()) in deny
    tasks = (Path(bench.os.environ["TAU2_DATA_DIR"]) / "tau2" / "domains" / "banking_knowledge" / "tasks").resolve()
    assert any(str(tasks).startswith(p) for p in deny)
    assert fs["allowWrite"] == []                               # writes untouched (alltools is read-only)


def test_the_shell_audit_flags_escape_attempts_and_ground_truth():
    conv = _conv(("shell", {"command": "cat \"$HOME\"/Desktop/x.json"}, "{\"evaluation_criteria\": {}}"),
                 ("shell", {"command": "grep -rn fee ."}, "./a.md:1:fee"),
                 ("shell", {"command": "cat ../x"}, "Error: Command blocked - contains '..' which could escape"))
    a = sandbox_policy.audit(conv)
    assert a["shell_calls"] == 3
    assert [f["reasons"] for f in a["flagged"]] == [["escape_pattern", "ground_truth_like_output"],
                                                   ["escape_pattern", "blocked_by_tau2"]]


# ---- the metric regression ----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tool_type():
    import sys

    sys.path.insert(0, str(bench.REPO_ROOT / "research" / "h002"))
    from tool_retrieval_probe import registry

    return registry()[1]


def test_a_lookup_through_the_wrapper_is_a_read_not_a_write(tool_type):
    from tau2.runner.helpers import get_tasks

    task = get_tasks("banking_knowledge", task_ids=["task_077"])[0]
    buckets = {(a.name, (a.arguments or {}).get("agent_tool_name")): metrics.bucket_of(a, tool_type)
               for a in task.evaluation_criteria.actions}
    call = "call_discoverable_agent_tool"
    assert buckets[(call, "get_all_user_accounts_by_user_id_3847")] == "discoverable_reads"   # counted as a write before
    assert buckets[(call, "order_replacement_credit_card_7291")] == "discoverable_writes"
    assert buckets[("unlock_discoverable_agent_tool", "get_all_user_accounts_by_user_id_3847")] == "other"
    assert buckets[("log_verification", None)] == "base_writes"
    assert metrics.kind("call_discoverable_agent_tool", {"agent_tool_name": "get_all_user_accounts_by_user_id_3847"},
                        tool_type) == "read"


def test_the_corrected_h004_counts_are_reproduced(tool_type):
    from tau2.runner.helpers import get_tasks

    res = json.loads((bench.REPO_ROOT / "experiments" / "H004_results.json").read_text())
    rows = [r for r in res["results"] if r.get("trace") and Path(r["trace"]).exists()]
    if len(rows) < 40:
        pytest.skip("H004 traces are local run artefacts; not all present here")
    tasks = {t.id: t for t in get_tasks("banking_knowledge", task_ids=sorted({r["task_id"] for r in rows}))}
    tot = {}
    for r in rows:
        p = metrics.progress(json.loads(Path(r["trace"]).read_text())["messages"],
                             tasks[r["task_id"]].evaluation_criteria.actions, tool_type)
        a = tot.setdefault(r["arm"], [0, 0, 0, 0])
        a[0] += p["ref_discoverable_writes_matched"]
        a[1] += p["ref_discoverable_writes"]
        a[2] += p["ref_discoverable_reads_matched"]
        a[3] += p["ref_discoverable_reads"]
    assert tot == {"harness_v1": [17, 90, 29, 58], "harness_v1_dep": [43, 90, 35, 58]}


# ---- the standard arm stays the benchmark's own agent -------------------------------------------------------------

def test_the_standard_agent_is_tau2s_llm_agent_unmodified():
    from tau2.agent.llm_agent import LLMAgent

    from bench import agent

    built = agent.factory(tools=[], domain_policy="policy", llm="gpt-5-mini", llm_args={})
    assert type(built) is LLMAgent
    assert not hasattr(built, "harness_events") and not hasattr(built, "adapter_events")
