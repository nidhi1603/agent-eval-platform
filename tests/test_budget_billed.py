"""'billed' budget accounting: calls are reserved conservatively, then settled at the provider-billed cost (cached
prompt tokens at the cached rate). H005 showed why it's needed: the upper-bound settlement cut off long, ~93%-cached
conversations whose billed cost was a fraction of the cap. $0."""

import time

import pytest

from bench import batch
from bench import budget as B

MINI = B.Price(0.25, 2.0, "test", cached_input_per_mtok=0.025)   # gpt-5-mini's recorded rates
EMB = B.Price(0.13, 0.0, "test")                                  # no cached rate (embeddings)


def _call(b, model, inp, out, cached=None, in_bound=None):
    c = b.reserve("chat", model, 1, in_bound or inp, out)
    usage = {"prompt_tokens": inp, "completion_tokens": out}
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    b.settle_ok(c, usage, model, time.perf_counter())
    return c


def test_billed_settles_cached_tokens_at_the_cached_rate_and_upper_bound_does_not():
    ub, billed = B.Budget(1.0, {"m": MINI}), B.Budget(1.0, {"m": MINI}, accounting="billed")
    for b in (ub, billed):
        _call(b, "m", 1_000_000, 1_000, cached=930_000)
    assert ub.summary()["enforced_usd"] == pytest.approx(0.25 + 0.002)
    assert billed.summary()["enforced_usd"] == pytest.approx(70_000 * 0.25e-6 + 930_000 * 0.025e-6 + 0.002)
    for b in (ub, billed):   # both figures are always reported, whatever is enforced
        s = b.summary()
        assert s["upper_bound_usd"] == pytest.approx(0.252) and s["billed_estimate_usd"] == pytest.approx(0.04275)


def test_the_h005_case_a_call_refused_under_upper_bound_is_admitted_when_billed():
    """task_058 (harness_v1): ~$0.77 upper bound spent, ~$0.22 billed; the next customer call reserved ~$0.30."""
    ub, billed = B.Budget(1.0, {"m": MINI}), B.Budget(1.0, {"m": MINI}, accounting="billed")
    for b in (ub, billed):
        _call(b, "m", 2_520_000, 70_000, cached=2_350_000)
    with pytest.raises(B.BudgetExceeded):
        ub.reserve("chat", "m", 1, 400_000, 100_000)
    billed.reserve("chat", "m", 1, 400_000, 100_000)


def test_billed_is_never_below_what_the_provider_bills_without_a_cached_report_or_rate():
    b = B.Budget(1.0, {"m": MINI, "e": EMB}, accounting="billed")
    _call(b, "m", 100_000, 0)                  # no cached-token report: full price
    _call(b, "e", 100_000, 0, cached=90_000)   # a model without a cached rate: full price
    assert b.summary()["enforced_usd"] == pytest.approx(100_000 * 0.25e-6 + 100_000 * 0.13e-6)


def test_reservations_and_unresolved_calls_stay_conservative_in_billed_mode():
    b = B.Budget(1.0, {"m": MINI}, accounting="billed")
    c = b.reserve("chat", "m", 1, 1_000_000, 16_384)
    assert c.reserved_usd == pytest.approx(0.25 + 16_384 * 2e-6)   # reserved at the full input price
    b.settle_unresolved(c, RuntimeError("timeout"), time.perf_counter())
    assert b.summary()["enforced_usd"] == pytest.approx(c.reserved_usd)


def test_unknown_accounting_is_refused():
    with pytest.raises(ValueError):
        B.Budget(1.0, {"m": MINI}, accounting="optimistic")


def test_the_batch_counts_what_each_run_enforced():
    assert batch._enforced({"spend_enforced_usd": 0.2, "spend_upper_bound_usd": 0.7}) == 0.2
    assert batch._enforced({"spend_upper_bound_usd": 0.7}) == 0.7      # older rows
    assert batch._enforced({"spend_enforced_usd": None, "spend_upper_bound_usd": 0.7}) == 0.7
