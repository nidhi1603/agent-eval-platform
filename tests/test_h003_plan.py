"""The frozen H003 calibration plan is consistent, and its output allowance reaches the run. Zero cost."""

import json

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, batch, pins

PLAN = json.loads((REPO_ROOT / "experiments" / "H003_plan.json").read_text())
H002 = json.loads((REPO_ROOT / "experiments" / "H002_plan.json").read_text())


def test_baseline_only_on_h002_tasks_with_disclosed_setting_changes():
    assert PLAN["tasks"] == H002["tasks"][:5] and set(PLAN["tasks"]) <= set(pins.load_split()["dev"])
    assert list(PLAN["arms"]) == ["baseline_medium"] and PLAN["arms"]["baseline_medium"] == {"agent_variant": "baseline"}
    changed = {k for k in PLAN["settings"] if PLAN["settings"][k] != H002["settings"].get(k)}
    assert changed == {"agent_args", "max_output_tokens"}
    assert PLAN["settings"]["agent_args"] == {"reasoning_effort": "medium"} and PLAN["settings"]["max_output_tokens"] == 16384


def test_the_output_allowance_is_passed_to_the_run(monkeypatch):
    seen = {}

    def fake_run(opts):
        seen["limits"] = opts.limits
        return {"execution": {"finished": True}, "spend": {"incurred": {"upper_bound_usd": 0.1}}}, REPO_ROOT

    monkeypatch.setattr(batch, "run", fake_run)
    batch._run_one(PLAN["runs"][0], {**PLAN["settings"], **PLAN["arms"]["baseline_medium"]}, 1.0, None)
    assert seen["limits"].max_output_tokens == 16384


def test_needs_the_exact_approval():
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)
