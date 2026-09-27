"""Run one banking development task locally and save a structured trace.

    # zero cost: scripted model responses through the real tau2 path (trace is labelled MOCK)
    uv run --extra bench python -m bench.run --task task_015 --retrieval-config bm25 \
        --scripted bench/scripts/task_015_reference.json

    # live: needs an approved --budget-usd, recorded prices in bench/prices.json, and a key in .env
    uv run --extra bench python -m bench.run --task task_015 --retrieval-config bm25 \
        --agent-model MODEL --budget-usd 1.00

Files in runs/local/<run_id>/ (run_id is unique; the directory is created exclusively):
    manifest.json   written first, before any benchmark code or network call; state updated at the end
    ledger.jsonl    append-only, fsync'd: every reservation before its request, every settlement after
    trace.json      the full trace, written at the end (trace_error.json if writing it fails)
    repo.diff       uncommitted changes to tracked files, when the working tree is dirty
    simulation.json tau2's own SimulationRun, when the simulation returned
    tau2.log        tau2's debug log
A process killed with SIGKILL leaves manifest.json (state "started") and ledger.jsonl.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT, agent, pins
from bench.budget import Budget, Limits, check_llm_args, install, load_prices, metered_embedder, role
from bench.trace import (
    SCHEMA_VERSION,
    SIDE_CHANNEL_TOOL,
    ConfigError,
    attribute,
    missing_fields,
    models_observed,
    research_eligibility,
    retrievals,
    serialize_messages,
    tool_calls,
)

OFFICIAL_NOTE = (
    "Official protocol (docs/leaderboard-submission.md, arXiv 2603.04370): all 97 tasks, 4 trials, "
    "retrieval_config=alltools, user simulator gpt-5.2 with reasoning_effort=low, seed 300. A single "
    "development task is an integration smoke test, never a baseline estimate or a leaderboard comparison."
)
OFFICIAL_USER_MODEL = "gpt-5.2"
OFFICIAL_USER_ARGS = {"reasoning_effort": "low"}


@dataclass
class RunOptions:
    task_id: str
    agent_model: str
    user_model: str = OFFICIAL_USER_MODEL
    agent_llm_args: dict = field(default_factory=lambda: {"temperature": 0.0})
    user_llm_args: dict = field(default_factory=lambda: dict(OFFICIAL_USER_ARGS))
    retrieval_config: str = "alltools"
    max_steps: int = 200  # tau2 default; counts every message, not only agent turns
    max_errors: int = 10
    seed: int = 300
    timeout_s: float | None = 1200.0
    budget_usd: float | None = None
    limits: Limits = field(default_factory=Limits)
    scripted: Path | None = None
    out_dir: Path = REPO_ROOT / "runs" / "local"
    env_fixes: tuple[str, ...] = ()  # opt-in environment changes (bench/fixes.py); disclosed in every trace
    agent_variant: str = "baseline"  # harness instruction variant (bench/variants/); recorded with its sha256


def run(opts: RunOptions) -> tuple[dict, Path]:
    mode = "mock" if opts.scripted else "live"
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%S}Z_{opts.task_id}_{mode}_{uuid.uuid4().hex[:8]}"
    run_dir = opts.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)  # never share or overwrite another run's directory

    trace: dict = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "mode": mode,
                   "started_at": started.isoformat(), "messages": []}
    budget = orchestrator = simulation = log_sink = None
    error: BaseException | None = None
    t0 = time.perf_counter()
    try:
        trace["label"] = ("MOCK: scripted model responses and fake embeddings. Tests the harness; NOT a benchmark result."
                          if opts.scripted else
                          "LIVE development smoke test: one dev-split task, one trial. Not a baseline estimate "
                          "and not a leaderboard comparison.")
        trace["config"] = _config_record(opts)
        trace["protocol_note"] = OFFICIAL_NOTE
        trace["provenance"] = _provenance(opts, run_dir)
        _write_json(run_dir / "manifest.json", {**{k: trace[k] for k in (
            "schema_version", "run_id", "mode", "started_at", "label", "config", "provenance")},
            "state": "started", "pid": os.getpid()})
        log_sink = _capture_tau2_logs(run_dir)

        import litellm

        litellm.suppress_debug_info = True  # tau2's cost lookup fails loudly for scripted model names
        trace["benchmark"] = pins.verify_benchmark()
        split = pins.load_split()
        if opts.task_id not in split["dev"]:
            where = "test split (held out)" if opts.task_id in split["test"] else "neither split"
            raise ConfigError(f"{opts.task_id} is in the {where}; local runs are restricted to dev tasks")
        if opts.retrieval_config in agent.FORBIDDEN_RETRIEVAL_CONFIGS:
            raise ConfigError(f"retrieval_config={opts.retrieval_config} gives the agent task-specific documents")
        check_llm_args(opts.agent_llm_args, "agent")
        check_llm_args(opts.user_llm_args, "user simulator")

        budget, send, embedder_cls = _prepare_spending(opts, run_dir / "ledger.jsonl")
        trace["budget"] = {"cap_usd": budget.cap_usd, "limits": asdict(opts.limits),
                           "mechanism": "estimated spend admission control (bench/budget.py), not a guarantee"}

        from tau2.data_model.simulation import TextRunConfig
        from tau2.runner.build import _build_env_kwargs, build_text_orchestrator
        from tau2.runner.helpers import get_tasks
        from tau2.runner.simulation import run_simulation

        from bench import independence

        agent_name = agent.register(opts.agent_variant)
        task = get_tasks(pins.DOMAIN, task_ids=[opts.task_id])[0]
        trace["task"] = {"id": task.id, "split": "dev",
                         "reward_basis": [str(b.value) for b in task.evaluation_criteria.reward_basis],
                         "sha256": _sha256(pins.tasks_dir() / f"{task.id}.json")}
        config = TextRunConfig(
            domain=pins.DOMAIN, agent=agent_name,
            llm_agent=opts.agent_model, llm_args_agent=dict(opts.agent_llm_args),
            llm_user=opts.user_model, llm_args_user=dict(opts.user_llm_args),
            max_steps=opts.max_steps, max_errors=opts.max_errors, seed=opts.seed, timeout=opts.timeout_s,
            retrieval_config=opts.retrieval_config,
        )
        from contextlib import ExitStack

        from bench import fixes

        unknown = set(opts.env_fixes) - {fixes.FIX_NAME}
        if unknown:
            raise ConfigError(f"unknown env_fixes {sorted(unknown)}")
        with ExitStack() as env_stack, install(budget, opts.limits, send=send, embedder_cls=embedder_cls):
            if fixes.FIX_NAME in opts.env_fixes:
                env_stack.enter_context(fixes.listing_from_agent_state())
            with role("environment_setup"):  # a fresh environment (fresh DB) is built for every run
                orchestrator = build_text_orchestrator(config, task, seed=opts.seed)
            trace["agent_inputs"] = _audit_agent_inputs(orchestrator, task, config, opts.agent_variant)
            if not trace["agent_inputs"]["passed"]:
                raise ConfigError("agent input integrity check failed; see agent_inputs")
            with role("environment"):  # tool calls and grading replays; agent/user/grader tag themselves
                simulation = run_simulation(orchestrator, env_kwargs=_build_env_kwargs(config, task) or None)
            # A post-run diagnostic. Its failure must not turn a finished, graded trial into a failed one;
            # it can be rerun later from the saved trajectory (python -m bench.independence <run_dir>).
            try:
                with role("independence_check"):
                    trace["answer_independence"] = independence.check(config, task, simulation.messages)
            except Exception as e:  # noqa: BLE001
                trace["answer_independence"] = {"error": f"{type(e).__name__}: {e}"[:500], "conclusive": False}
    except BaseException as e:  # noqa: BLE001 - leave a trace on every exit path this process controls
        error = e
    finally:
        path = _finalize(trace, run_dir, simulation, orchestrator, budget, error, t0)
        if log_sink is not None:
            _release_tau2_logs(log_sink)
    if isinstance(error, KeyboardInterrupt):
        raise error
    return trace, path


def _finalize(trace, run_dir, simulation, orchestrator, budget, error, t0) -> Path:
    path = run_dir / "trace.json"
    try:
        trace.update(_result_record(simulation, orchestrator, error))
        trace["spend"] = _spend_record(simulation, budget)
        trace["attribution"] = attribute(trace["termination_reason"], (trace.get("evaluation") or {}).get("reward"),
                                         error, trace["messages"], trace["spend"]["ledger"])
        trace["finished_at"] = datetime.now(timezone.utc).isoformat()
        trace["duration_s"] = round(time.perf_counter() - t0, 2)
        trace["missing_fields"] = missing_fields(trace)
        trace["trace_complete"] = not trace["missing_fields"]
        trace["research_eligibility"] = research_eligibility(trace)
        if error is not None:
            trace["error_traceback"] = "".join(traceback.format_exception(error))[-4000:]
        trace["persisted"] = True  # set before writing: the file on disk exists only if the write succeeds
        path.write_text(json.dumps(trace, indent=2, default=str))
        if simulation is not None:
            (run_dir / "simulation.json").write_text(simulation.model_dump_json(indent=2))
        state = "finalized"
    except Exception as e:  # noqa: BLE001 - record the finalization failure itself
        path = run_dir / "trace_error.json"
        _write_json(path, {"run_id": trace.get("run_id"), "finalization_error": repr(e),
                           "traceback": traceback.format_exc()[-4000:],
                           "run_error": repr(error) if error else None})
        trace["persisted"] = False
        state = "finalization_failed"
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text())
        _write_json(run_dir / "manifest.json", {**manifest, "state": state, "finished_at": trace.get("finished_at")})
    except Exception:  # noqa: BLE001 - the manifest may not exist if setup failed very early
        pass
    return path


def _config_record(opts: RunOptions) -> dict:
    return {
        "domain": pins.DOMAIN,
        "task_id": opts.task_id,
        "agent": {"implementation": ("tau2 LLMAgent, unmodified prompt" if opts.agent_variant == "baseline" else
                                     f"tau2 LLMAgent + frozen instruction variant {opts.agent_variant!r} appended to the policy"),
                  "variant": _variant_record(opts.agent_variant),
                  "model_requested": opts.agent_model, "llm_args": opts.agent_llm_args},
        "user_simulator": {"implementation": "tau2 user_simulator", "model_requested": opts.user_model,
                           "llm_args": opts.user_llm_args},
        "retrieval_config": opts.retrieval_config,
        "max_steps": opts.max_steps,
        "max_errors": opts.max_errors,
        "seed": opts.seed,
        "seed_note": "tau2 sends this seed to both LLMs; providers treat it as best-effort, so runs can differ",
        "timeout_s": opts.timeout_s,
        "budget_usd": opts.budget_usd,
        "limits": asdict(opts.limits),
        "scripted": str(opts.scripted) if opts.scripted else None,
        "environment_patches": list(opts.env_fixes),  # non-empty = modified benchmark environment
        "evaluation": "tau2 evaluate_simulation, EvaluationType.ALL (reward = product over the task's reward_basis)",
    }


def _variant_record(name: str) -> dict:
    from bench import variants

    return variants.record(name)


def _provenance(opts: RunOptions, run_dir: Path) -> dict:
    prov = pins.provenance()
    files = [*(REPO_ROOT / "bench").glob("*.py"), REPO_ROOT / "bench" / "prices.json", REPO_ROOT / "uv.lock",
             pins.SPLIT_FILE, *([Path(opts.scripted).resolve()] if opts.scripted else [])]
    prov["file_sha256"] = {
        str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p): _sha256(p)
        for p in sorted(f.resolve() for f in files) if p.exists()}
    if prov.get("repo_dirty"):
        diff = subprocess.run(["git", "diff", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
        (run_dir / "repo.diff").write_text(diff)
        prov["repo_diff_sha256"] = hashlib.sha256(diff.encode()).hexdigest()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "bench"], cwd=REPO_ROOT,
                               capture_output=True, text=True).stdout.split()
    prov["untracked_bench_files"] = untracked  # hashed above if they are .py files in bench/
    return prov


def _prepare_spending(opts: RunOptions, journal: Path):
    if opts.scripted:
        from bench.scripted import FAKE_PRICES, FakeEmbedder, ScriptedLLM

        _isolate_embedding_cache(Path(tempfile.mkdtemp(prefix="aep-mock-embeddings-")))
        budget = Budget(opts.budget_usd if opts.budget_usd is not None else 1.0, FAKE_PRICES, journal)
        return budget, ScriptedLLM.from_file(opts.scripted), FakeEmbedder

    if opts.budget_usd is None:
        raise ConfigError("live runs need an explicitly approved --budget-usd")
    import litellm
    from dotenv import load_dotenv
    from tau2.knowledge.embedders.openai_embedder import OpenAIEmbedder

    load_dotenv(REPO_ROOT / ".env", override=False)
    budget = Budget(opts.budget_usd, load_prices(), journal)
    needed = {opts.agent_model, opts.user_model}
    if opts.retrieval_config.startswith("alltools") or "openai_embeddings" in opts.retrieval_config:
        needed.add("text-embedding-3-large")
    for model in sorted(needed):
        budget.price(model)  # raises PriceMissing before anything is sent
    for model in (opts.agent_model, opts.user_model):
        env = litellm.validate_environment(model=model)
        if not env.get("keys_in_environment"):
            raise ConfigError(f"missing credentials for {model}: set {env.get('missing_keys')} in .env")
    _isolate_embedding_cache(Path.home() / ".cache" / "agent-eval-platform" / "embeddings")
    return budget, None, metered_embedder(budget, opts.limits, OpenAIEmbedder)


def _isolate_embedding_cache(cache_dir: Path) -> None:
    """tau2 caches document embeddings under ./data. Keep mock and live vectors in separate places."""
    from tau2.knowledge import embeddings_cache

    embeddings_cache._global_cache = embeddings_cache.EmbeddingsCache(cache_dir=str(cache_dir))


def _audit_agent_inputs(orchestrator, task, config, variant: str = "baseline") -> dict:
    """Gate: the agent was built without the task, and its complete system prompt and tool schemas are
    byte-identical to an agent built from a copy of the task with the answer key emptied (reference
    actions, NL assertions, communicate info, required documents). The string scan is a diagnostic."""
    from tau2.data_model.tasks import Task

    from bench import independence, variants

    from tau2.agent.llm_agent import LLMAgent

    a = orchestrator.agent
    schemas = [t.openai_schema for t in a.tools]
    blind_env = independence.fresh_env(config, independence.blind_copy(task))
    blind_agent = LLMAgent(tools=blind_env.get_tools(), llm=a.llm,
                           domain_policy=variants.apply(blind_env.get_policy(), variant))
    # the variant's text is present exactly when a variant is used, and the official policy is otherwise untouched
    variant_applied = (variants.apply(blind_env.get_policy(), variant) == a.domain_policy
                       and (variant == variants.BASELINE) == (a.domain_policy == blind_env.get_policy()))
    blind_schemas = [t.openai_schema for t in blind_agent.tools]
    policy_same = a.system_prompt == blind_agent.system_prompt  # the complete system prompt, not only the policy
    schemas_same = json.dumps(schemas, sort_keys=True) == json.dumps(blind_schemas, sort_keys=True)
    task_refs = agent.task_references(a, Task)
    scan = agent.leakage_check(task, a.system_prompt + "\n" + json.dumps(schemas))
    return {
        **agent.last_build,
        "system_prompt_sha256": hashlib.sha256(a.system_prompt.encode()).hexdigest(),
        "system_prompt_chars": len(a.system_prompt),
        "tools": [s["function"]["name"] for s in schemas],
        "side_channel_tool_exposed": SIDE_CHANNEL_TOOL in [s["function"]["name"] for s in schemas],
        "system_prompt_identical_without_answer_key": policy_same,
        "tool_schemas_identical_without_answer_key": schemas_same,
        "task_objects_found": task_refs,
        "task_object_search": f"bounded: depth {agent.TASK_SEARCH_DEPTH}, attributes/lists/dicts, no closures",
        "string_scan": {**scan, "role": "diagnostic, not the gate",
                        "interpretation": ("these inputs are unchanged when the answer key is emptied; "
                                           "inspect where the overlapping values come from") if scan["findings"]
                        and policy_same and schemas_same else None},
        "variant_applied_as_recorded": variant_applied,
        "passed": ("task" in agent.last_build.get("withheld", []) and policy_same and schemas_same and not task_refs
                   and variant_applied),
    }


def _result_record(simulation, orchestrator, error) -> dict:
    if simulation is not None:
        messages = serialize_messages(simulation.messages)
        termination = simulation.termination_reason.value
        reward_info = simulation.reward_info.model_dump(mode="json") if simulation.reward_info else None
    else:
        partial = orchestrator.get_trajectory() if orchestrator is not None else []
        messages = serialize_messages(partial)
        termination, reward_info = None, None
    calls = tool_calls(messages)
    return {
        "execution": {"finished": simulation is not None and error is None,
                      "simulation_returned": simulation is not None,
                      "error": f"{type(error).__name__}: {error}"[:500] if error else None,
                      "error_in_role": getattr(error, "aep_role", None) if error else None},
        "termination_reason": termination,
        "evaluation": reward_info,  # the official evaluator's output, unmodified
        "models_observed": models_observed(messages),
        "counts": {"messages": len(messages), "tool_calls": len(calls),
                   "agent_tool_calls": sum(c["by"] == "agent" for c in calls),
                   "tool_errors": sum(bool(c["error"]) for c in calls),
                   "side_channel_tool_calls": sum(c["by"] == "agent" and c["name"] == SIDE_CHANNEL_TOOL
                                                  for c in calls)},
        "messages": messages,
        "tool_calls": calls,
        "retrievals": retrievals(calls),
    }


def _spend_record(simulation, budget: Budget | None) -> dict:
    reported = None
    if simulation is not None:
        reported = {"agent_cost": simulation.agent_cost, "user_cost": simulation.user_cost,
                    "note": "tau2's own numbers: litellm price map, agent and user only; 0.0 for unknown models; "
                            "excludes embeddings, grader and failed calls"}
    return {
        "reported_by_benchmark": reported,
        "incurred": budget.summary() if budget else None,
        "ledger": budget.ledger() if budget else [],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str))
    os.replace(tmp, path)  # atomic: readers never see a half-written file


def _capture_tau2_logs(run_dir: Path):
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    return logger.add(run_dir / "tau2.log", level="DEBUG")


def _release_tau2_logs(sink_id) -> None:
    from loguru import logger

    logger.remove(sink_id)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", required=True)
    p.add_argument("--scripted", type=Path, help="script file: mock run, no network, no spend")
    p.add_argument("--agent-model")
    p.add_argument("--user-model", default=OFFICIAL_USER_MODEL)
    p.add_argument("--agent-args", type=json.loads, default={"temperature": 0.0})
    p.add_argument("--user-args", type=json.loads, default=dict(OFFICIAL_USER_ARGS))
    p.add_argument("--retrieval-config", default="alltools")
    p.add_argument("--agent-variant", default="baseline", help="bench/variants/<name>.md, or baseline")
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--max-errors", type=int, default=10)
    p.add_argument("--seed", type=int, default=300)
    p.add_argument("--timeout-s", type=float, default=1200.0)
    p.add_argument("--budget-usd", type=float)
    p.add_argument("--max-output-tokens", type=int, default=4096)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "runs" / "local")
    a = p.parse_args(argv)
    if a.scripted:
        from bench.scripted import AGENT_MODEL, USER_MODEL
        a.agent_model, a.user_model = AGENT_MODEL, USER_MODEL
    elif not a.agent_model:
        p.error("live runs need --agent-model")
    opts = RunOptions(
        task_id=a.task, agent_model=a.agent_model, user_model=a.user_model,
        agent_llm_args=a.agent_args, user_llm_args=a.user_args, retrieval_config=a.retrieval_config,
        max_steps=a.max_steps, max_errors=a.max_errors, seed=a.seed, timeout_s=a.timeout_s,
        budget_usd=a.budget_usd, limits=Limits(max_output_tokens=a.max_output_tokens, max_attempts=a.max_attempts),
        scripted=a.scripted, out_dir=a.out_dir, agent_variant=a.agent_variant,
    )
    trace, path = run(opts)
    spend = (trace.get("spend") or {}).get("incurred") or {}
    print(json.dumps({
        "label": trace.get("label"),
        "termination_reason": trace.get("termination_reason"),
        "official_reward": (trace.get("evaluation") or {}).get("reward"),
        "attribution": trace.get("attribution"),
        "trace_complete": trace.get("trace_complete"),
        "persisted": trace.get("persisted"),
        "research_eligibility": trace.get("research_eligibility"),
        "spend_upper_bound_usd": spend.get("upper_bound_usd"),
        "trace": str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path),
    }, indent=2))
    if not trace.get("persisted"):
        print("ERROR: the trace was not saved; see trace_error.json / manifest.json", file=sys.stderr)
        return 2
    return 0 if trace.get("execution", {}).get("finished") else 1


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    sys.exit(main())
