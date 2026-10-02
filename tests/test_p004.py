"""P004: standard agent vs standard agent + transfer_code_recheck (plan, scripted pipeline, frozen decision). $0."""
import hashlib
import importlib.util
import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import
from bench import REPO_ROOT, batch

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

PLAN = json.loads((REPO_ROOT / "experiments" / "P004_plan.json").read_text())
H008 = json.loads((REPO_ROOT / "experiments" / "H008_plan.json").read_text())
_spec = importlib.util.spec_from_file_location("p004_verdict", REPO_ROOT / "research" / "p004" / "verdict.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


def test_arms_differ_only_by_the_one_check_and_settings_are_h008s():
    from bench import code_probe, pins

    assert PLAN["arms"] == {"baseline": {"agent_variant": "baseline"},
                            "recheck": {"agent_variant": "baseline", "nudges": ["transfer_code_recheck"]}}
    assert PLAN["settings"] == H008["settings"]
    assert PLAN["registered_agents"]["baseline"] != PLAN["registered_agents"]["recheck"]
    assert PLAN["component_text_sha256"] == hashlib.sha256(code_probe.feedback("treatment").encode()).hexdigest()
    p003 = json.loads((REPO_ROOT / "experiments" / "P003_plan.json").read_text())
    assert PLAN["tier_document_sha256"] == p003["tier_document_sha256"]   # the document P003 screened
    assert sorted(PLAN["tasks"]) == sorted(pins.load_split()["dev"]) and len(PLAN["tasks"]) == 30


def test_one_balanced_pair_per_task_and_the_reward_graded_code_tasks():
    runs = batch.schedule(PLAN)
    assert len(runs) == 60 and all(r["attempt"] == 0 for r in runs)
    pairs = [runs[i:i + 2] for i in range(0, 60, 2)]
    assert all(a["task_id"] == b["task_id"] and {a["arm"], b["arm"]} == {"baseline", "recheck"} for a, b in pairs)
    assert sum(p[0]["arm"] == "baseline" for p in pairs) == 15
    # only task_004 and task_012's REWARDS depend on the code (task_092 lists a transfer but is graded on the database)
    assert PLAN["strata"]["graded_reason"] == {"task_004": "account_ownership_dispute",
                                                "task_012": "kb_search_unsuccessful_customer_requests_transfer"}
    assert not batch.cap_headroom(PLAN, lambda it: {**PLAN["settings"], **PLAN["arms"][it["arm"]]})
    assert "run P004 with $9.00" in PLAN["execution"]["approval"] and PLAN["budget_usd_total"] == 9.0


def _mock_plan(tmp_path, script):
    plan = {**PLAN, "batch_id": "P004mock", "tasks": ["task_004"], "budget_usd_total": 1.0, "per_run_cap_usd": None,
            "runs": [{"task_id": "task_004", "arm": "baseline", "attempt": 0}, {"task_id": "task_004", "arm": "recheck", "attempt": 0}],
            "settings": {**PLAN["settings"], "agent_model": "scripted/agent", "user_model": "scripted/user",
                         "retrieval_config": "bm25", "scripted": str(REPO_ROOT / "bench" / "scripts" / script)}}
    plan["strata"] = {**PLAN["strata"]}
    out = batch.run_batch(plan, 1.0, out_dir=tmp_path)
    return plan, out["results"]


def test_scripted_pipeline_measures_the_component(tmp_path):
    from bench import diagnostics

    plan, rows = _mock_plan(tmp_path, "task_004_transfer_recheck.json")
    assert {r["arm"]: r["nudges"] for r in rows} == {"baseline": [], "recheck": ["transfer_code_recheck"]}
    s = V.summarize(rows, plan, diagnostics._tool_types()[0])
    assert s["complete_pairs"] == 1 and not any(s["defects"].values())
    c = s["component"]
    assert c["conversations_fired"] == 1 and c["replies"]["changed_code"] == 1
    assert c["code_changes"] == [{"task": "task_004", "from": "customer_requests_human_no_specific_reason", "to": "account_ownership_dispute"}]
    assert c["changed_to_graded_and_executed"] == ["task_004"] and not c["harm_graded_to_wrong"] and not c["harm_required_transfer_missing"]
    rc = next(f for f in s["per_conversation"] if f["arm"] == "recheck")
    assert rc["executed_transfer_reasons"] == ["account_ownership_dispute"] and rc["passed"]


def test_scripted_pipeline_flags_a_missing_required_transfer_after_the_hold(tmp_path):
    from bench import diagnostics

    plan, rows = _mock_plan(tmp_path, "task_004_transfer_recheck_once.json")
    s = V.summarize(rows, plan, diagnostics._tool_types()[0])
    c = s["component"]
    assert c["replies"]["text"] == 1 and c["changed_to_graded_and_executed"] == []
    # the later (unheld) transfer executes, so the required transfer is not missing; the code stays wrong
    assert c["harm_required_transfer_missing"] == [] and c["no_transfer_after_hold"] == []


def _summary(net=1, fired_ok=True, harm=False, defects=False, writes=0, cost=(1.0, 1.2)):
    return {"net_passes": net, "defects": {"fired_more_than_once": ["task_004"] if defects else []},
            "component": {"changed_to_graded_and_executed": ["task_004"] if fired_ok else [],
                          "harm_graded_to_wrong": ["task_012"] if harm else [], "harm_required_transfer_missing": [],
                          "writes_after_hold": writes},
            "arms": {"baseline": {"billed_usd": cost[0]}, "recheck": {"billed_usd": cost[1]}}}


CLAIMS_OK = {"per_arm": {"baseline": {"unsupported": 2, "affected": 2}, "recheck": {"unsupported": 1, "affected": 1}}}


def test_decision_rule_is_exhaustive_and_first_match():
    assert V.decide(_summary(defects=True), CLAIMS_OK, [])["verdict"] == "INVALID"
    assert V.decide(_summary(), None, [])["verdict"] == "INCOMPLETE_LABELS"
    assert V.decide(_summary(writes=1), CLAIMS_OK, None)["verdict"] == "INCOMPLETE_LABELS"
    assert V.decide(_summary(writes=1), CLAIMS_OK, [{"violation": None}])["verdict"] == "INCOMPLETE_LABELS"
    assert V.decide(_summary(), CLAIMS_OK, [])["verdict"] == "CONTINUE"
    assert V.decide(_summary(net=0), CLAIMS_OK, [])["failed"] == ["C1_net_passes_at_least_plus_1"]       # a tie is a no-go
    assert V.decide(_summary(fired_ok=False), CLAIMS_OK, [])["failed"] == ["C2_mechanism_seen_live"]
    assert V.decide(_summary(harm=True), CLAIMS_OK, [])["failed"] == ["C3_no_component_harm"]
    worse = {"per_arm": {"baseline": {"unsupported": 1, "affected": 1}, "recheck": {"unsupported": 2, "affected": 1}}}
    assert V.decide(_summary(), worse, [])["failed"] == ["C4_unsupported_statements_not_higher"]
    assert V.decide(_summary(writes=1), CLAIMS_OK, [{"violation": True}])["failed"] == ["C5_no_violating_write_after_hold"]
    assert V.decide(_summary(cost=(1.0, 1.6)), CLAIMS_OK, [])["failed"] == ["C6_cost_within_1_5x"]
