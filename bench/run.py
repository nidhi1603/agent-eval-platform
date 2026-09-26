"""Run one banking development task locally and save a complete trace.

    # zero cost: scripted model responses through the real tau2 path (trace is labelled MOCK)
    uv run python -m bench.run --task task_015 --scripted bench/scripts/task_015_reference.json

    # live: needs an approved --budget-usd, verified prices in bench/prices.json, and a key in .env
    uv run python -m bench.run --task task_015 --agent-model MODEL --user-model MODEL --budget-usd 0.50

Pipeline: verify pins -> refuse test-split tasks -> build tau2's orchestrator with our allowlisted
agent -> integrity checks on the agent's inputs -> run tau2's orchestrator and official evaluator
with every paid call metered -> write runs/local/<run_id>/trace.json (always, even on failure).
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT, agent, pins
from bench.budget import Budget, Limits, install, load_prices, metered_embedder, role
from bench.trace import (
    SCHEMA_VERSION,
    ConfigError,
    classify,
    missing_fields,
    models_observed,
    retrievals,
    serialize_messages,
    tool_calls,
)

OFFICIAL_NOTE = (
    "Official protocol (docs/leaderboard-submission.md, arXiv 2603.04370): all 97 tasks, 4 trials, "
    "retrieval_config=alltools, user simulator gpt-5.2 with reasoning_effort=low, seed 300. A single "
    "development task is never comparable to the leaderboard."
)


@dataclass
class RunOptions:
    task_id: str
    agent_model: str
    user_model: str
    agent_llm_args: dict = field(default_factory=lambda: {"temperature": 0.0})
    user_llm_args: dict = field(default_factory=lambda: {"temperature": 0.0})
    retrieval_config: str = "alltools"
    max_steps: int = 200  # tau2 default; counts every message, not only agent turns
    max_errors: int = 10
    seed: int = 300
    timeout_s: float | None = 1200.0
    budget_usd: float | None = None
    limits: Limits = field(default_factory=Limits)
    scripted: Path | None = None
    out_dir: Path = REPO_ROOT / "runs" / "local"


def run(opts: RunOptions) -> tuple[dict, Path]:
    mode = "mock" if opts.scripted else "live"
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}_{opts.task_id}_{mode}"
    run_dir = opts.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    trace: dict = {
        "schema_version": SCHEMA_VERSION,
        "label": ("MOCK: scripted model responses and fake embeddings. Tests the harness; NOT a benchmark result."
                  if opts.scripted else
                  "LIVE development run: one dev-split task, one trial. Not a leaderboard reproduction."),
        "run_id": run_id,
        "mode": mode,
        "started_at": started.isoformat(),
        "config": _config_record(opts),
        "protocol_note": OFFICIAL_NOTE,
        "provenance": pins.provenance(),
    }
    budget = None
    orchestrator = None
    simulation = None
    error: BaseException | None = None
    t0 = time.perf_counter()
    log_sink = _capture_tau2_logs(run_dir)
    import litellm

    litellm.suppress_debug_info = True  # tau2's cost lookup fails loudly for scripted model names
    try:
        trace["benchmark"] = pins.verify_benchmark()
        split = pins.load_split()
        if opts.task_id not in split["dev"]:
            where = "test split (held out)" if opts.task_id in split["test"] else "neither split"
            raise ConfigError(f"{opts.task_id} is in the {where}; local runs are restricted to dev tasks")
        if opts.retrieval_config in agent.FORBIDDEN_RETRIEVAL_CONFIGS:
            raise ConfigError(f"retrieval_config={opts.retrieval_config} gives the agent task-specific documents")

        budget, send, embedder_cls = _prepare_spending(opts)
        trace["budget"] = {"cap_usd": budget.cap_usd, "limits": asdict(opts.limits)}

        from tau2.data_model.simulation import TextRunConfig
        from tau2.runner.build import _build_env_kwargs, build_text_orchestrator
        from tau2.runner.helpers import get_tasks
        from tau2.runner.simulation import run_simulation

        agent.register()
        task = get_tasks(pins.DOMAIN, task_ids=[opts.task_id])[0]
        trace["task"] = {"id": task.id, "split": "dev", "reward_basis": [str(b.value) for b in
                         task.evaluation_criteria.reward_basis],
                         "sha256": hashlib.sha256((pins.tasks_dir() / f"{task.id}.json").read_bytes()).hexdigest()}
        config = TextRunConfig(
            domain=pins.DOMAIN, agent=agent.AGENT_NAME,
            llm_agent=opts.agent_model, llm_args_agent=dict(opts.agent_llm_args),
            llm_user=opts.user_model, llm_args_user=dict(opts.user_llm_args),
            max_steps=opts.max_steps, max_errors=opts.max_errors, seed=opts.seed, timeout=opts.timeout_s,
            retrieval_config=opts.retrieval_config,
        )
        with install(budget, opts.limits, send=send, embedder_cls=embedder_cls):
            with role("environment_setup"):  # a fresh environment (fresh DB) is built for every run
                orchestrator = build_text_orchestrator(config, task, seed=opts.seed)
            trace["agent_inputs"] = _audit_agent_inputs(orchestrator, task, opts.retrieval_config)
            if not trace["agent_inputs"]["passed"]:
                raise ConfigError("agent input integrity check failed; see agent_inputs")
            with role("environment"):  # tool calls and grading replays; agent/user/grader tag themselves
                simulation = run_simulation(orchestrator, env_kwargs=_build_env_kwargs(config, task) or None)
    except BaseException as e:  # noqa: BLE001 - every exit path, including Ctrl-C, must leave a trace
        error = e
    finally:
        trace.update(_result_record(simulation, orchestrator, error))
        trace["spend"] = _spend_record(simulation, trace["messages"], budget)
        trace["finished_at"] = datetime.now(timezone.utc).isoformat()
        trace["duration_s"] = round(time.perf_counter() - t0, 2)
        trace["missing_fields"] = missing_fields(trace)
        path = run_dir / "trace.json"
        path.write_text(json.dumps(trace, indent=2, default=str))
        if simulation is not None:
            (run_dir / "simulation.json").write_text(simulation.model_dump_json(indent=2))
        _release_tau2_logs(log_sink)
    if isinstance(error, KeyboardInterrupt):
        raise error
    return trace, path


def _config_record(opts: RunOptions) -> dict:
    return {
        "domain": pins.DOMAIN,
        "task_id": opts.task_id,
        "agent": {"implementation": f"{agent.AGENT_NAME} (tau2 LLMAgent, unmodified prompt)",
                  "model_requested": opts.agent_model, "llm_args": opts.agent_llm_args},
        "user_simulator": {"implementation": "tau2 user_simulator", "model_requested": opts.user_model,
                           "llm_args": opts.user_llm_args},
        "retrieval_config": opts.retrieval_config,
        "max_steps": opts.max_steps,
        "max_errors": opts.max_errors,
        "seed": opts.seed,
        "seed_note": "tau2 sends this seed to both LLMs; providers treat it as best-effort, so runs can differ",
        "timeout_s": opts.timeout_s,
        "evaluation": "tau2 evaluate_simulation, EvaluationType.ALL (reward = product over the task's reward_basis)",
    }


def _prepare_spending(opts: RunOptions):
    if opts.scripted:
        from bench.scripted import FAKE_PRICES, FakeEmbedder, ScriptedLLM

        _isolate_embedding_cache(Path(tempfile.mkdtemp(prefix="aep-mock-embeddings-")))
        return Budget(opts.budget_usd or 1.0, FAKE_PRICES), ScriptedLLM.from_file(opts.scripted), FakeEmbedder

    if opts.budget_usd is None:
        raise ConfigError("live runs need an explicitly approved --budget-usd")
    import litellm
    from dotenv import load_dotenv
    from tau2.knowledge.embedders.openai_embedder import OpenAIEmbedder

    load_dotenv(REPO_ROOT / ".env", override=False)
    budget = Budget(opts.budget_usd, load_prices())
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
    return budget, None, metered_embedder(budget, OpenAIEmbedder)


def _isolate_embedding_cache(cache_dir: Path) -> None:
    """tau2 caches document embeddings under ./data. Keep mock and live vectors in separate places."""
    from tau2.knowledge import embeddings_cache

    embeddings_cache._global_cache = embeddings_cache.EmbeddingsCache(cache_dir=str(cache_dir))


def _audit_agent_inputs(orchestrator, task, retrieval_config: str) -> dict:
    from tau2.data_model.tasks import Task
    from tau2.domains.banking_knowledge.environment import get_knowledge_base
    from tau2.domains.banking_knowledge.retrieval import build_policy, resolve_variant

    a = orchestrator.agent
    schemas = [t.openai_schema for t in a.tools]
    visible = a.system_prompt + "\n" + json.dumps(schemas)
    variant = resolve_variant(retrieval_config)
    kb = get_knowledge_base()
    policy_independent = build_policy(variant, kb, task) == build_policy(variant, kb, None)
    task_refs = agent.task_references(a, Task)
    leakage = agent.leakage_check(task, visible)
    return {
        **agent.last_build,
        "system_prompt_sha256": hashlib.sha256(a.system_prompt.encode()).hexdigest(),
        "system_prompt_chars": len(a.system_prompt),
        "tools": [s["function"]["name"] for s in schemas],
        "policy_identical_with_and_without_task": policy_independent,
        "task_references_inside_agent": task_refs,
        "leakage_check": leakage,
        "passed": ("task" in agent.last_build.get("withheld", []) and policy_independent
                   and not task_refs and leakage["passed"]),
    }


def _result_record(simulation, orchestrator, error) -> dict:
    if simulation is not None:
        messages = serialize_messages(simulation.messages)
        termination = simulation.termination_reason.value
        reward_info = simulation.reward_info.model_dump(mode="json") if simulation.reward_info else None
        reward = simulation.reward_info.reward if simulation.reward_info else None
    else:
        partial = orchestrator.get_trajectory() if orchestrator is not None else []
        messages = serialize_messages(partial)
        termination, reward_info, reward = None, None, None
    calls = tool_calls(messages)
    return {
        "outcome": classify(termination, reward, error),
        "complete": simulation is not None and error is None,
        "termination_reason": termination,
        "evaluation": reward_info,
        "models_observed": models_observed(messages),
        "counts": {"messages": len(messages), "tool_calls": len(calls),
                   "agent_tool_calls": sum(c["by"] == "agent" for c in calls),
                   "tool_errors": sum(bool(c["error"]) for c in calls)},
        "messages": messages,
        "tool_calls": calls,
        "retrievals": retrievals(calls),
        # tau2 logs a discoverable READ call only if it is in the reference trajectory, and this tool
        # lists the log, so its output can reveal reference membership (docs/BENCHMARK_INTEGRATION.md).
        # Recorded so that no intervention can come to depend on it unnoticed.
        "side_channel_uses": sum(c["by"] == "agent" and c["name"] == "list_discoverable_agent_tools"
                                 for c in calls),
    }


def _spend_record(simulation, messages: list[dict], budget: Budget | None) -> dict:
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
    p.add_argument("--user-model")
    p.add_argument("--agent-args", type=json.loads, default={"temperature": 0.0})
    p.add_argument("--user-args", type=json.loads, default={"temperature": 0.0})
    p.add_argument("--retrieval-config", default="alltools")
    p.add_argument("--max-steps", type=int, default=200)
    p.add_argument("--max-errors", type=int, default=10)
    p.add_argument("--seed", type=int, default=300)
    p.add_argument("--timeout-s", type=float, default=1200.0)
    p.add_argument("--budget-usd", type=float)
    p.add_argument("--max-output-tokens", type=int, default=4096)
    p.add_argument("--max-attempts", type=int, default=3)
    a = p.parse_args(argv)
    if a.scripted:
        from bench.scripted import AGENT_MODEL, USER_MODEL
        a.agent_model, a.user_model = AGENT_MODEL, USER_MODEL
    elif not (a.agent_model and a.user_model):
        p.error("live runs need --agent-model and --user-model")
    opts = RunOptions(
        task_id=a.task, agent_model=a.agent_model, user_model=a.user_model,
        agent_llm_args=a.agent_args, user_llm_args=a.user_args, retrieval_config=a.retrieval_config,
        max_steps=a.max_steps, max_errors=a.max_errors, seed=a.seed, timeout_s=a.timeout_s,
        budget_usd=a.budget_usd, limits=Limits(max_output_tokens=a.max_output_tokens, max_attempts=a.max_attempts),
        scripted=a.scripted,
    )
    trace, path = run(opts)
    ev = trace.get("evaluation") or {}
    spend = (trace.get("spend") or {}).get("incurred") or {}
    print(json.dumps({
        "label": trace["label"],
        "outcome": trace["outcome"],
        "termination_reason": trace["termination_reason"],
        "reward": ev.get("reward"),
        "messages": trace["counts"]["messages"],
        "tool_calls": trace["counts"]["tool_calls"],
        "spend_incurred_upper_bound_usd": spend.get("complete_incurred_upper_bound_usd"),
        "trace": str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path),
    }, indent=2))
    return 0 if trace["outcome"]["class"] in ("agent_success", "agent_failure") else 1


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    sys.exit(main())
