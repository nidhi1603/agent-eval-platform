"""Agents a trial pod can run. Each takes the TrialSpec dict and returns a result dict.

The stub agents exercise the platform without calling an LLM. Their results are NOT benchmark
results and must never be reported as such. The fault-injection stubs exist to demonstrate
recovery on a real cluster (see scripts/failure_demo.sh).
"""

import hashlib
import os
import time
from collections.abc import Callable


def stub_agent(spec: dict) -> dict:
    """Deterministic: success is a fixed pseudo-random function of (task_id, trial_index)."""
    digest = hashlib.sha256(f"{spec['task_id']}:{spec['trial_index']}".encode()).digest()
    time.sleep(1 + digest[0] % 3)
    return {
        "reward": 1.0 if digest[1] < 154 else 0.0,  # ~60% success
        "cost_usd": 0.0,
        "n_turns": 3 + digest[2] % 10,
    }


def stub_crash_first_attempt(spec: dict) -> dict:
    """Simulates a worker crash: attempt 1 dies abruptly without reporting; later attempts succeed."""
    if spec["attempt"] == 1:
        os._exit(137)  # no exception handling, no callback, like an OOM kill
    return stub_agent(spec)


def stub_hang(spec: dict) -> dict:
    """Simulates an agent that never finishes, so the Job's deadline expires."""
    time.sleep(3600)
    return stub_agent(spec)


AGENTS: dict[str, Callable[[dict], dict]] = {
    "stub": stub_agent,
    "stub-crash-first-attempt": stub_crash_first_attempt,
    "stub-hang": stub_hang,
}
