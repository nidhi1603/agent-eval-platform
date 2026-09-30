"""The frozen H002 plan (experiments/H002_plan.json) is internally consistent, and three-arm comparisons are
computed correctly. Zero cost."""

import json
from collections import Counter

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, agent, batch, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H002_plan.json").read_text())
H001 = json.loads((REPO_ROOT / "experiments" / "H001_plan.json").read_text())
ARMS = {"baseline", "harness_v1", "harness_v2"}


def test_same_development_tasks_and_settings_as_h001_which_is_marked_superseded():
    assert PLAN["tasks"] == H001["tasks"] and PLAN["settings"] == H001["settings"]
    assert set(PLAN["tasks"]) <= set(pins.load_split()["dev"])
    assert H001["status"].startswith("SUPERSEDED by H002")


def test_every_group_runs_all_three_arms_back_to_back_and_positions_are_balanced():
    runs = PLAN["runs"]
    assert len(runs) == 60
    groups = [runs[i:i + 3] for i in range(0, 60, 3)]
    orders = {}
    for g in groups:
        assert len({(r["task_id"], r["attempt"]) for r in g}) == 1 and {r["arm"] for r in g} == ARMS
        orders[(g[0]["task_id"], g[0]["attempt"])] = tuple(r["arm"] for r in g)
    assert all(orders[(t, 0)] != orders[(t, 1)] for t in PLAN["tasks"])
    for pos in range(3):
        counts = Counter(o[pos] for o in orders.values())
        assert set(counts) == ARMS and max(counts.values()) - min(counts.values()) <= 1


def test_arms_differ_only_by_the_harness_spec():
    arms = PLAN["arms"]
    assert arms["baseline"] == {"agent_variant": "baseline"}
    assert agent.harness_record(arms["harness_v1"]["harness"])["gates"] == agent.harness_record({})["gates"]
    assert agent.harness_record(arms["harness_v2"]["harness"])["name"] == "harness_v2"
    for a in ("harness_v1", "harness_v2"):
        assert {k: v for k, v in arms[a].items() if k != "harness"} == arms["baseline"]


def test_budget_needs_the_exact_approval_and_parallel_reservations_are_set():
    assert PLAN["per_run_cap_usd"] and PLAN["execution"]["workers"] >= 1
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=PLAN["budget_usd_total"] - 1)


def test_three_arm_comparisons_are_paired_per_task_and_attempt():
    rows = [{"task_id": "t", "attempt": 0, "arm": a, "status": "finished", "official_reward": r}
            for a, r in (("baseline", 0.0), ("harness_v1", 1.0), ("harness_v2", 0.0))]
    rows.append({"task_id": "u", "attempt": 0, "arm": "baseline", "status": "finished", "official_reward": 1.0})
    out = batch._comparisons(rows, PLAN["comparisons"])
    assert out["harness_v1 vs baseline"]["counts"]["improved"] == 1
    assert out["harness_v2 vs harness_v1"]["counts"]["regressed"] == 1
    assert out["harness_v2 vs baseline"]["counts"]["incomplete pair"] == 1  # u has no v2 run: kept, labelled
