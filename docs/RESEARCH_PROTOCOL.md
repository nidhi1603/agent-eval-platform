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

Labels come from reading traces. Once ~50 are hand-labeled, an LLM labeler can take over, but only after measuring its agreement with hand labels (Cohen's κ, reported).

## Statistics

- 30 dev tasks × 4 trials gives a standard error of roughly 4–8 points on pass^1. **Effects smaller than ~5 points are not detectable on dev.** Chase big buckets first.
- Comparisons are always paired (same tasks), which is far more sensitive than comparing two independent scores.
- Test-set results are reported with bootstrap 95% CIs over tasks.

## Expected cycle order (a prior; the failure data overrides it)

| Cycle | Focus | Candidate reading |
|---|---|---|
| 0 | Baseline, observability, first failure analysis | τ-Knowledge (2603.04370), ττ-bench (2609.04611) |
| 1 | Finding and actually reading the right documents | Context engineering, Context Rot, ACE (2510.04618) |
| 2 | Policy compilation: knowledge base → structured rules | interwhen (2602.11202), ττ-bench atomic facts |
| 3 | Ordering: plan-then-verify | CaMeL (2503.18813), design patterns (2506.08837), ReWOO (2305.18323) |
| 4 | Trust: verify user claims before state changes | False success (2606.09863), CRITIC (2305.11738) |
| 5 | State and memory across long conversations | SKILL.state (2608.26263), Recuris (2608.24876) |
| 6 | Cost: smaller model, caching, routing | AI Agents That Matter (2407.01502) |
| 7 | Test-set evaluation, ablations, writeup, leaderboard submission | — |
