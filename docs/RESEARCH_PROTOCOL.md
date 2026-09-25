# Research protocol

How every harness change gets proposed, tested, and kept or killed. Written before the
first experiment so the rules can't bend to fit the results.

## Goal

On **held-out τ³-Banking tasks**, with no oracle information:

| Level | Target |
|---|---|
| Floor | Reproduce the default baseline for our agent model within noise of the published number |
| 1 | Beat the best custom harness: 31.2% pass^1 / 13.4% pass^4 |
| 2 (main) | Beat the best published result, 55.2% pass^1 / 35.1% pass^4, or match it with a ~10x cheaper model |
| 3 (stretch) | Close a meaningful share of the gap toward the ~80% expert/oracle ceiling reported in ττ-bench (different benchmark; reference only) |

Final numeric targets are confirmed after the baseline (cycle 0), not before.

## Fixed setup (changes only by an explicit, logged decision)

- **Benchmark:** tau2-bench `banking_knowledge`, tasks.json sha256 recorded in `splits/banking_knowledge.json`.
- **User simulator:** `gpt-5.2`, matching every leaderboard entry.
- **Agent model:** chosen once in cycle 0 and held fixed while harness components change.
- **Trials:** k = 4 per task, so pass^1 through pass^4 are all measurable.
- **Baseline retrieval config:** `alltools` (the leaderboard's standard configuration).

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

## Expected cycle order and reading map (a prior; the failure data overrides it)

All IDs verified on arXiv. Most 2026 entries were found through DAIR.AI Academy (Sep 2026 scan).

| Cycle | Focus | Candidate reading |
|---|---|---|
| 0 | Baseline, observability, first failure analysis | τ-Knowledge (2603.04370); ττ-bench (2609.04611); Policy Loopholes (2609.14400); Calibration is the Bottleneck (2609.00949); Harness or Model? (2609.11987) |
| 1 | Finding and actually reading the right documents | Is Bash All You Need? (2609.11999); VikingRAG (2609.11390); When Tools Get in the Way (2609.14157); Context Rot; ACE (2510.04618) |
| 2 | Policy compilation: knowledge base → structured rules | interwhen (2602.11202); ContrAgent, contracts compiled to automata that gate tool calls (2609.18128); Out-of-Band Policy Enforcement (2608.27646) |
| 3 | Ordering: plan-then-verify | Compositional Policy Violations (2609.18820); ContrAgent (2609.18128); CaMeL (2503.18813); design patterns (2506.08837); ReWOO (2305.18323) |
| 4 | Trust: verify user claims before state changes | False success (2606.09863); PACE, hidden conflicts in requests (2609.03293); Grounding Agent Memory (2609.11060); CRITIC (2305.11738) |
| 5 | State and memory across long conversations | Belief-State Engine (2609.10036); SKILL.state (2608.26263); Recuris (2608.24876); The Compaction Cliff (2608.22752) |
| 6 | Cost: smaller model, caching, efficiency metrics | AI Agents That Matter (2407.01502); RideWay efficiency metric (2609.17985) |
| 7 | Test-set evaluation, ablations, writeup, leaderboard submission | How Do Agent Harnesses Create Value? (2609.20474) for ablation design |
| 8 (optional) | Distill the harness into a smaller open model (the "10x cheaper" path) | Harness-Zero (2609.24974); Co-Evolving Harnesses and Models (2609.09134): imitating a stronger model's trajectories *hurt* the weaker model, on-policy correction helped; SFT or RL for Tool-Calling? (2609.17848); CHART (2609.22247) |

**Candidate tool: Jev (TypeSafe AI, Sep 2026)**, a non-generative "System One" classifier that returns
calibrated probabilities for yes/no, choice, and score questions ($0.042 per 1M input tokens, output free;
vendor-reported 40–200x faster than LLMs; early access). Candidate uses, each a separate experiment:
failure labeling and false-success detection (tooling), the claim-verification gate before state-changing
tool calls (cycle 4), and per-turn model routing between a cheap and a strong model (cycle 6). Vendor
claims are not accepted as results: Jev is validated against hand labels like any other judge, the model
version is pinned, and its use is disclosed in any leaderboard submission.

Automated harness optimization (SoL-Pi 2609.20519, Ecdysis 2609.11677, HarnessEvolve 2609.00829)
is out of scope until the hand-built harness works. HarnessEvolve replays tasks with the ground-truth
answer in hand, which would break our integrity rules.
