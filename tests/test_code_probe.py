"""Reason-code probe (bench/code_probe.py, P003). $0."""
import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import
from bench import REPO_ROOT, code_probe as cp

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")


def test_arms_differ_only_by_the_tier_document():
    c, t = cp.feedback("control"), cp.feedback("treatment")
    assert t.startswith(c) and "TIER 1 (HIGHEST PRIORITY)" in t and "TIER 1" not in c
    assert {"account_ownership_dispute", "technical_system_error", "kb_search_unsuccessful_customer_requests_transfer"} <= cp.valid_codes()


def test_scoring_counts_missing_and_invalid_transfers_as_wrong():
    codes = cp.valid_codes()
    call = lambda r: {"tool_calls": [{"name": cp.TRANSFER, "arguments": {"reason": r, "summary": "x"}}]}  # noqa: E731
    assert cp.score(call("account_ownership_dispute"), "account_ownership_dispute", codes)["correct"]
    assert cp.score(call("customer_requests_human_no_specific_reason"), "account_ownership_dispute", codes)["correct"] is False
    assert cp.score(call("made_up_code"), "account_ownership_dispute", codes)["outcome"] == "invalid_code"
    assert cp.score({"content": "I'll transfer you."}, "account_ownership_dispute", codes)["outcome"] == "no_transfer_call"


PLAN = REPO_ROOT / "experiments" / "P003_plan.json"


@pytest.mark.skipif(not PLAN.is_file(), reason="needs the P003 plan")
def test_every_case_reconstructs_and_the_gate_is_exhaustive():
    plan = json.loads(PLAN.read_text())
    if not all((REPO_ROOT / c["source_trace"]).is_file() for c in plan["cases"]):
        pytest.skip("the source traces are local")
    for spec in plan["cases"]:
        assert all(cp.Case(spec).checks().values()), spec["id"]
    # summarize: all samples correct -> PASS; an originally-correct case broken -> FAIL; missing samples -> INCOMPLETE
    rows = [{"status": "done", "case": r["case"], "arm": r["arm"], "correct": True, "outcome": "transfer_call"} for r in plan["runs"]]
    assert cp.summarize(rows, plan)["verdict"] == "FAIL"   # G2: treatment not MORE correct than control
    rows2 = [dict(r, correct=r["arm"] == "treatment") for r in rows]
    assert cp.summarize(rows2, plan)["verdict"] == "PASS"
    right = next(c["id"] for c in plan["cases"] if c["originally_correct"])
    rows3 = [dict(r, correct=False) if r["case"] == right and r["arm"] == "treatment" else r for r in rows2]
    assert cp.summarize(rows3, plan)["verdict"] == "FAIL"
    assert cp.summarize(rows2[:-1], plan)["verdict"] == "INCOMPLETE"


@pytest.mark.skipif(not PLAN.is_file(), reason="needs the P003 plan")
def test_a_scripted_run_records_scores_and_meters_every_sample(tmp_path):
    from bench.budget import load_prices
    from bench.scripted import ScriptedLLM

    plan = json.loads(PLAN.read_text())
    if not all((REPO_ROOT / c["source_trace"]).is_file() for c in plan["cases"]):
        pytest.skip("the source traces are local")
    keep = [c["id"] for c in plan["cases"] if c["source_harness"] == "standard agent"][:1] + \
           [c["id"] for c in plan["cases"] if c["source_harness"] != "standard agent"][:1]
    plan = dict(plan, runs=[r for r in plan["runs"] if r["case"] in keep])
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    steps = [{"call": "transfer_to_human_agents", "args": {"reason": "technical_system_error", "summary": "s"}},
             {"say": "Transferring you now."}, {"call": "transfer_to_human_agents", "args": {"reason": "bogus", "summary": "s"}}] * 4
    code = cp.main([str(path), "--approved-usd", str(plan["budget_usd_total"]), "--out-dir", str(tmp_path)],
                   send=ScriptedLLM({"agent": steps}), prices=load_prices())
    out = json.loads((tmp_path / "P003_results.json").read_text())
    assert code == 0 and out["by_status"] == {"done": 12}
    assert [r["outcome"] for r in out["results"]] == ["transfer_call", "no_transfer_call", "invalid_code"] * 4
    assert out["fidelity"]["tools_sent_equal_original_request"] is True
    assert out["result"]["verdict"] == "INCOMPLETE"       # only 2 of the 20 cases ran
    with pytest.raises(SystemExit):
        cp.main([str(path), "--approved-usd", "0.5", "--out-dir", str(tmp_path / "x")], send=ScriptedLLM({"agent": []}))
