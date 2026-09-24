"""Reliability metrics.

pass^k (tau-bench): the probability that an agent succeeds on ALL k independent attempts
at a task. With n completed trials of which c succeeded, the unbiased estimate is
C(c, k) / C(n, k); the run-level score is the mean over tasks.
Contrast pass@k (succeeds at least once), which rewards lucky retries.
"""

from collections import defaultdict
from collections.abc import Iterable
from math import comb

SUCCESS_THRESHOLD = 1.0 - 1e-6  # tau-bench counts a trial as solved only at reward == 1


def pass_hat_k(n: int, c: int, k: int) -> float:
    if not 0 <= c <= n:
        raise ValueError(f"need 0 <= c <= n, got c={c}, n={n}")
    if k < 1 or k > n:
        raise ValueError(f"need 1 <= k <= n, got k={k}, n={n}")
    return comb(c, k) / comb(n, k)


def run_pass_hat_k(trials: Iterable[tuple[str, float | None]], k: int) -> float | None:
    """trials: (task_id, reward) for completed trials. Tasks with fewer than k trials are skipped."""
    per_task: dict[str, list[bool]] = defaultdict(list)
    for task_id, reward in trials:
        per_task[task_id].append(reward is not None and reward >= SUCCESS_THRESHOLD)

    scores = [pass_hat_k(len(r), sum(r), k) for r in per_task.values() if len(r) >= k]
    return sum(scores) / len(scores) if scores else None
