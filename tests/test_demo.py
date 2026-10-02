"""The reproducible demonstration (bench/demo.py) runs offline and its key claims hold. Zero cost."""

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import demo  # noqa: E402


def test_demo_reproduces_its_claims(capsys):
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "differs (unchanged tau2): True" in out and "with the local fix (listing_from_agent_state):       False" in out
    assert "User accounts retrieved successfully." in out
    assert "the recorded $100 write:            allowed=False  (missing_contract)" in out
    assert "$100 adding the Gold card's 0.025%: allowed=True" in out
    assert "No model was called" in out and "local criterion met=True" in out


def test_provenance_demo_reproduces_the_bug_and_the_fix():
    from bench import demo_provenance

    assert demo_provenance.main() == 0
