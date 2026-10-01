"""Resume a saved conversation just before a known disclosure (bench/resume.py). $0: scripted models."""
import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import
from bench import REPO_ROOT, resume

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

SRC = "runs/local/20261001T075452Z_task_019_live_7fd6efb5/trace.json"
END = 6
needs_trace = pytest.mark.skipif(not (REPO_ROOT / SRC).is_file(), reason="the source trace is local")


@needs_trace
def test_prepare_replaces_the_saved_draft_and_checks_fidelity():
    p = resume.prepare(SRC, END)
    assert all(v for k, v in p.checks.items() if isinstance(v, bool))
    assert p.replacement.startswith("Before I can go further") and "/1990" not in p.replacement
    draft = json.loads((REPO_ROOT / SRC).read_text())["messages"][END]["content"]
    assert p.draft_text == draft and p.trajectory_history[-1].content == p.replacement
    assert len(p.trajectory_history) == END + 1 and p.model_history[-1].content == p.replacement


@needs_trace
def test_prepare_refuses_a_message_the_check_would_not_replace():
    with pytest.raises(resume.ResumeError):
        resume.prepare(SRC, 4)      # a tool call, not an agent text
    with pytest.raises(resume.ResumeError):
        resume.prepare(SRC, 2)      # an agent text with no disclosure


@needs_trace
def test_resumed_run_restores_history_and_never_delivers_the_draft(tmp_path):
    from bench.run import RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    script = tmp_path / "s.json"
    script.write_text(json.dumps({"description": "MOCK resume", "agent": [{"say": "Thanks. Goodbye."}] * 4,
                                  "user": [{"say": "My date of birth is 01/01/2000."}] + [{"say": "###STOP###"}] * 4}))
    trace, _ = run(RunOptions(task_id="task_019", agent_model=AGENT_MODEL, user_model=USER_MODEL, retrieval_config="bm25",
                              scripted=script, out_dir=tmp_path, agent_harness={"version": "v3.2", "disclosure_check": True},
                              resume={"source_trace": SRC, "end": END}))
    src = json.loads((REPO_ROOT / SRC).read_text())["messages"]
    m = trace["messages"]
    assert [x.get("content") for x in m[:END]] == [x.get("content") for x in src[:END]]
    assert m[END]["content"] == trace["resume"]["replacement"] and m[END + 1]["role"] == "user"
    assert not any(x.get("content") == src[END]["content"] for x in m)
    assert trace["harness"]["events"][0]["event"] == "disclosure_replaced" and trace["harness"]["events"][0]["resumed"]
    assert trace["harness"]["runtime_matches_record"] is True


def test_resume_needs_the_disclosure_check(tmp_path):
    from bench.run import ConfigError, RunOptions, run
    from bench.scripted import AGENT_MODEL, USER_MODEL

    script = tmp_path / "s.json"
    script.write_text(json.dumps({"description": "MOCK", "agent": [{"say": "x"}], "user": [{"say": "###STOP###"}]}))
    trace, _ = run(RunOptions(task_id="task_019", agent_model=AGENT_MODEL, user_model=USER_MODEL, retrieval_config="bm25",
                              scripted=script, out_dir=tmp_path, agent_harness={"version": "v3.2"},
                              resume={"source_trace": SRC, "end": END}))
    assert "disclosure_check" in (trace["execution"]["error"] or "")


def test_batch_refuses_a_per_run_cap_below_two_reservations():
    """P002's first attempt: a $0.30 cap was below one gpt-5.2 user-simulator reservation on a restored conversation."""
    from bench import batch

    plan = json.loads((REPO_ROOT / "experiments" / "P002_plan.json").read_text())

    def settings_for(p):
        return lambda item: {**p["settings"], **(p["arms"][item["arm"]] if item["arm"] else {})}

    if not all((REPO_ROOT / r["resume"]["source_trace"]).is_file() for r in plan["runs"]):
        pytest.skip("the source traces are local")
    assert batch.cap_headroom({**plan, "per_run_cap_usd": 0.30}, settings_for(plan))
    assert batch.cap_headroom({**plan, "per_run_cap_usd": 0.80}, settings_for(plan)) == []
    for b in ("P001", "H009"):
        p = json.loads((REPO_ROOT / "experiments" / f"{b}_plan.json").read_text())
        assert batch.cap_headroom(p, settings_for(p)) == []
