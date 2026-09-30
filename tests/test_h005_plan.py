"""The frozen H005 plan: standard agent vs harness v1 under alltools, identical settings, no dependency search. $0."""

import json
from collections import Counter

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, agent, batch, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H005_plan.json").read_text())
H004 = json.loads((REPO_ROOT / "experiments" / "H004_plan.json").read_text())


def test_standard_agent_vs_v1_without_dependency_search():
    assert set(PLAN["arms"]) == {"baseline", "harness_v1"}
    assert PLAN["arms"]["baseline"] == {"agent_variant": "baseline"}               # tau2's LLMAgent, unmodified
    spec = agent.harness_record(PLAN["arms"]["harness_v1"]["harness"])
    assert "dep_search" not in spec and spec == agent.harness_record({})
    assert PLAN["comparisons"] == ["harness_v1 vs baseline"]


def test_h004_settings_with_alltools_and_the_same_tasks():
    assert {k: v for k, v in PLAN["settings"].items() if k != "retrieval_config"} == \
        {k: v for k, v in H004["settings"].items() if k != "retrieval_config"}
    assert PLAN["settings"]["retrieval_config"] == "alltools"
    assert PLAN["tasks"] == H004["tasks"] and set(PLAN["tasks"]) <= set(pins.load_split()["dev"])


def test_balanced_pairs_and_budget():
    runs = PLAN["runs"]
    assert len(runs) == 40 and len({(r["task_id"], r["arm"], r["attempt"]) for r in runs}) == 40
    pairs = [runs[i:i + 2] for i in range(0, 40, 2)]
    assert all(p[0]["task_id"] == p[1]["task_id"] and p[0]["attempt"] == p[1]["attempt"] for p in pairs)
    assert Counter(p[0]["arm"] for p in pairs) == {"baseline": 10, "harness_v1": 10}
    assert PLAN["budget_usd_total"] == 15.0 and PLAN["per_run_cap_usd"] == 1.0
    assert PLAN["preflight"]["budget_usd"] <= 0.30
    assert batch.schedule(PLAN) == runs
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)
