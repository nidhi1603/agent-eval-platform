"""Agent instruction variants and paired batches. Zero-cost: scripted models only."""

import hashlib

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import agent, batch, variants  # noqa: E402
from tests.test_bench import scripted_run  # noqa: E402

VARIANT = "denial_check_v1"


def test_variant_text_is_frozen_and_recorded():
    rec = variants.record(VARIANT)
    assert rec["sha256"] == hashlib.sha256(variants.text(VARIANT).encode()).hexdigest()
    assert variants.record("baseline") == {"name": "baseline", "file": None, "sha256": None, "chars": 0}
    assert variants.apply("POLICY", "baseline") == "POLICY"
    assert variants.apply("POLICY", VARIANT).startswith("POLICY\n\n## Before telling the customer")
    with pytest.raises(ValueError):
        variants.text("no_such_variant")


def test_variant_run_passes_the_integrity_gate_and_is_disclosed(tmp_path):
    base, _ = scripted_run(tmp_path / "b")
    var, _ = scripted_run(tmp_path / "v", agent_variant=VARIANT)
    for t in (base, var):
        assert t["agent_inputs"]["passed"] and t["agent_inputs"]["variant_applied_as_recorded"]
        assert t["agent_inputs"]["system_prompt_identical_without_answer_key"]
    assert var["config"]["agent"]["variant"]["sha256"] == variants.record(VARIANT)["sha256"]
    assert var["agent_inputs"]["system_prompt_sha256"] != base["agent_inputs"]["system_prompt_sha256"]
    assert var["agent_inputs"]["system_prompt_chars"] - base["agent_inputs"]["system_prompt_chars"] >= variants.record(VARIANT)["chars"]
    assert any("agent instruction variant" in f for f in var["research_eligibility"]["flags"])
    assert not any("agent instruction variant" in f for f in base["research_eligibility"]["flags"])
    # same scripted conversation, same official grade: the variant changes only the instructions
    assert var["evaluation"]["reward"] == base["evaluation"]["reward"] == 1.0


def test_unknown_variant_is_refused_before_anything_is_built():
    with pytest.raises(ValueError):
        agent.register("no_such_variant")


def test_paired_batch_runs_each_arm_and_keeps_incomplete_pairs(monkeypatch, tmp_path):
    seen = []

    def fake_run(opts):
        seen.append((opts.task_id, opts.agent_variant, opts.budget_usd))
        spent = min(0.2, opts.budget_usd)
        reward = 1.0 if (opts.task_id, opts.agent_variant) in {("a", VARIANT), ("b", "baseline"), ("b", VARIANT)} else 0.0
        trace = {"run_id": f"{opts.task_id}-{opts.agent_variant}", "execution": {"finished": spent == 0.2},
                 "evaluation": {"reward": reward}, "spend": {"incurred": {"upper_bound_usd": spent}}, "persisted": True,
                 "config": {"agent": {"variant": variants.record(opts.agent_variant)}},
                 "answer_independence": {"conclusive": True, "agent_visible_outputs_depending_on_hidden_reference": []}}
        return trace, tmp_path / "t.json"

    monkeypatch.setattr(batch, "run", fake_run)
    plan = {"batch_id": "P", "budget_usd_total": 1.0,
            "settings": {"agent_model": "m", "agent_args": {}, "user_model": "u", "user_args": {},
                         "retrieval_config": "bm25", "seed": 300, "max_steps": 200},
            "arms": {"baseline": {"agent_variant": "baseline"}, VARIANT: {"agent_variant": VARIANT}},
            "runs": [{"task_id": "a", "arm": "baseline"}, {"task_id": "a", "arm": VARIANT},
                     {"task_id": "b", "arm": VARIANT}, {"task_id": "b", "arm": "baseline"},
                     {"task_id": "c", "arm": "baseline"}, {"task_id": "c", "arm": VARIANT}]}
    summary = batch.run_batch(plan, 1.0)
    assert [(t, v) for t, v, _ in seen] == [("a", "baseline"), ("a", VARIANT), ("b", VARIANT), ("b", "baseline"),
                                            ("c", "baseline")]  # order as planned; c's second arm cannot be admitted
    pairs = {p["task_id"]: p["pair"] for p in summary["pairs"]}
    assert pairs == {"a": "improved", "b": "both pass", "c": "incomplete pair"}
    assert [r["status"] for r in summary["results"]][-1] == "not_run"  # reported, not dropped
    with pytest.raises(SystemExit):
        batch.run_batch({**plan, "runs": [{"task_id": "a", "arm": "nope"}]}, 1.0)


def test_blind_export_hides_the_arm(tmp_path):
    import json
    import random

    from bench import blind_export

    trace, run_dir = scripted_run(tmp_path / "v", agent_variant=VARIANT)
    path = run_dir / "trace.json"
    results = {"batch_id": "X", "results": [{"task_id": "task_015", "arm": VARIANT, "run_id": trace["run_id"],
                                             "trace": str(path)}]}
    key = blind_export.export(results, tmp_path / "blind", rng=random.Random(0))
    (code, entry), = key.items()
    text = (tmp_path / "blind" / f"conv_{code}.md").read_text()
    assert entry["arm"] == VARIANT
    for hidden in (VARIANT, "denial_check", trace["run_id"], "reward_basis", "official_reward", "Before telling the customer"):
        assert hidden not in text
    assert "CALL " in text and json.dumps(trace["config"]) not in text


def test_worked_example_is_derived_from_a_real_execution():
    from bench import discovery_example as ex

    frozen = variants.text("discovery_example_v2")
    assert frozen.strip() == ex.build().strip()  # the frozen file is exactly a fresh build
    real_unlock, real_call = ex.real_outputs()
    for real in (real_unlock, real_call):
        assert ex.neutralize(real).strip() in frozen  # the shown outputs are the real ones, renamed
        assert ex.restore(ex.neutralize(real)) == real  # and the renaming is reversible
    assert "7291" not in frozen and "c7d8e9f0a1" not in frozen  # no real tool name or customer id


def test_combined_variant_is_exactly_interface_plus_example():
    both = variants.text("discovery_both_v2")
    assert both == variants.text("discovery_interface_v2").rstrip() + "\n\n" + variants.text("discovery_example_v2")
