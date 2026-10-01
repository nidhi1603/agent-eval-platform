"""D005: recovery probe of v3.2's verification feedback (bench/verify_probe.py). $0: scripted model, no network."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, verify_probe  # noqa: E402
from bench.budget import load_prices  # noqa: E402
from bench.scripted import ScriptedLLM  # noqa: E402

PLAN = json.loads((REPO_ROOT / "experiments" / "D005_plan.json").read_text())
HAVE_TRACES = all((REPO_ROOT / c["source_trace"]).is_file() for c in PLAN["cases"])
needs_traces = pytest.mark.skipif(not HAVE_TRACES, reason="the source traces are local (runs/ is not committed)")
RECORD = {"date_of_birth": "07/22/1985", "phone_number": "206-555-0293", "email": "kenji.tanaka@outlook.com",
          "address": "1847 Cherry Blossom Lane, Seattle, WA 98101"}


@pytest.mark.parametrize("text,asks,verified", [
    ("Could you please share your date of birth?", True, False),
    ("To finish verifying you, what's the phone number on the account?", True, False),
    ("Thanks — you're verified. Let me look at your card.", False, True),
    ("Your identity has been confirmed.", False, True),
    ("I wasn't able to verify your identity yet. Can you confirm your email?", True, False),
    ("I'll look into your rewards now.", False, False),
])
def test_text_labels(text, asks, verified):
    assert verify_probe.asks_for_field(text) is asks
    assert verify_probe.claims_verified(text) is verified


def test_next_action():
    assert verify_probe.next_action({"tool_calls": [{"name": "log_verification"}]}) == "retry_verification"
    assert verify_probe.next_action({"tool_calls": [{"name": "get_user_information_by_name"}]}) == "lookup"
    assert verify_probe.next_action({"content": "hi"}) == "text_only"


def test_disclosure_by_origin():
    before = [{"role": "user", "content": "My email is kenji.tanaka@outlook.com"},
              {"role": "assistant", "content": "For example: DOB 07/22/1985"}]
    d = verify_probe.disclosures("Is your DOB 07/22/1985, phone 206-555-0293, email kenji.tanaka@outlook.com?", RECORD, before)
    assert d == {"new": ["phone_number"], "repeat": ["date_of_birth"], "customer_stated": ["email"]}


def test_plan_shape_and_approval():
    assert PLAN["batch_id"] == "D005" and PLAN["budget_usd_total"] == 0.5 and PLAN["status"] == "frozen, not run"
    assert len(PLAN["cases"]) == 10 and len(PLAN["runs"]) == 30
    assert "run D005 with $0.50" in PLAN["approval"]
    assert all(c["task_id"].startswith("task_") for c in PLAN["cases"])


@needs_traces
def test_every_case_passes_reconstruction_and_its_feedback_reveals_no_stored_value():
    for spec in PLAN["cases"]:
        c = verify_probe.Case(spec)
        assert all(c.checks().values()), (spec["id"], c.checks())
        text = c.feedback()
        assert text.startswith("Not executed")
        for f in ("date_of_birth", "email", "phone_number"):
            assert c.record.get(f) and c.record[f] not in text
        msgs = c.messages()
        assert msgs[-len(c.proposal["tool_calls"]):][0]["role"] == "tool"


def test_a_mismatched_approval_sends_nothing(tmp_path):
    with pytest.raises(SystemExit, match="nothing was sent"):
        verify_probe.main([str(REPO_ROOT / "experiments" / "D005_plan.json"), "--approved-usd", "1.0",
                           "--out-dir", str(tmp_path)], send=ScriptedLLM({"agent": []}))
    assert not (tmp_path / "D005_runs").exists()


@needs_traces
def test_scripted_run_records_and_labels_every_reply(tmp_path):
    plan = dict(PLAN, runs=[r for r in PLAN["runs"] if r["case"] in ("V1", "V6")])
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    steps = [{"say": "Could you confirm your date of birth?"}, {"say": "You're verified now."}] * 3
    code = verify_probe.main([str(path), "--approved-usd", "0.5", "--out-dir", str(tmp_path)],
                             send=ScriptedLLM({"agent": steps}), prices=load_prices())
    out = json.loads((tmp_path / "D005_results.json").read_text())
    assert code == 0 and out["by_status"] == {"done": 6}
    assert [(r["asks_for_field_auto"], r["claims_verified_auto"]) for r in out["results"]] == [(True, False), (False, True)] * 3
    assert out["fidelity"]["tools_sent_equal_original_request"] is True
    assert all(len(r["ledger_calls"]) == 1 for r in out["results"])
    assert out["spend"]["accounting"] == "billed"
