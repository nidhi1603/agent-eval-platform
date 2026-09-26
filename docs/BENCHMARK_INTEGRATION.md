# Benchmark integration: decisions and evidence

How the local runner (`bench/`) connects to tau2-bench, why, and what would show the choice is wrong.
Researched 2026-09-26 against tau2-bench v1.0.1, commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619`
(file references below are to that commit).

## Question

How do we run one banking task so that (1) the agent sees only what a deployed agent would see,
(2) grading is the official grader, unmodified, and (3) every paid call passes estimated spend admission control and is recorded?

## Primary sources

- tau2 code: `runner/build.py` (`build_agent`, `build_text_orchestrator`, `_build_env_kwargs`,
  `_derive_read_log_allowlist`), `runner/simulation.py` (`run_simulation`), `evaluator/evaluator.py`,
  `orchestrator/orchestrator.py`, `utils/llm_utils.py` (`generate`, `get_response_cost`),
  `domains/banking_knowledge/{environment,retrieval,tools}.py`, `knowledge/` (embedders, cache).
- tau2 docs: `docs/leaderboard-submission.md` (standard vs custom, required retrieval_config, no task
  subsets), `README.md`, `RELEASE_NOTES.md` (v1.0.1 grading fixes).
- Paper: Shi et al., "τ-Knowledge: Evaluating Conversational Agents over Unstructured Knowledge",
  arXiv 2603.04370 (protocol: gpt-5.2 user simulator with low reasoning effort; pass^k; §7 failure analysis).

## Findings that shaped the design

| Finding | Evidence | Consequence |
|---|---|---|
| `build_agent` passes `task=` (with reference actions) to every agent factory | `runner/build.py`, `build_agent` | Our factory takes an explicit allowlist (`tools`, `domain_policy`, `llm`, `llm_args`) and records what it withheld |
| The environment also receives the task; only `golden_retrieval` uses it (inlines required documents) | `retrieval.py`, `golden_prompt`; `environment.py` | `golden_retrieval` is refused; before every run we check the policy is identical with and without the task |
| Grading replays the trajectory on a fresh environment built with the same `env_kwargs` | `evaluator.py`, `evaluate_simulation` | We call tau2's own `run_simulation` with tau2's own `_build_env_kwargs`, so grading cannot drift from the official path |
| Any termination other than agent/user stop scores 0 | `evaluator.py:119-129` | Termination reason is recorded separately from reward so a crash is never read as an agent failure |
| LLM exceptions propagate out of the orchestrator (not converted to a termination reason) | `orchestrator.py`, `run()` | The runner classifies exceptions itself: provider / configuration / interrupted / harness |
| Every chat call (agent, user, NL grader) goes through `llm_utils.completion` | `utils/llm_utils.py`, `generate` | One metering point for chat; callers are tagged by role. litellm maps `num_retries=0` to the SDK's `max_retries`; we also set `max_retries=0` explicitly |
| Embeddings bypass litellm (OpenAI SDK directly); document embeddings are cached under `./data` relative to the working directory | `knowledge/embedders/openai_embedder.py`, `embeddings_cache.py` | A metered embedder subclass is swapped into both embedder registries; mock and live caches are kept in separate directories |
| tau2's reported cost uses litellm's price map and returns **0.0** on unknown models; excludes embeddings, grader and failed calls | `llm_utils.py:119-131` | Two spend figures in every trace: `reported_by_benchmark` and our ledger (usage-based estimate, unresolved reservations; provider-reconciled charges are not available to the code) |
| litellm retries internally (`num_retries=3`) | `llm_utils.py`, `generate` | Forced to 0; our wrapper retries, and each retry is a separate reservation |
| tau2 loads `tasks/task_*.json`; the aggregate `tasks.json` differs on 13 tasks | direct comparison of the files | The split records and checks the hash of the files that actually run |
| `alltools` needs the `srt` sandbox (npm) and `ripgrep` binaries | `knowledge/sandbox_manager.py` | Official config blocked locally until those are installed; zero-cost tests use `bm25` |
| **Side channel in the benchmark:** a discoverable READ call is logged only if it is in the reference trajectory, and the agent-visible `list_discoverable_agent_tools` lists that log | `runner/build.py:_derive_read_log_allowlist`, `tools.py:693,711`; reproduced locally with task_085: identical call, listing differs | The tool stays exposed in unchanged runs, so an LLM agent can call it: "never used" is not enforceable. Each trajectory is replayed against real, control and answer-key-emptied environments; answer-dependent outputs are flagged (positive control: task_085). Flagged runs are kept, and claims limited. Upstream issue drafted (`docs/upstream/`), not filed |

| litellm's supported-parameter list returns the generic OpenAI list even for a made-up model name | probe: `get_supported_openai_params("gpt-6-luna")` | Not evidence that a model honours `max_tokens`; instead the exact parameters sent are recorded and usage is checked against the bounds after every call (violation stops the run) |
| KB search results end with a wall-clock `[Timing: ...]` line | differential replay on task_015 | Agent inputs contain timing noise (minor reproducibility cost); the replay normalizes it and uses a control environment to separate nondeterminism from answer dependence |
| A reference argument (`2025-11-14 03:40:00 EST`, task_085) also appears in the task-independent policy | string scan | The integrity gate is byte-identical prompt and tool schemas with and without the answer key; the string scan is a diagnostic whose overlaps are reported for review, never used to drop a task |

## Decision

Reuse tau2's layers 1-2 (`build_text_orchestrator`, `run_simulation`, official evaluator) and own only
three things: the agent factory (input allowlist), the metering layer (`bench/budget.py`), and the
trace (`bench/trace.py`). The alternative, reimplementing the orchestration loop, would make our
numbers depend on our reimplementation instead of the benchmark's.

## What would show this is wrong

- A scripted run that performs the reference actions scores below 1.0, or one that refuses scores
  above 0.0 (tested: `tests/test_bench.py`).
- The leakage check misses planted task content (tested with positive controls).
- The ledger's confirmed spend differs materially from the provider's usage dashboard for the same
  run (checked after the first live run).
- A live trace contains an agent tool call with no recorded result, or a paid call with no ledger
  entry (`missing_fields` in every trace).

## Failure classes in the trace

`agent_success`, `agent_failure` (agent results) vs `configuration_failure`, `provider_failure`,
`simulator_failure`, `interrupted`, `harness_error` (not measurements of the agent; reported separately).
