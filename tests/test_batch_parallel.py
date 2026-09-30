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


def test_no_new_run_starts_after_the_provider_reports_no_credit(monkeypatch):
    def broke(item, settings, cap, out_dir):
        row = fake_run_one(item, settings, cap, out_dir)
        if item["task_id"] == "t1":
            row.update(status="interrupted_or_failed", attribution={"cause": "interrupted",
                       "evidence": "RateLimitError: You exceeded your current quota"})
        return row

    monkeypatch.setattr(batch, "_run_one", broke)
    out = batch.run_batch({**PLAN, "budget_usd_total": 10.0}, 10.0)
    statuses = [(r["task_id"], r["status"]) for r in out["results"]]
    assert statuses[:4] == [("t0", "finished"), ("t0", "finished"), ("t1", "interrupted_or_failed"), ("t1", "not_run")]
    assert all(r["reason"].startswith("stopped") for r in out["results"] if r["status"] == "not_run")


# ---- rate limits (bench/budget.py) -------------------------------------------------------------------------------

def test_a_rate_limit_waits_as_asked_and_is_not_counted_as_spend(monkeypatch):
    import litellm

    from bench import budget as b

    assert b.rate_limit_wait(Exception("Please try again in 3.152s."), 0) == pytest.approx(5.0)
    assert b.rate_limit_wait(Exception("Please try again in 20s."), 0) == pytest.approx(21.0)
    assert b.rate_limit_wait(Exception("no hint"), 5) == 60.0
    waits = []
    monkeypatch.setattr(b.time, "sleep", waits.append)
    calls = {"n": 0}

    def send(**kw):
        calls["n"] += 1
        if calls["n"] <= 4:  # more 429s than max_attempts: they must not use attempts up
            raise litellm.RateLimitError("Rate limit reached. Please try again in 2s.", "openai", "gpt-5-mini")
        return litellm.ModelResponse(model="gpt-5-mini", choices=[{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": "ok"}}],
                                     usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})

    budget = b.Budget(cap_usd=1.0, prices={"gpt-5-mini": b.Price(0.25, 2.0, "test")})
    completion = b.metered_completion(budget, b.Limits(max_attempts=2), send)
    completion(model="gpt-5-mini", messages=[{"role": "user", "content": "hi"}])
    assert calls["n"] == 5 and len(waits) == 4
    s = budget.summary()
    assert s["unresolved_reservations_usd"] == 0 and s["upper_bound_usd"] == s["usage_based_estimate_usd"]


def test_no_credit_is_not_waited_on(monkeypatch):
    import litellm

    from bench import budget as b

    monkeypatch.setattr(b.time, "sleep", lambda s: None)

    def send(**kw):
        raise litellm.RateLimitError("You exceeded your current quota (insufficient_quota)", "openai", "gpt-5-mini")

    budget = b.Budget(cap_usd=1.0, prices={"gpt-5-mini": b.Price(0.25, 2.0, "test")})
    with pytest.raises(litellm.RateLimitError):
        b.metered_completion(budget, b.Limits(), send)(model="gpt-5-mini", messages=[{"role": "user", "content": "x"}])
    assert len(budget.calls) == 1


def test_operator_stopped_runs_count_their_spend_but_may_rerun(tmp_path):
    journal = tmp_path / "j.jsonl"
    journal.write_text(json.dumps({"kind": "operator_stopped", "run_id": "x", "spend_upper_bound_usd": 0.4}) + "\n")
    out = batch.run_batch(PLAN, 1.0, journal=journal)
    assert out["spend_upper_bound_usd"] == pytest.approx(1.0) and out["by_status"]["finished"] == 3
    assert out["operator_stopped_runs"][0]["spend_upper_bound_usd"] == 0.4
