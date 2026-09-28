# Experiment log

Every experiment gets an entry **before** it runs (hypothesis and prediction) and is completed after.
Rules: [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md). Failed ideas stay in the log.

## Template

```
### E### — <short name>
- Date / git SHA:
- Cycle / target failure bucket:
- Hypothesis:
- Prediction (written before running):
- Change (config flag):
- Setup: split=dev, k=4, agent model=, user sim=gpt-5.2
- Result: Δpass^1 = __ [95% CI __, __], Δpass^4 = __, Δcost/task = $__
- Failure buckets before → after:
- Decision: keep / revise / kill — why
- Reading that informed it:
```

---

### S001: integration smoke test (planned; not an experiment)
- Task: dev task_015, chosen by a rule fixed in advance (easiest DB-graded dev task, lowest id).
- Setup: 1 trial, retrieval=bm25 (non-official, labelled), user sim=gpt-5.2 with reasoning_effort=low, seed 300.
- Purpose: check credentials, request compatibility, logging, grading and spend accounting. Not a baseline estimate.
- Kept regardless of outcome; not retried until it passes.
- Run 2026-09-27 01:16 UTC, run_id 20260927T011640Z_task_015_live_da8b4495 (evidence: results/S001_task_015/).
  Agent gpt-5-mini-2025-08-07 (reasoning_effort low); user sim gpt-5.2-2025-12-11 (reasoning_effort low); bm25; seed 300.
- Result: official reward 0.0 (DB mismatch), termination user_stop, 10 messages, 6 model calls.
  Spend: full-price usage estimate $0.0189 (conservative; no unresolved reservations). Cache-aware estimate $0.0122 =
  tau2-reported, confirmed call by call from provider-reported cached tokens (agent 8,576, user 3,072); provider dashboard
  not yet reconciled. The user simulator is ~74% of the full-price estimate. The implemented checks detected no prohibited
  answer leakage;
  differential replay conclusive, no answer-dependent outputs; flag: non-official retrieval config (bm25).
- First consequential error (read from the trace; simulator followed its instructions): at message 4 the agent gave the
  customer the get_referral_link tool for the Crypto-Cash Back Card without evidence that card has a referral program.
  Its one search returned EcoCard and other cards' referral documents. A keyword search of all 698 documents found no
  Crypto-Cash Back referral document: that supports "could not verify this offer", not proof that no applicable policy exists.
  The agent also pre-filled card_name="Crypto-Cash Back Card", so it selected the wrong product itself. The customer used the tool for the wrong card, so the final database has a Crypto-Cash Back referral instead of
  the Platinum Rewards one. Failure label: TRUST (acted on an unverified customer claim), with READ as a contributor
  (the agent restated terms from the EcoCard document as if they applied).
- Harness verdict: integration path works end to end with real models. One trajectory; says nothing about how often this happens.
- Lesson: a satisfied customer, a successful tool call and a correct business outcome are three different measurements;
  here the first two were positive and the third failed.
- Working hypothesis (to be tested only after S002): before enabling an action, establish that authoritative evidence
  supports that action for the specific product and applicable conditions; correct mistaken customer claims separately
  (a customer can quote wrong terms and still qualify). Any rule-based intervention must be compared against a simple
  instruction requiring product-specific evidence, and false blocks must be measured.

### S002: exploratory six-task dev sample (planned)
- Plan fixed before running: experiments/S002_plan.json (selection rule: dev minus task_015, sorted by sha256("S002:"+id),
  first 6 -> task_069, task_080, task_035, task_089, task_029, task_047). Same settings as S001; one attempt each; no retries.
- One shared allocation for the batch (bench/batch.py). Tasks that cannot be admitted are recorded, not dropped.
- Per task: official reward, first consequential error with trace excerpt, cost, and whether the cause is uncertain.
- Status: awaiting approval of the batch allocation.

### E000 — Default-agent baseline (planned)
- Cycle / target: 0 — establish the reference point
- Hypothesis: the default tau2 agent's dev-split behaviour is a usable reference point for later paired comparisons.
- Note: a dev-split score is not a leaderboard reproduction (30 of 97 tasks). A leaderboard value for the same model is context for spotting gross harness errors only, never a pass/fail criterion.
- Setup: split=dev, k=4, retrieval=alltools, user sim=gpt-5.2
- Status: blocked on model API keys (agent model + OpenAI for the user simulator).

### F001: answer-dependent listing audit (feasibility study, 2026-09-27, $0)
- Question: can controlled differential replay detect hidden-answer dependencies in agent tool environments,
  with reproducible evidence and a measured false-positive rate? (The answer gives negative controls within coverage, not a general rate.)
- Result (dev split, bm25, no model calls, reference-constructed probes): one shared mechanism (`list_discoverable_agent_tools` prints an
  evaluation log filtered by the reference actions) exposes answer information in 17/30 tasks (145 of 442
  agent-visible reference-probe outputs); the flagged set equals the code-predicted set (a mechanism consistency check, not independent
  validation). With the local fix: 0 flags on 532 agent-visible probe outputs (569 calls executed). Grading logic is
  unchanged; hashes, schemas and grades matched on the tested scripted trajectories only. Exposure only; exploitation and score inflation
  not tested. Report: docs/findings/2026-09-27-answer-dependent-listing.md.

### S002: exploratory baseline batch (run 2026-09-27, $1 approved)
- 6 pre-registered dev tasks, 1 trial each; gpt-5-mini agent, gpt-5.2 user simulator; bm25, unchanged tau2 v1.0.1.
- **Outcome:** 6/6 finished, **0/6 rewarded**. Exposure `not_observed` in all 6: the check was conclusive and the listing tool was never called.
- **Spend:** $0.601 full-price estimate ($0.283 cache-aware), within the $1 allocation. Per rollout, mean $0.100 full price. The user simulator is about 51% of cost.
- **First consequential errors,** labelled by reading traces (`experiments/S002_labels.md`):
  - The most common observed pattern is a negative conclusion without an adequate search ("not documented", "no tool", "can't do that here"): 5/6 traces, and the first error in 3/6.
  - Discoverable agent tools were not unlocked when needed in 3/6.
  - First-error categories are mixed; n = 6, so these are counts, not rates.

### S003: paired instruction comparison (planned; not run)
- **Question:** does one frozen instruction (`bench/variants/denial_check_v1.md`) reduce unsupported denials, and does official success change?
  - Scope: exploratory, 6 tasks × 2 arms × 1 attempt.
- **Tasks:** `task_031`, `task_019`, `task_094`, `task_095`, `task_066`, `task_087`. Chosen by sha256 from the dev tasks that were unused for S002 analysis and prompt design. F001 probed all dev tasks, so these are not "unseen".
- **Order:** balanced, pre-specified, with each task's two arms run back to back.
- **Settings:** identical to S002; the benchmark is unchanged.
- **Measures:**
  - Primary: official reward per pair.
  - Secondary: unsupported denials, harms (unnecessary actions, delayed transfers) and cost, labelled from a blinded export.
- **Forecast:** about $1.20. Allocation awaiting approval (recommended $1.50). Full plan: `experiments/S003_plan.json`.
- **S003 result (run 2026-09-27):**
  - All 12 finished; spend $1.118 full-price estimate. **0 improved, 0 regressed, 6 both fail.**
  - Unsupported denials: 4/6 baseline vs 2/6 variant (2 pairs lower, 0 higher; anecdotal at n = 6). One harm in each arm; the variant's was an unauthorized write.
  - The variant cost +45% (full price). Post-hoc: denials contradicting just-retrieved tool documents suggest the discoverable-tool mechanism, not search, is the bottleneck.
  - Details: `experiments/S003_findings.md`.
- **S003 decision:** `denial_check_v1` is retired as a candidate default. There was no observed success improvement, and cost rose (+45% full price, +24% cache-aware). The secondary metric measures search compliance, not denial correctness.

### T001: offline tool-discovery check (2026-09-27, $0)
- **Usage:** across 19 live traces, the agent unlocked a discoverable tool in only 2, even though tool names appeared in results it received in 16. It made no failed attempts.
- **Replay:** from the exact saved states where it said it could not act (S003 task_095 msg 26; S002 task_080 msg 22), the documented unlock-and-call sequence **works**. Unlocking returns the parameters, and the calls return accounts and cards and freeze the card.
- **Authorization:** writes execute with no identity verification. Authorization is enforced by the written policy only, not the interface.
- **Conclusion:** not a broken integration; the model did not use a working interface. Details: `experiments/T001_tool_discovery_check.md`. Test: `tests/test_tool_discovery.py`.

### G001: rewards-write permission check (2026-09-27, $0)
- **The rule:** `update_transaction_rewards_3847` requires an approved cash back dispute for that transaction, read from the environment's own records (policy doc `_004`).
- **Placement:** at the agent's proposal step, because tau2 grades by replaying recorded writes; a check at execution time would break grading.
- **Verified:**
  - it blocks the S003 unauthorized write from its saved state;
  - it allows the legitimate task_028 write after auto-approved disputes;
  - a full scripted conversation keeps blocked calls out of the trajectory and grading still completes.
- Details: `experiments/G001_rewards_guard.md`.

### D001: tool-discovery diagnostic pilot (planned; not run; revised per review before any run)
- **Design:** agent-only continuations from 4 saved failure points:
  - P1: permitted; success = correct tool, correct user_id, succeeded;
  - P2: permitted; lookup progress is reported separately from freeze completion (k/3);
  - M1: prerequisite missing; forbidden write proposed/executed, and valid next step;
  - A1: unavailable capability plus missing information, read.
- **Four instruction packages (2x2), v2 files:** none / interface description / validated worked example / both.
  - v2 corrects B's "genuinely unavailable" conclusion and the error-handling sentence.
  - v1 was never run.
  - Each package mixes interface information with behavioural guidance, so differences are attributed to packages, not to interface knowledge alone.
- **Size:** 16 runs, 1 sample, Latin-square order. The G001 guard is off in all arms.
- **Stopping rule:** if nothing improves, read the traces before buying repetitions; confirmation needs new contexts and a new approval.
- **Forecast:** about $0.30 full price. Allocation awaiting approval ($0.50).
- Plan: `experiments/D001_plan.json`.

### Review of c20312c: measurement and preflight fixes (2026-09-27, $0)
- **Outcome:** all five tech-lead findings were verified against the code and the pinned benchmark, and accepted. There is one partial disagreement: an invented tool name passes through, because the environment rejects it with no state change.
- **Continuation runner fixes:**
  - progressive evidence that survives errors;
  - full results used for provenance;
  - receipts, not error flags, decide success;
  - five scoring levels: proposed, blocked, attempted, successful, final state;
  - preflight (fingerprints, split, arms, approval) and a manifest written before any network call;
  - exposure checked on prefix plus continuation.
- **Guard:** the rule is renamed `write_requires_verification_log`, because `log_verification` accepts invented identities, and its unprotected paths are documented. Missing metadata is now a configuration error.
- **Pre-send check:**
  - only success receipts count as used;
  - "relevance" is renamed as reference-name overlap;
  - 12 of 13 firings would name an out-of-reference write.
  - The applicability review of the 13 firing points (`experiments/N001_applicability_review.md`): at 5 the reviewer judged the first suggestion applicable and authorized; the first suggestion was a harm-risk write at 5; the draft was already correct at 2. These are trigger-selected points, and no intervention was executed. **v1 is not ready for N001.** The next candidate is reads-only, after a verification log, evaluated offline first.
- **D001:** scoring revised before any run; still awaiting approval.
- Decision record: `docs/reviews/2026-09-27-tech-lead-review-c20312c.md`.

### Review of 4b63830: D001 cleared technically; guard fail-open fixed (2026-09-27, $0)
- **Reviewer:** reran the suite (120 passed, 14 xfailed) and checked the fixes and D001's four frozen cases and prefixes. Verdict: D001 ready to run as frozen, as a diagnostic on selected failure points, not a reliability estimate. Spending approval stays with Nidhi.
- **Guard (accepted, fixed now rather than before N001; the fix is small and the fail-open is real):** `toolkit_type_lookup` caught every exception as "unknown tool", so a known write whose metadata lookup raised was allowed without a verification log. Now a name absent from the toolkit returns no type (the benchmark's own rejection stands), and a known tool with unreadable metadata raises `GuardConfigError`. Test: `test_unreadable_metadata_for_a_known_tool_fails_closed` (fails on `4b63830`).
- **N001 counts (accepted):** the table had 11 inappropriate drafts, the prose said 10. The per-row labels were right; the reviewer's own summary sentence left out F01 (covered by a customer self-service tool). Reconciled in the file, and the wording no longer implies prevalence or measured benefit.
- **Nudge candidate:** kept as a candidate, not built until after D001, with the reviewer's added requirements (protected reads vs lookups, applicability, honest log wording, required transfers preserved).
- Decision record: `docs/reviews/2026-09-27-tech-lead-review-4b63830.md`.

### D001: tool-discovery instruction packages at four frozen decision points (run 2026-09-27, $0.236 upper bound)
- **Approval:** Nidhi, "run all", for the $0.50 total. Run: 16/16 once each (13 text, 3 step limit, 0 errors). No continuation was flagged for answer-dependent output. Frozen scores unchanged; revision 2 of the findings corrects interpretation.
- **P1** (tool named, permitted): the baseline denied again; **all three packages made the documented lookup**.
  - Two runs (interface, both) then applied **$100 without a recorded, validated derivation**; the reference expects $98.
  - Run 02 (example) derived $100 in text, including the Gold 0.025% that docs `_045` and `gold_account_013` treat inconsistently, and asked permission first.
- **P2:** no freeze before the next reply or step limit, in any run. The example package made lookups on guessed IDs; the others re-asked for confirmation after explicit authorization.
- **M1:** the baseline made the prohibited rewards writes; the packages avoided them but offered investigation workflows no tool performs. No run took the valid step.
- **A1:** all four passed the identifier-request check; one added an unsupported capability claim.
- **Post-run audit ($0):** `D001_audit.md`.
- **Evidence check built offline** (`bench/evidence.py`, controls in `tests/test_evidence.py`). It is not wired into any run. It verifies provenance and arithmetic, not policy.
- Findings: `experiments/D001_findings.md`. Decision record: `docs/reviews/2026-09-27-tech-lead-review-6d42140.md`.

### Review of d2c716e: evidence check hardened; D002 planned (2026-09-27, $0)
- **Accepted and reproduced:** two bypasses (unit constants; numbers from error receipts and customer claims).
  - Amounts now need a sourced contract (`record:` / `policy:` / `customer:` for requests only).
  - Decimal arithmetic with half-up rounding.
  - Separate statuses for missing and invalid evidence; none is a policy verdict.
- **Found while implementing:**
  - card digits, PINs and counts were being treated as amounts;
  - card digits were not checked as identifiers;
  - the scorer missed built-in reads and multi-field final states.
- **Arms:** `record` vs `enforce` (one private correction, then withhold), with identical instructions (`discovery_interface_evidence_v1`).
- **D002 plan (draft, unapproved):** six new dev contexts × two arms = 12 continuations. The expected assessments are frozen; all 12 offline context tests pass. Forecast $0.20–$0.45 upper bound; recommended allocation $0.60.
- Decision record: `docs/reviews/2026-09-27-tech-lead-review-d2c716e.md`.

### Review of 493f5e1: three checker defects fixed before D002 (2026-09-27, $0)
- **Reproduced and fixed:**
  - a date accepted as card digits (I1);
  - division by zero crashed the checker;
  - the withheld reply could deny an earlier successful change (W1).
- **Also:** `customer:` is limited to an explicit (tool, argument) allowlist and to a request message; zero amounts are reported as `unchecked`; the reporting rules are written into the plan.
- **Regressions:** 8 new tests fail on `493f5e1`. Suite: 169 passed, 14 xfailed.
- **D002:** technically cleared; awaiting Nidhi's approval of $0.60. Decision record: `docs/reviews/2026-09-27-tech-lead-review-493f5e1.md`.

### D002: recording vs enforcing the argument-evidence check (run 2026-09-27, $0.100 upper bound)
- **Approval:** Nidhi, "go for it", $0.60 total. Run: 12/12 once each, all ending in text; exposure `not_observed`.
- **The checker was barely exercised:** 2 write proposals in 12 runs, both D1's legitimate $50 credit.
  - A executed it without a contract.
  - B blocked it (`missing_contract`); the correction was a malformed contract in text plus a repeat consent request, so no repair.
  - No unsupported write was attempted in either arm.
- **Discovery failure dominated:** 0/6 discovery at W1, C1 and X1; 0/2 handover at I1. L1 and D1 needed no new unlock. L1's read succeeded in both arms.
- **X1(A):** conditional arithmetic on the customer's unverified inputs, plus a false capability denial. False denials also appear at C1 and X1 in both arms.
- **Reading:** acting at all is still the constraint; enforcement cost one valid action here. Whether the evidence section suppresses action is untested (no interface-only arm).
- Findings: `experiments/D002_findings.md`.

### Review of cccd6e0: D002 interpretations corrected; D003 ablation planned (2026-09-27, $0)
- **X1(A):** conditional arithmetic on unverified inputs plus a false capability denial, not an entitlement claim.
- **Discovery denominator:** 0/6 at W1, C1 and X1; 0/2 handover at I1.
- **Contract finding:** narrowed to what happened.
- **D003 (draft, unapproved):**
  - `discovery_interface_v2` vs `discovery_interface_evidence_v1`, with the checker off, fresh samples, D002's six prefixes (12 continuations);
  - outcomes frozen;
  - forecast $0.10–$0.45, worst case about $0.75.
- **Stopping rule:** after D003, stop instruction variants and write up the findings. Enforcement and N001 stay paused.
- Decision record: `docs/reviews/2026-09-27-tech-lead-review-cccd6e0.md`.

### D003: interface vs interface + evidence instructions, checker off (run 2026-09-27, $0.189 upper bound)
- **Approval:** Nidhi, "run D003 with a $0.75 total". Run: 12/12 once each, all ending in text; exposure `not_observed`.
- **Useful progress at W1, C1, X1:** A 1/3 (X1), B 1/3 (C1); no target state change before the first text reply in either arm.
- **Other cases:** I1 handover A 0/1, B 1/1. D1's valid credit executed in both (contract missing in B, secondary). L1's read preserved in both.
- **Writes and text claims:** 0 unsupported writes. False capability denials: A 0, B 2. Unnecessary clarification: A 1, B 0.
- **Reading:** no consistent directional pattern (inconclusive). Outcomes differed across runs with the same instruction text, and these few observations cannot separate instruction effects from run-to-run variation. No target state change before the first text reply at W1, C1 or X1 in either arm (the runner stops there). No unsupported write was observed; the only executed writes were the authorized $50 credits. Discovery stays poor under both.
- **Stopping rule applies:** no more instruction variants; write up next.
- Findings: `experiments/D003_findings.md`.

### Review of 653efbd and the consolidated write-up (2026-09-27, $0)
- **D003 findings revised:**
  - "no consistent directional pattern";
  - runs with the same text differed;
  - "no target state change before the first text reply";
  - a narrow safety claim;
  - W1(B)'s inaccurate handover summary noted.
- **`docs/WRITEUP.md` rewritten:** separate evaluation types, the evidence trail, the limits of each check, and engineering decisions.
- **`make demo`:** an offline demonstration of the whole evidence trail.
- **Milestone closed.** No further paid experiment; enforcement and N001 paused.

