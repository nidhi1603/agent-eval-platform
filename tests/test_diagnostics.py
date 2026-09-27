"""Milestone/minefield diagnostics over the saved live traces. Zero-cost."""

import json

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import REPO_ROOT, diagnostics  # noqa: E402


@pytest.fixture(scope="module")
def types():
    return diagnostics._tool_types()


def _analyse(path, types):
    return diagnostics.analyse(json.loads((REPO_ROOT / path).read_text()), *types)


def test_the_two_fabricated_timestamps_are_the_only_observed_minefields(types):
    flagged = {}
    for p in diagnostics.live_traces():
        blocks = _analyse(p.relative_to(REPO_ROOT), types)["observed"]["minefield_would_block"]
        if blocks:
            flagged[str(p.relative_to(REPO_ROOT))] = [(b["i"], b["rule"]) for b in blocks]
    assert flagged == {"results/S002/task_089/trace.json": [(8, "verification_time_from_clock")],
                       "results/S003/task_087_baseline/trace.json": [(10, "verification_time_from_clock")]}
    assert len(diagnostics.live_traces()) == 19


def test_rewards_writes_are_checked_against_the_database_at_that_moment():
    t = json.loads((REPO_ROOT / "results/S003/task_019_denial_check_v1/trace.json").read_text())
    assert diagnostics.replay_rewards_writes(t, "task_019") == [{"i": 24, "allowed": False}, {"i": 26, "allowed": False}]


def test_official_reward_is_reported_unchanged_next_to_diagnostics(types):
    t = json.loads((REPO_ROOT / "results/S002/task_047/trace.json").read_text())
    row = diagnostics.analyse(t, *types)
    assert row["official_reward"] == t["evaluation"]["reward"]
    assert row["reference_actions_matched"] == "2/15"
    assert row["observed"]["discoverable_unlocked"] == ["apply_statement_credit_8472", "close_credit_card_account_7834"]
