import pytest

from app.metrics import pass_hat_k, run_pass_hat_k


def test_pass_hat_k_basics():
    assert pass_hat_k(4, 4, 4) == 1.0
    assert pass_hat_k(4, 3, 4) == 0.0  # one failure means not all 4 succeed
    assert pass_hat_k(4, 2, 1) == 0.5
    assert pass_hat_k(4, 3, 2) == pytest.approx(3 / 6)  # C(3,2)/C(4,2)


def test_pass_hat_k_is_non_increasing_in_k():
    vals = [pass_hat_k(8, 6, k) for k in range(1, 9)]
    assert vals == sorted(vals, reverse=True)


def test_pass_hat_k_rejects_bad_input():
    with pytest.raises(ValueError):
        pass_hat_k(3, 4, 1)
    with pytest.raises(ValueError):
        pass_hat_k(3, 1, 4)


def test_run_level_mean_over_tasks_and_skips_short_tasks():
    trials = [("a", 1.0), ("a", 1.0), ("b", 1.0), ("b", 0.0), ("c", 1.0)]  # c has only 1 trial
    assert run_pass_hat_k(trials, 1) == pytest.approx((1.0 + 0.5 + 1.0) / 3)
    assert run_pass_hat_k(trials, 2) == pytest.approx((1.0 + 0.0) / 2)
    assert run_pass_hat_k([], 1) is None


def test_partial_reward_is_not_success():
    assert run_pass_hat_k([("a", 0.99)], 1) == 0.0
