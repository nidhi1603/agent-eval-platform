# Literature review, 2026-09-30: what applies to v3 and H007

**Sources.** arXiv search for "Harness" (50 newest), DAIR.AI Academy's Harness Engineering collection and its public paper index (issue 181; the papers-of-the-week dashboard needs a sign-in and was not read). 20 papers were read in full text. Figures quoted here were checked against the paper text unless marked otherwise. None of the papers uses `banking_knowledge` or gpt-5-mini, so every number is from another setting.

**What this document is.** For each idea: what the paper shows, whether the concern applies to us (tested on data already on disk, $0: `checks.py` → `checks.json`), and what to do. Nothing in `bench/` or in the frozen H007 plan was changed.

## 1. Main finding: the give-up check blocks correct transfers, and H007 has three transfer tasks

RegLLM (2609.37501) scores escalation with precision and recall against a should-escalate label. Applying that to our data (the label is "the task's reference actions include `transfer_to_human_agents`") found a defect in v1's `search_before_giving_up` check, which v3 inherits.

| Check on saved data | Result |
|---|---|
| H007 tasks graded on actions, where the pass requires a transfer | 3 of 12: task_004 and task_012 (the transfer is the only reference action), task_035 (emergency tool, then transfer). 6 of 24 conversations per arm. |
| Transfers the public top agents proposed on those three tasks | 23 (22 in passing conversations) |
| Of those, the v1 check would have held | **16 of 23** (12 because a retrieved document names an unused tool, 4 because fewer than 3 searches); 17 of 23 with v3's capability search approximated |
| Transfers the top agents proposed on tasks that do not want one | 9; the check would have held **0** |
| Our standard agent's transfers in H002/H003 (pilot tasks) | 17; the check would have held 17 |
| Our harness conversations in which a transfer was held (H002–H004, all harness arms) | 25; a transfer was executed later in **0** |
| Conversations that executed a transfer | standard agent 17 of 24; harness arms 12 of 77 |

Reading: the check holds nearly every transfer by an agent that has not called a discovered tool, and once held, gpt-5-mini has never come back to the transfer. On the pilot tasks that was mostly harmless, because a transfer was rarely the right outcome. On task_004 and task_012 the transfer is the whole pass. The hold message never says that a repeated transfer will go through.

Two papers describe the same mechanism from the other side:
- XYEval (2609.23939): on tau2 (airline, retail, telecom) a confident wrong suggestion cuts success by 11.2% to 37.2%; agents notice the problem in their reasoning in 92.1% of traces and often do not act on it. Here the harness is the one making the suggestion.
- How Strongly Should Task State Influence an LLM Agent? (2609.25686): on tau2 airline, an advisory that returns a violating write once and says the identical call will execute was overridden in 8 of 30 notices. Ours has been overridden 0 times in 25 conversations.

Limits: the 16 of 23 figure replays the check on GPT-5.5 and Qwen 3.8 Max behaviour, not gpt-5-mini's. Under v3, an agent that calls the account lookup counts as "engaged" and is not held for unused tools, so v3's real exposure could be lower. We have no gpt-5-mini conversation on tasks 004, 012 or 035.

Effect on H007's gate (`gate_sim` in `checks.py`, 100,000 simulations per row):

| Truth | Gate (1) and (2) both met |
|---|---|
| No effect (the same agent twice) | 3% to 6% |
| +0.15 on every task | 36% to 38% |
| +0.25 on every task | 65% to 71% |
| +0.40 on every task | 90% to 95% |
| +0.40 on 9 tasks, the 3 transfer tasks fall to 0.1 | 25% to 71%, depending on how easy those 3 tasks are for the standard agent (25% to 37% if they are its easy ones) |

So a real improvement on the nine database tasks could fail the gate because of the three transfer tasks.

**Proposed (needs approval; changes `bench/harness.py` and re-freezes H007):**
1. The transfer hold fires at most once per conversation (it can now fire every turn: four times in one task_092 conversation).
2. Its message says plainly that calling the transfer again will go through.
3. H007 reports the 3 action-graded tasks and the 9 database-graded tasks as separate strata, fixed before the run.

## 2. Evaluation method (H007 plan amendments, $0)

| Paper | Finding | Applies to us? | Proposed |
|---|---|---|---|
| More Programs or More Rolls? (2609.35873) | Nine byte-identical copies of one program show 2.16 points of apparent oracle gain, against 2.33 for eight distinct harnesses; clone-adjusted gain −0.26 | Yes: with 2 attempts, "solved at least once" would be coverage from extra rolls. With identical agents, a gap of 3 or more passes of 24 arises 29% to 40% of the time (simulation) | State the noise floor in the plan; never score best-of-2; report attempt 0 against attempt 1 within each arm as the same-code control; word a null as "insufficient evidence" |
| Interface-Induced Trajectory Censoring (2609.03966) | Comparing only the items both arms completed is post-treatment conditioning | Yes: H005's cap cut off 2 of 3 v1 conversations. H007 excludes incomplete pairs from the gate | Admissibility rule: if any conversation hits the per-run cap, the gate must also hold with cap-interrupted conversations counted as failures |
| Policy Loopholes (2609.14400) | 17 ambiguities in tau2 airline/retail policy; on 7 affected airline tasks GPT-5 scores 32.1% against 64.5% elsewhere; retail is unaffected because its tools enforce the rules | Yes: `file_credit_card_transaction_dispute_4829` validates only its enum arguments; nothing enforces a dispute limit (read from tau2's source). The agent is the only enforcer, so divergence is expected | Keep reporting rule-dependent counts under both readings; note per rule whether a tool enforces it |
| Compositional Policy Violations (2609.18820, conceptual, no experiments) | An aggregate limit that no single step checks is a "cumulative sum" violation | Yes: the 12-month dispute limit | In the audit, recount disputes from raw records and executed writes, not from what the agent said |
| GAUGE (2609.12191) | On tau2, 57.5% of conversations a human panel rated satisfied had failed the task; averaging four LLM judges does not remove a shared error | Our pass/fail is the official grade, so the primary outcome is unaffected. The audit is exposed: same-family auditors share a misreading | Second reviewer from a different model family, or fix the reading in the codebook |
| Toollery (2609.22218) | The share of requests with every required tool retrieved (0.381) is far below per-tool recall (0.684) | Partly: top agents reach all required documents in 38 of 120 and 43 of 120 dev conversations, and still pass 26 of 82 and 38 of 77 when they do not. gpt-5-mini reached all in 0 of 8 | Report "all required documents reached" beside mean recall; do not treat it as necessary for a pass |

## 3. Harness design: candidates after H007 (not now)

| Paper | Finding | Candidate |
|---|---|---|
| Task State (2609.25686) | Shown checklist 0.55, self-written ledger 0.70, one-line directive 0.84, enforcement 0.98 (Qwen3-235B, synthetic tasks). Moving the directive to the system role drops it to 0.39. Refusals with no notice were read as done in 70 of 86 cases | Explains why v2's shown ledger did not raise passes. v3's note after a capability search and v1's feedback on a held text reply are system messages in mid-history. Different model and mechanism, so test before changing: a small paid probe of the next action under each role |
| Question's Gambit (2609.14412) | A harness-run opening retrieval raises BrowseComp-Plus accuracy 68.1% → 79.0% (GPT-5.4-mini) and 83.1% → 90.5% (GPT-5.5). Queries are derived from the request, expanded with corpus vocabulary, pooled and reranked; top 5 shown. Only 3.8% of remaining errors were "never surfaced" | Supports capability search. If H007 shows the fixed queries miss, derive them from the request. Costs model calls |
| Environment Steering (2609.35807) | Response to a blocked action: stop −36.2% task success, generic retry −10.5%, violation-specific retry +6.5% | Supports our structured feedback. Candidate: a newly discovered write tool needs its eligibility document in the trace first (our extension, no published evidence; aimed at the H004 dispute violations) |
| Fabrication After Tool Failure (2609.14758) | Requiring a status line before the answer cut dishonest responses from 14.10% to 0.87% (value lookup, gemini-2.5-flash) | Candidate: check a completion claim against the tool log before it is sent. Measure the rate on our traces first |
| Co-Evolving Harnesses and Models (2609.09134) | A weak model fine-tuned on expert trajectories fell from 78.0% to 63.1%; corrections at its own failing turn gave 79.7% | Analogy only (they train weights). Write interventions against gpt-5-mini's first failing turn, not against what top agents do in general |
| Grow the Harness, Not the Context (2609.26760) | Ablation (single runs): joint repair of several failures 36% against 28% for one at a time; without a gate set 22% | Acceptance rule: keep a change only if it fixes several failures with one mechanism and breaks no passing task |
| Bad Genius (2609.18366) | A held-out task split does not catch shortcuts tied to the benchmark protocol: one harness's +8.16% became −5.10% when table context moved | One perturbation (shuffle search-result order) before any generality claim |

## 4. Not used

- **Index-side augmentation (Toollery).** Adding generated queries to a harness-side index would replace the benchmark's retrieval tools, and the claim "same model, same tools, with the harness" would no longer hold.
- **ToolSearcher (2609.30906), Traverse (2609.37082).** Both need fine-tuning. One data point is worth keeping: an untrained small model searching over several turns did worse than one-shot retrieval (F1 0.098 against 0.194, not checked against the paper text).
- **When Tools Get in the Way (2609.14157).** One unnecessary tool cut the answer rate from 98.2% to 63.5% on single-turn questions. Opposite failure direction to ours and no guidance on how many tools to expose.
- **The Compiler May Read It (2609.35557).** Its advice (remove secrets from the sandbox; a deny list permits what it omits) is already what `bench/sandbox_policy.py` does. Only 2 of its 15 read routes were tested.
- **Success Leaves Detours (2609.22120).** Backward slicing from a successful write to the reads that fed it is a sound way to mine the public trajectories, but applied per task it would memorise dev tasks. Parked.

## 5. Reproduce

    uv run --extra bench python research/literature/checks.py

Public-trajectory checks read development tasks only. The three transfer tasks were inspected (their scenario and required document) to understand the finding in section 1.
