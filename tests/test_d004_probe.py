"""D004: next-message probe of the transfer-hold feedback (bench/hold_probe.py). $0: scripted model, no network."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, harness, hold_probe  # noqa: E402
from bench.budget import load_prices  # noqa: E402
from bench.scripted import ScriptedLLM  # noqa: E402

PLAN = json.loads((REPO_ROOT / "experiments" / "D004_plan.json").read_text())
HAVE_TRACES = all((REPO_ROOT / c["source_trace"]).is_file() for c in PLAN["cases"])
needs_traces = pytest.mark.skipif(not HAVE_TRACES, reason="the H004 traces are local (runs/ is not committed)")


@pytest.mark.parametrize("reply,label", [
    ({"content": None, "tool_calls": [{"name": "transfer_to_human_agents"}]}, "transfer_again"),
    ({"content": None, "tool_calls": [{"name": "KB_search"}, {"name": "transfer_to_human_agents"}]}, "transfer_again"),
    ({"content": None, "tool_calls": [{"name": "KB_search_bm25"}]}, "retrieval"),
    ({"content": None, "tool_calls": [{"name": "get_debit_cards_by_account_id_7823"}]}, "other_tool"),
    ({"content": "Done — I've transferred you to a human specialist."}, "claims_transfer"),
    ({"content": "I'm connecting you to our security team now."}, "claims_transfer"),
    ({"content": "Could you tell me the date of the charge?"}, "other_text")])
def test_labels(reply, label):
    assert hold_probe.classify(reply) == label


def test_plan_shape_and_approval():
    assert len(PLAN["cases"]) == 9 and len(PLAN["runs"]) == 54
    assert {(r["case"], r["arm"], r["sample"]) for r in PLAN["runs"]} == {
        (c["id"], a, s) for c in PLAN["cases"] for a in hold_probe.ARMS for s in range(3)}
    pairs = [PLAN["runs"][i:i + 2] for i in range(0, 54, 2)]
    assert all(p[0]["case"] == p[1]["case"] and p[0]["sample"] == p[1]["sample"] and p[0]["arm"] != p[1]["arm"] for p in pairs)
    assert sum(p[0]["arm"] == "A_v1_text" for p in pairs) in (13, 14)
    assert PLAN["budget_usd_total"] == 1.0 and "run D004 with $1.00" in PLAN["approval"]
    assert PLAN["settings"]["budget_accounting"] == "billed" and PLAN["settings"]["agent_model"] == "gpt-5-mini"


@needs_traces
def test_reconstruction_is_exact_and_the_arms_differ_only_in_the_held_calls_result():
    manifest, cases = hold_probe.preflight(PLAN, 1.0)
    for cid, c in cases.items():
        assert all(c.checks().values()), cid
        a, b = c.messages("A_v1_text"), c.messages("B_v3_1_text")
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        assert len(a) == len(b) and len(diff) == 1 and a[diff[0]]["tool_call_id"] == c.transfer_id, cid
        assert b[diff[0]]["content"].startswith(harness.TRANSFER_NOT_EXECUTED)
        assert b[diff[0]]["content"].endswith(harness.TRANSFER_STILL_OPEN)
        assert manifest["feedback_texts"][cid]["A_v1_text"] == a[diff[0]]["content"]


@needs_traces
def test_a_mismatched_approval_sends_nothing(tmp_path):
    with pytest.raises(SystemExit, match="nothing was sent"):
        hold_probe.main([str(REPO_ROOT / "experiments" / "D004_plan.json"), "--approved-usd", "0.5",
                         "--out-dir", str(tmp_path)], send=ScriptedLLM({"agent": []}))
    assert not (tmp_path / "D004_runs").exists()


@needs_traces
def test_scripted_run_records_and_labels_every_reply(tmp_path):
    plan = dict(PLAN, runs=[r for r in PLAN["runs"] if r["case"] in ("C5", "C7")])   # the two shortest histories
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    steps = [{"say": "I'm transferring you now."}, {"call": "transfer_to_human_agents", "args": {"summary": "s"}},
             {"call": "KB_search", "args": {"query": "q"}}, {"say": "Could you confirm the card?"}] * 3
    code = hold_probe.main([str(path), "--approved-usd", "1.0", "--out-dir", str(tmp_path)],
                           send=ScriptedLLM({"agent": steps}), prices=load_prices())
    out = json.loads((tmp_path / "D004_results.json").read_text())
    assert code == 0 and out["by_status"] == {"done": 12}
    assert [r["label"] for r in out["results"]] == ["claims_transfer", "transfer_again", "retrieval", "other_text"] * 3
    assert sum(v["samples"] for v in out["labels"].values()) == 12
    assert all(len(r["ledger_calls"]) == 1 for r in out["results"])        # one paid call per run, metered
    assert (tmp_path / "D004_runs" / "manifest.json").is_file() and (tmp_path / "D004_runs" / "ledger.jsonl").is_file()
    assert out["spend"]["accounting"] == "billed"
