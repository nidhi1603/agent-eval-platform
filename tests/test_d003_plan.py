"""D003 (instruction ablation) is what it claims to be: the arms differ only in instruction text, the evidence
checker is off in both, and post-hoc assessment works on its records. Zero cost."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, continuation, evidence, variants  # noqa: E402
from bench.budget import Budget, Limits, install  # noqa: E402
from bench.scripted import AGENT_MODEL, FAKE_PRICES, ScriptedLLM  # noqa: E402

PLAN = json.loads((REPO_ROOT / "experiments" / "D003_plan.json").read_text())
D002 = json.loads((REPO_ROOT / "experiments" / "D002_plan.json").read_text())


def test_arms_differ_only_in_instruction_text():
    assert all(a == {"evidence": None, "guard_rules": [], "nudges": []} for a in PLAN["arms"].values())
    by_arm = {r["arm"]: r["variant"] for r in PLAN["runs"]}
    a, b = variants.text(by_arm["A_interface"]), variants.text(by_arm["B_interface_evidence"])
    assert b.startswith(a) and "## Evidence for account changes" in b[len(a):]
    assert len(PLAN["runs"]) == 12 and {r["case"] for r in PLAN["runs"]} == {c["id"] for c in PLAN["cases"]}


def test_same_prefixes_as_d002_and_fresh_samples_in_both_arms():
    key = lambda c: (c["id"], c["task_id"], c["source_trace"], c["prefix_end"])  # noqa: E731
    assert sorted(map(key, PLAN["cases"])) == sorted(map(key, D002["cases"]))
    assert {r["arm"] for r in PLAN["runs"]} == {"A_interface", "B_interface_evidence"}
    assert PLAN["settings"]["max_rounds"] == D002["settings"]["max_rounds"]


def test_checker_off_means_no_harness_and_post_hoc_assessment_still_works(tmp_path):
    case = {c["id"]: c for c in PLAN["cases"]}["D1"]
    credit = {"call": "call_discoverable_agent_tool", "args": {"agent_tool_name": "apply_statement_credit_8472",
              "arguments": json.dumps({"user_id": "c7d8e9f0a1", "credit_card_account_id": "cc_c7d8e9f0a1_plat",
                                       "amount": 50.0, "reason": "retention_offer"})}}
    budget = Budget(1.0, FAKE_PRICES, tmp_path / "l.jsonl")
    with install(budget, Limits(), send=ScriptedLLM({"agent": [credit, {"say": "Applied."}]})):
        r = continuation.continue_case(case, "discovery_interface_v2", AGENT_MODEL, {}, max_rounds=12, budget=budget)
    assert r["harness_events"] == [] and r["score"]["success"]  # plain agent: nothing reviewed at run time
    rows = evidence.audit_continuations(PLAN, {"results": [{**r, "run": 0, "variant": "discovery_interface_v2"}]},
                                        lambda n: "write" if n == "apply_statement_credit_8472" else "read")
    assert rows[0]["executed"] and not rows[0]["would_allow"]
    assert rows[0]["findings"][-1]["status"] == "missing_contract"


def test_useful_progress_needs_the_right_customer_and_resource(tmp_path):
    case = {c["id"]: c for c in PLAN["cases"]}["X1"]
    acct = "get_all_user_accounts_by_user_id_3847"

    def run(user, sub):
        steps = [{"call": "unlock_discoverable_agent_tool", "args": {"agent_tool_name": acct}},
                 {"call": "call_discoverable_agent_tool", "args": {"agent_tool_name": acct,
                                                                   "arguments": json.dumps({"user_id": user})}},
                 {"say": "ok"}]
        budget = Budget(1.0, FAKE_PRICES, tmp_path / f"{sub}.jsonl")
        with install(budget, Limits(), send=ScriptedLLM({"agent": steps})):
            return continuation.continue_case(case, "discovery_interface_v2", AGENT_MODEL, {}, max_rounds=12, budget=budget)
    assert run("wl94k7m3p8", "right")["score"]["progress"]
    wrong = run("mt35a7c9d2", "wrong")  # another real customer: the call succeeds, but it is not useful progress
    assert wrong["calls"][-1]["ok"] and not wrong["score"]["progress"]
    assert "Completion is not guaranteed" in PLAN["budget_options"]["recommended"]["note"]
