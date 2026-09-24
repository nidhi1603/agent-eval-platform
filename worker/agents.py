"""Agents a trial pod can run. Each takes the TrialSpec dict and returns a result dict."""

import hashlib
import time
from collections.abc import Callable


def stub_agent(spec: dict) -> dict:
    """Deterministic placeholder that exercises the platform end to end without calling an LLM.

    Success is a fixed pseudo-random function of (task_id, trial_index), so reruns reproduce.
    It is NOT a benchmark result and must never be reported as one.
    """
    digest = hashlib.sha256(f"{spec['task_id']}:{spec['trial_index']}".encode()).digest()
    time.sleep(1 + digest[0] % 3)
    return {
        "reward": 1.0 if digest[1] < 154 else 0.0,  # ~60% success
        "cost_usd": 0.0,
        "n_turns": 3 + digest[2] % 10,
    }


AGENTS: dict[str, Callable[[dict], dict]] = {"stub": stub_agent}
