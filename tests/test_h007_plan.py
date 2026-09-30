"""The frozen H007 plan: standard agent vs harness v3 on the dev tasks strong public agents solve. $0."""

import json
from collections import Counter

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, agent, batch, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H007_plan.json").read_text())
H006 = json.loads((REPO_ROOT / "experiments" / "H006_plan.json").read_text())


def test_standard_agent_vs_v3_with_unchanged_settings():
    assert set(PLAN["arms"]) == {"baseline", "harness_v3"} and PLAN["arms"]["baseline"] == {"agent_variant": "baseline"}
    spec = agent.harness_record(PLAN["arms"]["harness_v3"]["harness"])
    assert spec["capability_search"] is True and "dep_search" not in spec and spec["gates"] == agent.harness_record({})["gates"]
    assert PLAN["settings"] == H006["settings"] and PLAN["settings"]["budget_accounting"] == "billed"
    assert PLAN["settings"]["retrieval_config"] == "alltools"


def test_the_tasks_are_the_dev_tasks_both_public_agents_pass_at_least_3_of_4():
    assert set(PLAN["tasks"]) <= set(pins.load_split()["dev"]) and len(PLAN["tasks"]) == 12
    feats = REPO_ROOT / "research" / "public_trajectories" / "features_dev.json"
    passes = Counter()
    for x in json.loads(feats.read_text()):
        if x["model"] in ("gpt-5.5", "qwen-3.8-max"):
            passes[x["task"], x["model"]] += x["reward"] >= 1
    solved = {t for t in pins.load_split()["dev"] if passes[t, "gpt-5.5"] >= 3 and passes[t, "qwen-3.8-max"] >= 3}
    assert set(PLAN["tasks"]) == solved


def test_balanced_pairs_and_budget():
    runs = PLAN["runs"]
    assert len(runs) == 48 and len({(r["task_id"], r["arm"], r["attempt"]) for r in runs}) == 48
    pairs = [runs[i:i + 2] for i in range(0, 48, 2)]
    assert all(p[0]["task_id"] == p[1]["task_id"] and p[0]["attempt"] == p[1]["attempt"]
               and {p[0]["arm"], p[1]["arm"]} == set(PLAN["arms"]) for p in pairs)
    assert Counter(p[0]["arm"] for p in pairs) == {"baseline": 12, "harness_v3": 12}
    assert PLAN["budget_usd_total"] == 9.0 and PLAN["per_run_cap_usd"] == 0.75 and PLAN["execution"]["workers"] == 2
    assert batch.schedule(PLAN) == runs
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)
