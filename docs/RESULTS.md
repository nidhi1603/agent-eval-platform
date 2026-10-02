# Results: every experiment, side by side

gpt-5-mini on τ-Knowledge `banking_knowledge` (tau2-bench v1.0.1, pinned), development tasks only. The 67 held-out tasks were never run.

**Bottom line:**
- Several components changed the behaviour they targeted in local tests.
- None produced a validated gain in completed tasks over tau2's standard agent in full conversations.
- The project's value is its evaluation engineering and evidence, not a better banking agent.

How to read the tables:
- **Full conversations** are graded by tau2's official evaluator.
- **Targeted tests** (saved-prefix continuations, next-message probes, offline replays) use local checks fixed in advance. Their counts are on SELECTED development cases and are never success rates.
- The two kinds are never combined.
- Spend is in the unit recorded at the time:
  - "UB": the usage-based upper bound, all prompt tokens at the full price;
  - "billed": the provider-billed estimate, cached tokens at the cached rate. It became the accounting basis after H005.

## 1. Full-conversation comparisons (official grade)

| ID | Comparison | Tasks × attempts | Passes (control vs treatment) | Decision under the frozen rule | Spend |
|---|---|---|---|---|---|
| S002 | standard agent, baseline | 6 × 1 | 0 / 6 | descriptive | $0.60 UB |
| S003 | standard vs "search before denying" instruction | 6 × 1 | 0 vs 0 | instruction retired: +45% cost; one unauthorized write in the instruction arm | $1.12 UB |
| H002 | standard vs harness v1 vs harness v2 | 10 × 2 | 0 vs 1 vs 0 (of 20) | rule (+4) not met. Transfers and denials fell, discovered-tool use rose, passes did not | $9.49 UB |
| H003 | standard agent, medium reasoning (calibration) | 5 × 1 | 1 / 5 | settings kept for later runs | $0.83 UB |
| H004 | harness v1 vs v1 + dependency search | 10 × 2 (19 complete pairs) | 2 vs 3 | INCOMPLETE; gate not met (+1 < +4); write-safety screen failed under the adjudicated reading (violations 8 → 20) | $9.86 UB |
| H005 | standard vs harness v1, `alltools` | stopped early | descriptive only | stopped: the per-run cap on the upper bound cut off the longer arm. This led to billed accounting | $3.49 UB (≈ $1.16 billed) |
| H008 | standard vs harness v3.1 (capability search + once-only transfer hold) | 12 × 2 (22 complete pairs) | **5 vs 8** | gate not met: +3 < +5; tasks improved minus regressed +1; write safety worse (3 violations in 2 conversations vs 11 in 7, corrected) | $4.00 billed |
| H009 | v3.1 with full vs read-only automatic tool exposure (harness vs harness) | 12 × 2 | 9 vs 6 | (c) mixed or inconclusive (corrected): fewer violations came with fewer passes | $4.24 billed |
| P001 | v3.2 vs v3.2 + identity-disclosure check | 6 × 1 | 0 vs 0 | INCONCLUSIVE_ON_RECOVERY: the check never fired; 0 covered disclosures in either arm | $1.26 billed |
| P004 | standard vs standard + transfer reason-code re-check | 30 × 1 | **3 vs 3** | STOP, after a disclosed infrastructure-related rerun amendment; the component was closed | $6.01 accounted (billed + $0.38 allowance) |

Two closest calls, neither established:
- **H008 (+3, 8 vs 5):** the gain came from transfer tasks (5 vs 0), while database tasks regressed (3 vs 5) with more write-policy violations.
- **P004:** the one score-relevant chance for the component (task_004) was not corrected live.

## 2. Targeted tests: local effects on the behaviour each component aimed at

| ID | What was tested | Result on the selected cases | Did it carry over to full conversations? | Spend |
|---|---|---|---|---|
| F001 | do agent-visible outputs depend on the hidden answer key? | yes, in 17 of 30 dev tasks, through one listing tool; a local fix removes it without changing grades. Reported upstream (sierra-research/tau2-bench#574) | n/a (benchmark finding) | $0 |
| T001 | does the agent see tools it needs? | tool names reached the agent in 17 of 19 conversations; it unlocked a tool in 2 | led to the adapter and harness (H002+) | $0 |
| D001 | instruction packages at four failure points | fixed the denial at task_095 (3 of 3), then 2 runs applied an underived $100 credit | no (S003) | $0.24 UB |
| D002, D003 | argument-evidence check; interface instructions | check barely exercised (one valid credit blocked); no consistent pattern | not tested | $0.29 UB |
| A001 | direct-tool adapter equivalence | same official grade through wrappers and adapter (2 tasks) | part of v1–v3.1 | $0 |
| v1–v3.2 controls | reference solutions of all 30 dev tasks, scripted | same reward 30 / 30; hard checks fire 0 / 30 | n/a (safety control) | $0 |
| v3 replay | capability search reaches the account-lookup document | 16 of 90 → 81 of 90 conversations that need it (availability, not use) | no: in H008 the lookup tool was called in 6 of 16 where offered | $0 |
| D004 | v3.1 transfer-hold wording | unsupported "transfer under way" claims 26 of 27 → 2 of 27 | yes for claims: 0 unsupported statements in H008 and H009. No pass gain | $0.13 billed |
| retrospective | did v1's hold mislead customers? | 30 unsupported transfer statements in 27 of 84 harness conversations; standard agent 0 in 29 | led to v3.1 | $0 |
| D005 | v3.2 verification hold: what the agent asks next | an eligible field asked in 24 of 30; stored values leaked in 4 of 30 → REVISE | led to the disclosure check | $0.11 billed |
| disclosure check (offline) | catch identity-value leaks before delivery | catches 4 of 4 D005 leaks; would catch 13 of 1,301 saved agent texts; blind review 23 of 23 agree | P001: never fired (no leak situation arose) | $0 |
| P002 | recovery after the check replaces a known leak | 6 of 8 selected continuations reached valid verification and resumed work | not tested at scale; work closed | $0.63 billed |
| failure tally, transfer table | where failed conversations first go wrong | 79 failures, 2 blind readers; 68 transfer decisions. Wrong codes mostly without the reason-code document | chose P003's target | $0 |
| P003 | reason-code re-check with vs without doc 042 | 20 of 27 vs 13 of 27 samples; PASS at G1's threshold | **no** (P004: 3 vs 3) | $0.14 billed |
| confirmation pass | fresh P004 failures | 13 of 27 transferred where the reference has none, on 13 tasks; missing required documents recur (absence, not cause) | none built (decision: package) | $0 |

**The recurring pattern:**
- The targeted behaviour moved: fewer transfers and denials, more tool use, no false claims, more documents retrieved, better codes in replay.
- Completed tasks did not.
- Each fix exposed the next bottleneck, most often acting correctly on a document already in context.

## 3. Measurement and harness defects found and fixed

These are the evaluation engineering results. Each was caught by a control, an audit or a review, and each has a regression test.

| # | Defect | Effect if uncaught | Where |
|---|---|---|---|
| 1 | An agent-visible listing depends on the hidden answer key | answer leakage into 17 of 30 dev tasks | F001; upstream issue |
| 2 | Number provenance matched "100.0" inside "2100.00" | an underived amount looks sourced | D001 |
| 3 | "Reference writes" counted lookups made through the wrapper | progress overstated in H002–H004 | corrected in H004's review |
| 4 | Per-run cap enforced on the upper bound | cut off the longer (harness) arm only | H005 → billed accounting |
| 5 | v1's transfer hold led to false "transfer under way" messages | a harness harm the write audits missed | D004, retrospective |
| 6 | Two agent specs could register under one name | a later run silently reused the first spec's settings | fixed before any affected run |
| 7 | "Customer typed matching values" accepted echoes of agent-shown values | three invalid verifications counted as valid | H008/H009 corrected |
| 8 | **Provenance counted an intercepted draft as delivered** | a valid verification refused (`make demo-provenance`) | before P001 |
| 9 | Execution parser defaulted unknown outcomes to success | 1 of 565 actions mis-scored | H009 correction |
| 10 | A per-run cap below one call's reservation | every run stopped at its first call | P002 attempt 1 → `cap_headroom` |
| 11 | Sequential batches ignored the per-run cap | one conversation could spend past its intended cap (never past the approved total) | fixed after P002 |
| 12 | The harness's fixed verification request confirmed which field matched | a disclosure to unverified customers in 5 of 8 | P002 → neutral request |
| 13 | "Code graded" included task_035 (any code passes) and task_092 (database-graded) | wrong denominators in two analyses | failure tally; P004 plan |

## Spend

| Period | Basis | Total |
|---|---|---|
| S001–D003 (phase 1) | upper bound | $2.26 |
| H002–H005 | upper bound | $23.67 (H005 ≈ $1.16 billed) |
| D004–P004 | billed (P004 accounted) | $16.52 |

Units differ, so these are not summed. Every paid run had an explicit approval with its amount, recorded before the run.

Details: `EXPERIMENTS.md` (chronological log), `experiments/*_findings.md`, `docs/REPORT.md` (narrative).
