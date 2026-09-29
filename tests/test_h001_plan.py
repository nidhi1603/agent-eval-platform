"""The frozen H001 pilot plan (experiments/H001_plan.json) is internally consistent. Zero cost."""

import json
from collections import Counter

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, agent, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H001_plan.json").read_text())


def test_only_development_tasks_and_a_fixed_selection_rule():
    import hashlib

    split = pins.load_split()
    assert set(PLAN["tasks"]) <= set(split["dev"]) and not set(PLAN["tasks"]) & set(split["test"])
    expected = sorted(split["dev"], key=lambda t: hashlib.sha256(f"H001:{t}".encode()).hexdigest())[:10]
    assert PLAN["tasks"] == expected


def test_every_task_and_attempt_has_both_arms_back_to_back_and_order_is_balanced():
    runs = PLAN["runs"]
    assert len(runs) == 40
    pairs = [runs[i:i + 2] for i in range(0, 40, 2)]
    for a, b in pairs:
        assert (a["task_id"], a["attempt"]) == (b["task_id"], b["attempt"]) and {a["arm"], b["arm"]} == set(PLAN["arms"])
    assert sum(p[0]["arm"] == "harness_v1" for p in pairs) == 10
    per_task = Counter(p[0]["task_id"] for p in pairs if p[0]["arm"] == "harness_v1")
    assert all(per_task[t] == 1 for t in PLAN["tasks"])  # each task: harness first in exactly one attempt


def test_arms_differ_only_by_the_harness_and_settings_match_s002_s003():
    base, h = PLAN["arms"]["baseline"], PLAN["arms"]["harness_v1"]
    assert base == {"agent_variant": "baseline"} and {k: v for k, v in h.items() if k != "harness"} == base
    assert agent.harness_record(h["harness"])["gates"]  # a valid spec
    s002 = json.loads((REPO_ROOT / "experiments" / "S002_plan.json").read_text())
    for k in ("agent_model", "agent_args", "user_model", "user_args", "retrieval_config"):
        assert PLAN["settings"][k] == (s002.get("settings") or s002)[k]


def test_nothing_runs_without_an_approved_amount_matching_the_plan():
    from bench.batch import run_batch

    with pytest.raises(SystemExit):
        run_batch(PLAN, approved_usd=PLAN["budget_usd_total"] + 1)
