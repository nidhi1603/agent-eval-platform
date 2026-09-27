"""Answer-dependence audit and the local listing fix. Zero-cost: no model calls."""

import functools
import hashlib
import json
import random

import pytest

import bench  # noqa: F401 - must precede any tau2 import: it sets TAU2_DATA_DIR

pytest.importorskip("tau2", reason="install the bench extra: uv sync --extra bench")

from bench import audit, fixes, pins  # noqa: E402
from bench.independence import blind_copy, fresh_env  # noqa: E402

READ_TOOL, READ_ARGS = "get_all_user_accounts_by_user_id_3847", '{"user_id": "f7d3a82c91"}'  # in task_085's reference


@pytest.fixture(scope="module")
def config():
    from tau2.data_model.simulation import TextRunConfig

    return TextRunConfig(domain="banking_knowledge", retrieval_config="bm25")


@pytest.fixture(scope="module")
def task_085():
    from tau2.runner.helpers import get_tasks

    return get_tasks("banking_knowledge", task_ids=["task_085"])[0]


def _read_then_list(env):
    from tau2.data_model.message import ToolCall

    def call(name, args):
        return env.get_response(ToolCall(id="x", name=name, arguments=args, requestor="assistant")).content

    call("unlock_discoverable_agent_tool", {"agent_tool_name": READ_TOOL})
    call("call_discoverable_agent_tool", {"agent_tool_name": READ_TOOL, "arguments": READ_ARGS})
    return call("list_discoverable_agent_tools", {})


def _db_hash(env):
    return hashlib.sha256(env.tools.db.model_dump_json().encode()).hexdigest()


def test_reproducer_leaky_listing_depends_on_the_answer_key(config, task_085):
    real, blind = fresh_env(config, task_085), fresh_env(config, blind_copy(task_085))
    assert _read_then_list(real) != _read_then_list(blind)


def test_standalone_reproducer_detects_the_defect():
    import importlib.util

    spec = importlib.util.spec_from_file_location("repro", pins.REPO_ROOT / "repro" / "tau2_listing_allowlist.py")
    repro = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repro)
    assert repro.main() == 1  # tau2-only reproducer: listings differ when only read_log_allowlist changes


def test_fix_removes_the_dependency_and_leaves_grading_state_and_schemas_unchanged(config, task_085):
    before = fresh_env(config, task_085)
    listing_before = _read_then_list(before)
    schemas_before = json.dumps([t.openai_schema for t in before.get_tools()], sort_keys=True)
    with fixes.listing_from_agent_state():
        real, blind = fresh_env(config, task_085), fresh_env(config, blind_copy(task_085))
        assert _read_then_list(real) == _read_then_list(blind)  # no longer answer-dependent
        assert _db_hash(real) == _db_hash(before)  # evaluation log / DB state identical to the unchanged env
        assert json.dumps([t.openai_schema for t in real.get_tools()], sort_keys=True) == schemas_before
    assert _read_then_list(fresh_env(config, task_085)) == listing_before  # the patch is fully undone on exit


def test_audit_flags_only_the_listing_on_the_leaky_env_and_nothing_when_fixed(config, task_085):
    leaky = audit.audit_task(config, task_085, "R")
    assert leaky["answer_dependent"] and {d["tool"] for d in leaky["answer_dependent"]} == {"list_discoverable_agent_tools"}
    with fixes.listing_from_agent_state():
        fixed = audit.audit_task(config, task_085, "R")
    assert fixed["answer_dependent"] == [] and fixed["conclusive"]
    assert fixed["calls"] == leaky["calls"]  # the same calls and states were exercised


def test_reference_free_probes_do_not_flag(config, task_085):
    result = audit.audit_task(config, task_085, "F")
    assert result["answer_dependent"] == [] and result["conclusive"]


def test_harmless_nondeterminism_is_inconclusive_not_a_leak(config, task_085, monkeypatch):
    from tau2.domains.banking_knowledge.tools import KnowledgeTools

    original = KnowledgeTools.get_current_time

    @functools.wraps(original)
    def jittery_time(self):
        return f"{original(self)} (jitter {random.random():.6f})"

    monkeypatch.setattr(KnowledgeTools, "get_current_time", jittery_time)
    result = audit.audit_task(config, task_085, "F")
    assert [d["tool"] for d in result["nondeterministic"]] == ["get_current_time"]
    assert result["answer_dependent"] == [] and result["conclusive"] is False


def test_full_dev_audit_on_fixed_env_is_clean_and_never_touches_held_out_tasks():
    result = audit.run_audit(fixed=True)
    ids = {r["task_id"] for r in result["rows"]}
    split = pins.load_split()
    assert ids == set(split["dev"]) and not ids & set(split["test"])
    summary = audit.summarize(result)
    assert summary["tasks_flagged"] == [] and summary["totals"]["R_nondeterministic_calls"] == 0
