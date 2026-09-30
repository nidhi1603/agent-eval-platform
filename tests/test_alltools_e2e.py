"""alltools end to end, $0: scripted conversations through tau2's real sandbox, with fake embeddings. Skipped when
sandbox-runtime (srt) or ripgrep is not installed."""

import json
import shutil

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")
pytestmark = pytest.mark.skipif(not (shutil.which("srt") and shutil.which("rg")),
                                reason="needs sandbox-runtime and ripgrep (tau2 src/tau2/knowledge/README.md)")

TOOL = "get_debit_cards_by_account_id_7823"
FILE = "doc_bank_accounts_bank_accounts__general__028.md"
STEPS = [{"call": "KB_search_bm25", "args": {"query": "debit card lost"}},
         {"call": "KB_search_dense", "args": {"query": "debit card lost"}},
         {"call": "shell", "args": {"command": f"grep -rn {TOOL} . | head -5"}},
         {"call": "shell", "args": {"command": f"cat {FILE}"}},
         {"call": "shell", "args": {"command": "printenv"}},
         {"say": "Let me check."}, {"say": "Goodbye."}, {"say": "Goodbye."}]


def _run(tmp_path, spec):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    tmp_path.mkdir(parents=True, exist_ok=True)
    s = tmp_path / "s.json"
    s.write_text(json.dumps({"agent": STEPS, "user": [{"say": "Hi, I lost my debit card."}, {"say": "OK."},
                                                        {"say": "Thanks. ###STOP###"}] + [{"say": "###STOP###"}] * 3}))
    trace, _ = run(RunOptions(task_id="task_089", agent_model=AGENT_MODEL, user_model=USER_MODEL,
                              retrieval_config="alltools", scripted=s, out_dir=tmp_path, agent_harness=spec,
                              budget_usd=20.0))
    return trace


@pytest.mark.parametrize("spec", [None, {}], ids=["standard", "harness_v1"])
def test_alltools_runs_contained_and_answer_independent(tmp_path, spec, monkeypatch):
    monkeypatch.setenv("AEP_FAKE_API_KEY", "canary-e2e")
    t = _run(tmp_path / ("s" if spec is None else "h"), spec)
    assert t["execution"]["finished"] and t["evaluation"] is not None and t["agent_inputs"]["passed"]
    assert t["answer_independence"]["conclusive"]
    results = {c["name"]: c["result"] for c in t["tool_calls"] if c["name"] in ("KB_search_bm25", "KB_search_dense")}
    assert set(results) == {"KB_search_bm25", "KB_search_dense"} and all("ID: doc_" in r for r in results.values())
    shell = [c["result"] for c in t["tool_calls"] if c["name"] == "shell"]
    assert FILE in shell[0] and TOOL in shell[0]                  # grep reached the knowledge base
    assert "Retrieving Debit Card Information" in shell[1]         # cat of a document
    assert "canary-e2e" not in shell[2] and "API_KEY" not in shell[2]   # the shell's environment is scrubbed
    assert t["sandbox_policy"]["deny_read_added"] and t["shell_audit"]["shell_calls"] == 3
    if spec is not None:
        assert TOOL in t["harness"]["offered"]                     # discovered from shell output
