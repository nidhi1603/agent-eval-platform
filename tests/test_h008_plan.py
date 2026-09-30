"""The frozen H008 plan: H007 with harness v3.1 as the treatment, strata fixed before the run, and two added gate
conditions (budget censoring; no best-of-two scoring). $0."""

import json
from collections import Counter

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, agent, batch, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H008_plan.json").read_text())
H007 = json.loads((REPO_ROOT / "experiments" / "H007_plan.json").read_text())
ARM = "harness_v3_1"


def test_only_the_treatment_arm_changed_from_h007():
    assert set(PLAN["arms"]) == {"baseline", ARM} and PLAN["arms"]["baseline"] == {"agent_variant": "baseline"}
    spec = agent.harness_record(PLAN["arms"][ARM]["harness"])
    assert spec["capability_search"] is True and spec["transfer_hold_once"] is True and "dep_search" not in spec
    assert spec["gates"] == agent.harness_record({})["gates"]
    for key in ("tasks", "settings", "trials_per_arm", "budget_usd_total", "per_run_cap_usd", "selection_rule"):
        assert PLAN[key] == H007[key], key
    renamed = [{**r, "arm": ARM if r["arm"] == "harness_v3" else r["arm"]} for r in H007["runs"]]
    assert PLAN["runs"] == renamed and batch.schedule(PLAN) == renamed and len(renamed) == 48
    assert "superseded by H008" in H007["status"] and "H007" in PLAN["supersedes"]


def test_the_gate_keeps_h007s_conditions_and_adds_censoring_and_scoring_rules():
    rule = PLAN["decision_rule"]
    assert "at least 5 more of 24" in rule and "by at least 3" in rule and "safety screen" in rule
    assert "counted as a failure" in rule and "best of two" in rule and "insufficient evidence" in rule
    assert "3-6%" in PLAN["noise_floor"] and "29-40%" in PLAN["noise_floor"]


def test_the_strata_come_from_each_tasks_reward_basis():
    pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")
    from tau2.runner.helpers import get_tasks

    tasks = get_tasks("banking_knowledge", task_ids=sorted(PLAN["tasks"]))
    action = {t.id for t in tasks if [b.value for b in t.evaluation_criteria.reward_basis] == ["ACTION"]}
    s = PLAN["strata"]
    assert set(s["action_graded_transfer_tasks"]) == action
    assert set(s["database_graded_tasks"]) == set(PLAN["tasks"]) - action and len(s["database_graded_tasks"]) == 9
    assert all(any(a.name == "transfer_to_human_agents" for a in t.evaluation_criteria.actions) for t in tasks if t.id in action)
    assert set(PLAN["tasks"]) <= set(pins.load_split()["dev"])


def test_balanced_pairs_and_approval():
    pairs = [PLAN["runs"][i:i + 2] for i in range(0, 48, 2)]
    assert all(p[0]["task_id"] == p[1]["task_id"] and p[0]["attempt"] == p[1]["attempt"]
               and {p[0]["arm"], p[1]["arm"]} == set(PLAN["arms"]) for p in pairs)
    assert Counter(p[0]["arm"] for p in pairs) == {"baseline": 12, ARM: 12}
    assert "run H008 with $9.00" in PLAN["execution"]["approval"] and PLAN["execution"]["resume"].endswith("H008_journal.jsonl")
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)
