# Can a harness make the same model complete more banking tasks? A technical report

Nidhi Rajani, October 2026.
- **Authorship.** Implementation was AI-assisted (Claude Code). A second model (ChatGPT, acting as tech lead) reviewed every plan and result. Research direction, every spending approval and every decision to stop were mine.
- **Status.** Paused at an honest endpoint. Phase 1 has its own write-up, [WRITEUP.md](WRITEUP.md). The full table is [RESULTS.md](RESULTS.md).

## Question and answer

**Question.** With the model held fixed (gpt-5-mini), can a harness around it complete more τ-Knowledge banking tasks than tau2's standard agent?

**Answer, on this evidence: not shown.**
- Ten full-conversation batches were run under frozen plans: eight comparisons and two baselines or calibrations.
- Several components moved the behaviour they targeted in local tests.
- No intervention demonstrated an overall completion improvement in the full-conversation comparisons; the samples cannot show zero effect either.
- H008 recorded 8 of 22 passes with harness v3.1 vs 5 of 22 with the standard agent, on completed matched pairs, and did not meet the predefined gate. Its corrected audit found 11 policy violations across 7 harness conversations, vs 3 across 2 standard-agent conversations.
- The engineering produced is reusable:
  - a pinned, audited evaluation runner;
  - spend control;
  - blind review procedures;
  - thirteen measurement or harness defects found and fixed;
  - a benchmark answer-exposure finding reported upstream.

## Setup

- **Benchmark:** τ-Knowledge `banking_knowledge`, tau2-bench v1.0.1, pinned and verified on every run. Customers are simulated by gpt-5.2.
- **The task:** agents must find procedures in a 698-document knowledge base, unlock "discoverable" tools named there, verify the customer, and act within policy.
- **Grading:** official, on the final database state or on reference actions.
- **Data:** 30 development tasks. The 67 held-out tasks were never touched.
- **The agent:** gpt-5-mini. Low reasoning effort at first, then medium (from H003); bm25 retrieval, then `alltools` (from H005).

## Method: the controls that make a null result trustworthy

- **Frozen plans before spending.** Each plan fixed its tasks, arms, settings, decision rule and budget before any run. Each paid run needed an explicit approval with its amount.
  - Changes after freezing were recorded as amendments before any spend.
  - The one unplanned rerun (P004, after my tool's time limit stopped the batch) is disclosed, and the original attempt is labelled INCOMPLETE.
- **Spend admission control.** Every call reserves its worst-case cost before sending, and a run that cannot be covered never starts. After H005, completed calls settle at the provider-billed cost.
- **Answer independence.** The agent is built without the task. Differential replay re-executes every agent-visible output against a copy of the task with the answer key erased. This found the benchmark exposure (F001).
- **Negative controls.** Every harness version replays all 30 reference solutions with the same official reward (30 / 30). Hard checks fire 0 times.
- **Blind, independent review.** Safety audits, transfer-claim reads and failure labels were done blind to arm by two readers, with a blind adjudicator for disagreements. The readers were separate model instances (Claude), not humans. What this adds is blinding, independent readings and adjudication, not human ground truth. The reviews also showed their limit: in H008/H009, reviewers agreed on three verifications that a provenance check later showed were invalid.
- **Separate evaluation types.** Full conversations (official grade) and targeted tests (selected development cases, local checks) are reported apart and never merged.

## The hypotheses, in order

**Phase 1: instructions (S002–D003).**
- **Hypothesis:** the agent fails because it does not search or use the tools it finds; better instructions fix that.
- **Result:** 0 of 6 at baseline, and 0 vs 0 with a "search before denying" instruction, at +45% cost.
- **At saved failure points:** instructions fixed one denial, and the next step then went wrong (an underived $100 credit).
- **Stopped** under a pre-set rule: one sample per cell cannot separate effects from noise ([WRITEUP.md](WRITEUP.md)).

**Phase 2a: the harness architecture (H002–H009).**
- **Hypothesis:** deterministic layers beat prompting. These were a tool adapter, checks before giving up, verification and writes, then procedure compilation, dependency search, capability search and controlled tool exposure.
- **Each layer moved its target:**
  - transfers 0.65 → 0.05 per conversation;
  - discovered-tool use about 16×;
  - required documents reached;
  - false transfer claims 26 of 27 → 2 of 27 after a wording fix.
- **Passes did not follow.** H002 gave 0 vs 1 vs 0 of 20, and H004 2 vs 3 of 19.
- **Violations grew** with tools in reach: dependency search took violations from 8 to 20 (adjudicated). v3.1 had 11 in 7 conversations against the standard agent's 3 in 2.
- **The pattern:** repeatedly, the remaining failures involved acting on documents already in context. In 16 agreed policy-step failures, the rule and the evidence were both available. Finding and applying procedures may both remain bottlenecks.

**Phase 2b: verification and disclosure safety (v3.2, D005, P001, P002).**
- **Hypothesis:** holding unsupported verifications prevents echo verifications.
- **Result:** the hold produced an appropriate request 24 of 30 times, but leaked stored values as "examples" in 4 of 30. A deterministic disclosure check was built:
  - offline it caught 4 of 4 leaks, with blind agreement 23 of 23;
  - live (P001) it never had occasion to fire;
  - in 8 selected restored conversations (P002), 6 recovered to valid verification and resumed work.
- **Closed** as a safety component that was compatible where tested. It was never a completion gain.

**Phase 2c: post-verification decisions (failure tally, transfer table, P003, P004).**
- **Hypothesis:** wrong transfer reason codes come from not seeing the bank's reason-code document, and showing it at the transfer fixes them.
- **Replay result (P003):** on 9 saved histories, 20 of 27 vs 13 of 27 samples, a narrow pass.
- **Full conversations (P004):** 3 vs 3 of 30. The re-check fired 10 times, and the agent re-sent the same code 9 times. On the one task where the code decides the score, it re-sent the wrong code.
- **Stopped** under the frozen rule.

## Three layers, and which one this project completed

The broader aim behind the work was a harness that can build a better harness. That needs three layers:

| Layer | What it should do | What this project achieved |
|---|---|---|
| **Evaluation platform** | run agents, measure outcomes, control cost, diagnose failures | substantially implemented, with the limits stated here |
| **Runtime harness** | help an agent complete tasks safely through checks, evidence and recovery | several local improvements; no overall completion gain established |
| **Harness-improvement system** | use evaluation results to propose, implement, test and select better harness versions, and show the selected versions improve on separate tasks | **not built.** The loop was run by hand: Claude implemented changes, while a human and model reviews chose the hypotheses, corrected measurements, changed plans and decided when to stop. That is AI-assisted engineering, not an autonomous, validated optimizer |

An automatic loop would need to:
1. identify a failure pattern from traces;
2. propose and implement a bounded change;
3. test it against the unchanged baseline;
4. accept or reject it on completion, safety and cost;
5. choose the next experiment;
6. show, on separate evaluation tasks, that the versions it selected are better.

The evaluation layer supplies part of that machinery: a trusted scorer, answer-independence checks, regression controls, spend caps and frozen decision rules. The central result, evidence that an improvement process selects better harnesses, is missing.

The manual loop also gives reasons for caution before automating it:
- improvements in replays did not carry over to full conversations (P003 → P004);
- at one conversation per task, an identical agent comes out ahead about 42% of the time, so selecting among many candidates would mostly select noise.

The goal is unfinished, not disproven.

**Relation to tau2-bench.** We extended tau2 with experiment controls, provenance checks and diagnostic workflows. Those extensions helped uncover failures in both the benchmark integration (the answer exposure) and our own harness (the other defects in RESULTS.md). tau2 itself supplies the official grading and replays a conversation's database and simulated customer; our additions build on it. They did not establish a better-performing agent or an effective automatic harness-improvement system.

## Why I stopped

1. **Reach.** P004's component could directly affect only 2 of 30 tasks' scores, and it met one live opportunity. A successful correction would still have had a ceiling of 2 passes. Choosing a target by its tractability rather than its reach was the main design error of the last cycle.
2. **The next obvious candidate has prior negative evidence.** In P004's fresh failures, 13 of 27 transferred where the reference has no transfer, on 13 tasks, with required documents unread. But in H008, increased document availability did not translate into better completion in that combined configuration: the lookup tool was offered in 16 conversations and called in 6. A cheap check that search can find the document would not resolve whether the agent would apply it.
3. **Power.** With one conversation per task, an identical copy of the agent comes out at least one pass ahead in about 42% of simulated runs. That figure is conditional on the estimated per-task pass rates. Detecting a component with a small ceiling needs many more trials than this budget supports.

## What I would do differently

- **Choose interventions by reach first.** How many tasks, and how many conversations per task, could the change affect? Then by mechanism.
- **Estimate power before building.** Use the noise simulation to decide whether a full-conversation screen can detect the component's maximum plausible effect at all.
- **Test "acting on what is in context" directly**, alongside retrieval: much of the evidence pointed to applying procedures, not only finding them.
- **Plan long runs for the tooling's time limits**, with resumable batches from the start.

## Limits

- One model, one domain, development tasks only, small samples.
- Every result is a development screen. None is a benchmark score or leaderboard-comparable: the official protocol is all 97 tasks × 4 trials.
- Many labels come from blind model readers of transcripts (two readers where it mattered), not from human annotation or a validated classifier.
- Spend figures are estimates from token usage.

## Reproduce

- `make test`: the test suite, offline.
- `make demo`: the phase-1 deterministic checks, and the saved results.
- `make demo-provenance`: the delivered-message vs intercepted-draft verification bug and its fix, end to end on a scripted conversation ($0, offline). It proves the scripted behaviour and the regression fix. It does not demonstrate general identity-verification security or live recovery reliability; its value is making a subtle state-tracking defect reproducible.
- Every plan, result, journal and findings file is under `experiments/`. Analyses are under `research/`. The chronological log is `EXPERIMENTS.md`.
