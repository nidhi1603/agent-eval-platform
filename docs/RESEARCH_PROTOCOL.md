# Research protocol

How every harness change gets proposed, tested, and kept or killed. Written before the
first experiment so the rules can't bend to fit the results.

## Research question

> **Can automatically extracted, source-linked action prerequisites improve a banking agent's
> reliability over a strong retrieval baseline, without blocking too many valid actions?**

Revised 2026-09-26 after external review. The earlier framing ("automatic procedure compilation is
something vendors don't do") was wrong: Decagon's AOP Copilot and Intercom's Fin Procedures both
draft procedures from SOPs, documentation and past conversations, and PCAS (2602.16708),
Autoformalization into Policy-as-Code (2606.26649) and COVENANT (2607.25400) compile natural-language
policies or workflows into enforceable forms. This project builds on and compares with them; it does
not claim automatic compilation as novel.

## What counts as success

**The primary comparison is internal and paired:** the same agent model and budget, on the same
held-out tasks, with vs without the intervention. Results are reported with task-level CIs.

| Variant | What it isolates |
|---|---|
| A. Standard agent | Starting point |
| B. A + improved retrieval | Whether finding the right information is enough |
| C. B + extracted rules in context | Whether structured guidance helps |
| D. C plus action-time enforcement of the same rules | Whether enforcement adds value beyond guidance |
| E. D with a small manually reviewed rule set | Whether compiler quality is the bottleneck |

D differs from C in exactly one thing: the identical rule set, still shown in context, is also enforced
before controlled actions. Any other difference (new rules, different retrieval, different prompt)
would confound the C→D comparison. E's rules are labelled human-reviewed and never reported as automatic.

Metrics beyond task success: incorrect write actions executed, **valid actions wrongly blocked**
(false blocks), whether the required evidence existed before each write, cost and latency.
Extra resources (a stronger compiler model, extra inference, longer context) are reported, never hidden.

**Leaderboard numbers are context, not the comparison.** A score on our 67-task holdout, the 30-task
dev split, or any single task is not a leaderboard reproduction and is never presented as one. The
leaderboard requires all 97 tasks, 4 trials each, unmodified task definitions (`docs/leaderboard-submission.md`
in tau2-bench). Any leaderboard claim requires running the
official protocol on all tasks and submitting through Sierra's process. For context only: the best
standard text entry is 55.2% pass^1 / 35.1% pass^4 (Qwen 3.8 Max, from Sierra's
`web/leaderboard/public/submissions` data, read 2026-09-24).

A reproducible improvement, a well-explained negative result, and a clear account of the tradeoffs
are all acceptable outcomes.

## Fixed setup (changes only by an explicit, logged decision)

- **Benchmark:** tau2-bench v1.0.1 at commit b7ea907 `banking_knowledge`. The hash of the task files
  tau2 actually loads (`tasks/task_*.json`) is recorded in `splits/banking_knowledge.json` and checked
  before every run. (The aggregate `tasks.json` is stale on 13 tasks and is not used.)
- **User simulator:** `gpt-5.2` with `reasoning_effort: low`, as in the paper (arXiv 2603.04370) and
  the standard leaderboard entries.
- **Agent model:** chosen once in cycle 0 and held fixed while harness components change.
- **Trials:** k = 4 per task, so pass^1 through pass^4 are all measurable.
- **Baseline retrieval config:** `alltools` (the leaderboard's standard configuration).

## Denominator and replacement rules (fixed before any live run)

Every scheduled trial is reported in one of: completed and eligible, completed but ineligible, interrupted, replaced.
Nothing leaves the denominator silently.

- **Official score:** the evaluator's reward for every scheduled trial, exactly as tau2 computes it (premature
  terminations score 0). This is the number comparable to published results.
- **Research eligibility** (`research_eligibility` in each trace): finished, officially graded, trace complete,
  no unresolved spend, and the failure cause is the agent or none.
- **Replacement:** a trial whose cause is `provider`, `configuration`, `interrupted` or `harness` is rerun once
  with the same seed and recorded as *replaced*, with both traces kept. A second such failure is reported as
  missing, and results are shown with it counted as a failure and with it excluded.
- **Unattributed** (`max_steps`, `timeout`): read the trace and label the cause before seeing any
  comparison result; report the result with and without these trials.
- **Side-channel exposure** (`answer_independence` flag): trajectories are kept and flagged; claims are
  limited accordingly. A variant that hides the log is a disclosed environment change, never the baseline.

## Data split

- **Dev (30 tasks):** all development, debugging, and failure analysis.
- **Test (67 tasks):** evaluated only at milestones: baseline, mid-project, final. At most 3 runs, each logged. **Test trajectories are never read for debugging.**
- Split is stratified by difficulty (required documents + expected actions); dev and test medians match (20.5 vs 20).

## Integrity rules

1. The agent never reads `evaluation_criteria`, `required_documents`, or any other ground-truth field at run time. These are the grader's answers.
2. No task-specific prompts, rules, or special cases. Anything the harness learns must come from the knowledge-base documents and the domain policy.
3. Every run records model, harness config (git SHA + flags), cost, and the split it ran on.
4. Failed ideas are logged as carefully as successes.

## The loop (one cycle ≈ 3–5 days)

1. **Measure:** run the current harness on dev (30 tasks × k=4) with full traces.
2. **Diagnose:** label every failed trial with one failure category (below). Rank categories by count. The biggest bucket is this cycle's target.
3. **Read, targeted:** find 2–4 papers or posts that attack that specific failure. One pass each, with a 5-line note: problem · method · evidence · limitation · what we'd borrow.
4. **Hypothesize before coding:** write the prediction in `EXPERIMENTS.md`, e.g. "a plan verifier will fix ≥ 6 of the 14 ordering failures and raise dev pass^1 by ≥ 5 points."
5. **Implement the smallest version** behind a config flag, so every component can be switched off later for ablations.
6. **Compare paired:** same dev tasks, same k, with vs without the change. Report Δpass^1 with a paired bootstrap 95% CI, Δpass^4, and Δcost.
   *Status: planned. Only pass^k point estimates are implemented (`app/metrics.py`); the paired
   bootstrap and task-level CIs are not written yet and must be implemented and tested before the
   first comparison is reported.*
7. **Decide by the pre-set rule:**
   - **Keep** if the Δpass^1 CI excludes zero, or Δ ≥ +5 points replicated on a second run, and the cost increase is justified.
   - **Revise once** if the direction is right but the signal is weak.
   - **Kill** otherwise, and log why.
8. **Log** the result and move to the next biggest failure bucket.

Before any full dev run, a 5-task, k=1 smoke run checks that nothing is broken (cheap).

## Failure taxonomy (starting set; extend as needed, never delete)

| Code | Failure |
|---|---|
| RETRIEVE | Needed document never found |
| READ | Document found but its content misapplied (ττ-bench: "searched, but not read") |
| DEPEND | Missed a policy dependency across documents |
| ORDER | Right actions in the wrong order |
| TRUST | Acted on an unverified user claim |
| TOOL | Wrong tool, wrong arguments, or missed a discoverable-tool unlock |
| FALSE_OK | Claimed success when the database says otherwise |
| BUDGET | Ran out of steps or turns |
| SIM | Simulated user misbehaved (benchmark noise; tracked, not "fixed") |
| AMBIG | Policy is ambiguous or contradictory and the agent's action was defensible (Policy Loopholes, 2609.14400); tracked, not "fixed" |

For TOOL failures, also record whether the agent chose the wrong *kind* of action or chose
the right action but executed it wrongly. These are different problems with different fixes
(Calibration is the Bottleneck, 2609.00949).

Labels come from reading traces. Once ~50 are hand-labeled, an LLM labeler can take over, but only after measuring its agreement with hand labels (Cohen's κ, reported).

## Statistics

- 30 dev tasks × 4 trials gives a standard error of roughly 4–8 points on pass^1. **Effects smaller than ~5 points are not detectable on dev.** Chase big buckets first.
- Comparisons are always paired (same tasks), which is far more sensitive than comparing two independent scores.
- Test-set results are reported with bootstrap 95% CIs over tasks.
- **Control for prompt length.** When a component adds text to the context (plans, rules), also run a
  length-matched control with irrelevant text, so a gain can be credited to the information and not
  just to a longer prompt (How Do Agent Harnesses Create Value?, 2609.20474).
- **Verify what the grader saw.** Periodically diff the agent's raw model output against the recorded
  trajectory; serving adapters can silently drop tool calls (Interface-Induced Trajectory Censoring, 2609.03966).
- **Guard against shortcut gains.** A change that helps only a few specific dev tasks, or relies on
  benchmark artifacts rather than domain knowledge, is rejected even if the score rises
  (Bad Genius, 2609.18366; ModularRSI, 2609.14857).

## Where we look for research

In step 3 of every cycle, search in this order and stop once there are 2–4 good candidates:

1. **The Agent Canon** (the curated curriculum) for foundations.
2. **DAIR.AI Academy papers** — https://academy.dair.ai/papers — hand-picked weekly since 2023, with
   curator summaries. Use the search (`/papers?q=<topic>`), the topic filters (Agents, Evaluation,
   Memory, Retrieval, Safety, RL), and the **Harness Engineering collection**
   (`/papers/collections/harness-engineering`). Skim the new weekly issue every Monday.
3. **arXiv**, for everything newer than the latest DAIR issue. Run the triage weekly:
   `uv run python scripts/arxiv_scan.py`. It reads the past-week listings for cs.AI, cs.CL and cs.LG
   (one request each; the search API throttles this network after a few queries), matches titles to
   each cycle, skips papers already seen (`research/arxiv_seen.json`), and writes
   `research/arxiv_digest_<date>.md`. Abstracts are added when the API allows. Title matching is a
   triage filter and can miss papers, which is why DAIR is also checked.

Every paper that informs an experiment gets its arXiv ID recorded in `EXPERIMENTS.md`.

## Rules the compiler must produce (and how they are checked)

Exact execution of a wrong rule is still wrong, so compiler correctness is evaluated separately from
runtime enforcement.

Every extracted rule records:
- source document and the exact supporting passage;
- the action it governs and its conditions;
- exceptions and precedence;
- the evidence required and its authoritative source (which tool result proves it);
- the policy version;
- status: `executable`, `ambiguous`, or `unsupported`.

**Unknown stays unknown:** an `ambiguous` or `unsupported` rule never silently permits an action;
the agent must ask, look up evidence, or escalate.

A small **independently reviewed rule test set** (allowed cases, forbidden cases, missing evidence,
exceptions) is written by hand, not generated by the model that wrote the rules, so the tests can't
repeat the compiler's misunderstanding.

## Runtime design constraints (from review)

- **Authorization comes from evidence, not from how a claim sounds.** A customer claim is accepted only
  when an evidence record exists: the fact, its source tool call, the account/customer it refers to,
  and its freshness. A model may help interpret ambiguous wording; it never grants permission.
- **Check the actual action immediately before it executes**, with its real arguments, and update
  state from its result. A plan checked once at the start can go stale mid-conversation.
- **Basic task state and evidence tracking belong in the first agent loop**, because verification
  depends on them. Sophisticated long-term memory is out of scope.

## 60-day sequence

Applications, outreach and interview preparation run from week one: roughly 50% project,
25% applications and outreach, 25% interview preparation.

| Days | Work | Evidence at the end |
|---|---|---|
| 1–7 | Understand the agent loop; integrate the benchmark; run a small baseline | A reproducible command, event logs, a first failure analysis |
| 8–14 | Improve retrieval (variant B); classify dev failures | First paired comparison and a short public demo (milestone by day 14) |
| 15–28 | Extract prerequisites for 1–2 workflow families chosen from dev failures; evidence tracking; action-time checks | Rule test set results and a controlled experiment (variants C, D) |
| 29–40 | Ablations including the reviewed rule set (E); inspect false blocks and missed violations | Results that explain where the method helps and where it doesn't |
| 41–50 | Freeze configuration; evaluate the holdout; measure cost and latency | Final results with uncertainty and limitations |
| 51–60 | Reproducibility, demo, writeup, interview explanations | A project someone else can inspect and run |

**Out of the 60-day scope:** distillation, GRPO or any training, sophisticated memory, automated harness
evolution, and further platform expansion (the full Tempo/Prometheus/Loki/Grafana stack waits;
structured event logs come first).

## Reading map

Read the originals and their implementations; use DAIR and arXiv for discovery. For every paper write
five things: **problem, mechanism, assumptions, evidence, and one experiment it suggests for this system.**

| Phase | Reading |
|---|---|
| Days 1–7 | τ-Knowledge (2603.04370); τ²-bench (2506.07982); Policy Loopholes (2609.14400); Calibration is the Bottleneck (2609.00949) |
| Days 8–14 | Is Bash All You Need? (2609.11999); Context Rot; When Tools Get in the Way (2609.14157) |
| Days 15–28 (closest prior work) | **PCAS** (2602.16708); **Autoformalization into Policy-as-Code** (2606.26649); **COVENANT** (2607.25400); interwhen (2602.11202); ContrAgent (2609.18128); Compositional Policy Violations (2609.18820); CaMeL (2503.18813) |
| Days 29–50 | How Do Agent Harnesses Create Value? (2609.20474) for ablation design; False success (2606.09863); AI Agents That Matter (2407.01502) |
| After day 60 | Harness-Zero (2609.24974); Co-Evolving Harnesses and Models (2609.09134) |

**Candidate tool: Jev (TypeSafe AI, Sep 2026)**, a non-generative "System One" classifier that returns
calibrated probabilities for yes/no, choice, and score questions ($0.042 per 1M input tokens, output free;
vendor-reported 40–200x faster than LLMs; direct signups paused, also on OpenRouter). Candidate uses:
failure labeling and interpreting ambiguous wording. It is **not** an authorization mechanism; permission
to act comes from evidence records. Vendor
claims are not accepted as results: Jev is validated against hand labels like any other judge, the model
version is pinned, and its use is disclosed in any leaderboard submission.

Automated harness optimization (SoL-Pi 2609.20519, Ecdysis 2609.11677, HarnessEvolve 2609.00829)
is out of scope until the hand-built harness works. HarnessEvolve replays tasks with the ground-truth
answer in hand, which would break our integrity rules.
