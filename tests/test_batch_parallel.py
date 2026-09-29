"""Parallel batches (bench/batch.py --workers): the allocation is never exceeded, and a journal resumes a batch.
Zero cost: _run_one is replaced by a fake that reports a fixed spend."""

import json

import pytest

from bench import batch

PLAN = {"batch_id": "T", "budget_usd_total": 1.0, "per_run_cap_usd": 0.3, "settings": {},
        "arms": {"a": {}, "b": {}}, "runs": [{"task_id": f"t{i}", "arm": arm, "attempt": 0}
                                             for i in range(4) for arm in ("a", "b")]}


def fake_run_one(item, settings, cap, out_dir):
    return {"task_id": item["task_id"], "arm": item["arm"], "attempt": item.get("attempt", 0), "status": "finished",
            "official_reward": 1.0 if item["arm"] == "b" else 0.0, "cap_given_usd": cap, "spend_upper_bound_usd": 0.2}


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(batch, "_run_one", fake_run_one)


def test_sequential_runs_stop_when_the_allocation_is_spent():
    out = batch.run_batch(PLAN, 1.0)
    assert out["by_status"] == {"finished": 5, "not_run": 3} and out["spend_upper_bound_usd"] == pytest.approx(1.0)


def test_parallel_needs_a_per_run_reservation():
    with pytest.raises(SystemExit):
        batch.run_batch({**PLAN, "per_run_cap_usd": None}, 1.0, workers=2)


def test_parallel_never_starts_a_run_the_unreserved_allocation_cannot_cover(monkeypatch):
    # thread pool stand-in: the fake is not picklable into a spawned process
    import concurrent.futures as cf
    import multiprocessing as mp

    monkeypatch.setattr(cf, "ProcessPoolExecutor", lambda max_workers, mp_context: cf.ThreadPoolExecutor(max_workers))
    monkeypatch.setattr(mp, "get_context", lambda kind: None)
    out = batch.run_batch(PLAN, 1.0, workers=3)
    finished = [r for r in out["results"] if r["status"] == "finished"]
    # each start needs 0.30 unreserved; each finished run costs 0.20: at most 4 can start within $1.00
    assert len(finished) == 4 and out["spend_upper_bound_usd"] <= 1.0 + 1e-9
    assert all(r["cap_given_usd"] == 0.3 for r in finished)
    assert out["by_status"]["not_run"] == 4 and [p["pair"] for p in out["pairs"]][:2] == ["improved", "improved"]


def test_a_journal_resumes_without_repeating_or_forgetting_spend(tmp_path):
    journal = tmp_path / "j.jsonl"
    journal.write_text(json.dumps(fake_run_one(PLAN["runs"][0], {}, 0.3, None)) + "\n")
    calls = []
    orig = batch._run_one

    def counting(item, *a):
        calls.append(item["task_id"] + item["arm"])
        return orig(item, *a)

    batch._run_one = counting
    out = batch.run_batch(PLAN, 1.0, journal=journal)
    assert "t0a" not in calls  # the journaled run is not repeated
    assert out["spend_upper_bound_usd"] == pytest.approx(1.0)  # its spend still counts
    assert len(journal.read_text().splitlines()) == 1 + len(calls)
