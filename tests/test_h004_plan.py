"""The frozen H004 plan is consistent: two arms that differ only in dependency search, at H003's settings. Zero cost."""

import json
from collections import Counter

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, agent, batch, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H004_plan.json").read_text())
H002 = json.loads((REPO_ROOT / "experiments" / "H002_plan.json").read_text())
H003 = json.loads((REPO_ROOT / "experiments" / "H003_plan.json").read_text())


def test_the_arms_differ_only_in_dependency_search():
    v1, dep = PLAN["arms"]["harness_v1"], PLAN["arms"]["harness_v1_dep"]
    assert set(PLAN["arms"]) == {"harness_v1", "harness_v1_dep"}
    assert {k: v for k, v in dep.items() if k != "harness"} == {k: v for k, v in v1.items() if k != "harness"}
    a, b = agent.harness_record(v1["harness"]), agent.harness_record(dep["harness"])
    assert {k: v for k, v in b.items() if k != "dep_search"} == a and b["dep_search"] is True


def test_same_tasks_as_h002_and_same_settings_as_h003():
    assert PLAN["tasks"] == H002["tasks"] and set(PLAN["tasks"]) <= set(pins.load_split()["dev"])
    assert PLAN["settings"] == H003["settings"]
    assert PLAN["settings"]["agent_args"] == {"reasoning_effort": "medium"}
    assert PLAN["settings"]["max_output_tokens"] == 16384


def test_every_task_attempt_runs_both_arms_back_to_back_in_a_balanced_order():
    runs = PLAN["runs"]
    assert len(runs) == 40 and len({(r["task_id"], r["arm"], r["attempt"]) for r in runs}) == 40
    pairs = [runs[i:i + 2] for i in range(0, 40, 2)]
    assert all(p[0]["task_id"] == p[1]["task_id"] and p[0]["attempt"] == p[1]["attempt"]
               and {p[0]["arm"], p[1]["arm"]} == set(PLAN["arms"]) for p in pairs)
    first = Counter(p[0]["arm"] for p in pairs)
    assert first["harness_v1"] == first["harness_v1_dep"] == 10
    by_task = {}
    for p in pairs:
        by_task.setdefault(p[0]["task_id"], set()).add(p[0]["arm"])
    assert all(len(v) == 2 for v in by_task.values())  # a task's two attempts use opposite orders


def test_budget_workers_and_approval():
    assert PLAN["budget_usd_total"] == 12.0 and PLAN["per_run_cap_usd"] == 0.6 and PLAN["execution"]["workers"] == 2
    assert batch.schedule(PLAN) == PLAN["runs"]
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)
