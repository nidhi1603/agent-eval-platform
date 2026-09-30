"""H006 re-runs the H005 pilot unchanged except for billed budget accounting. $0."""

import json

import pytest

import bench  # noqa: F401
from bench import REPO_ROOT, batch

PLAN = json.loads((REPO_ROOT / "experiments" / "H006_plan.json").read_text())
H005 = json.loads((REPO_ROOT / "experiments" / "H005_plan.json").read_text())


def test_the_same_pilot_with_only_the_accounting_changed():
    assert PLAN["tasks"] == H005["tasks"] and PLAN["runs"] == H005["runs"] and PLAN["arms"] == H005["arms"]
    assert {k: v for k, v in PLAN["settings"].items() if k != "budget_accounting"} == H005["settings"]
    assert PLAN["settings"]["budget_accounting"] == "billed"
    assert PLAN["decision_rule"] is None and PLAN["interpretation"] == H005["interpretation"]


def test_the_accounting_reaches_each_run(monkeypatch):
    seen = {}

    def fake_run(opts):
        seen["accounting"] = opts.budget_accounting
        return {"execution": {"finished": True}, "spend": {"incurred": {"upper_bound_usd": 0.3, "enforced_usd": 0.1}}}, REPO_ROOT

    monkeypatch.setattr(batch, "run", fake_run)
    row = batch._run_one(PLAN["runs"][0], {**PLAN["settings"], **PLAN["arms"]["baseline"]}, 0.75, None)
    assert seen["accounting"] == "billed" and row["spend_enforced_usd"] == 0.1 and row["spend_upper_bound_usd"] == 0.3


def test_budget():
    assert PLAN["budget_usd_total"] == 3.50 and PLAN["per_run_cap_usd"] == 0.75 and PLAN["execution"]["workers"] == 2
    with pytest.raises(SystemExit):
        batch.run_batch(PLAN, approved_usd=1.0)
