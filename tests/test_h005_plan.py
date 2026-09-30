"""The frozen H005 plan: standard agent vs harness v1 under alltools, identical settings, no dependency search. $0."""

import json
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


def test_h004_settings_with_alltools_and_the_h003_tasks():
    assert {k: v for k, v in PLAN["settings"].items() if k != "retrieval_config"} == \
        {k: v for k, v in H004["settings"].items() if k != "retrieval_config"}
    assert PLAN["settings"]["retrieval_config"] == "alltools"
    h003 = json.loads((REPO_ROOT / "experiments" / "H003_plan.json").read_text())
    assert PLAN["tasks"] == H004["tasks"][:5] == h003["tasks"] and set(PLAN["tasks"]) <= set(pins.load_split()["dev"])


def test_ten_paired_conversations_alternating_order_and_a_five_dollar_cap():
    runs = PLAN["runs"]
    assert len(runs) == 10 and len({(r["task_id"], r["arm"]) for r in runs}) == 10
    pairs = [runs[i:i + 2] for i in range(0, 10, 2)]
    assert all(p[0]["task_id"] == p[1]["task_id"] and {p[0]["arm"], p[1]["arm"]} == set(PLAN["arms"]) for p in pairs)
    assert [p[0]["arm"] for p in pairs] == ["baseline", "harness_v1", "baseline", "harness_v1", "baseline"]
    assert PLAN["approval_total_usd"] == 5.0 and PLAN["per_run_cap_usd"] == 1.0
    assert PLAN["budget_usd_total"] + PLAN["preflight"]["budget_usd"] <= PLAN["approval_total_usd"] + 1e-9
    assert batch.schedule(PLAN) == runs
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)


def test_descriptive_screening_has_no_pass_count_gate():
    assert PLAN["decision_rule"] is None and "+4" not in json.dumps(PLAN["interpretation"])
    assert "DESCRIPTIVE SCREENING" in PLAN["interpretation"]
