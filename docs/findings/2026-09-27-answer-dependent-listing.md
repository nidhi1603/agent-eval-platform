# Finding: an agent-visible tool output in τ-Knowledge banking depends on the answer key

Feasibility study, 2026-09-27. No paid API calls. The held-out test split was not touched.
Code: `bench/audit.py`, `bench/fixes.py`, `bench/independence.py`. Tests: `tests/test_audit.py`.
Data: `results/audit_dev_split.json`.

## 1. The finding (reproducible)

**Mechanism** (tau2-bench v1.0.1, commit b7ea907, `domains/banking_knowledge/tools.py`):
- `call_discoverable_agent_tool` writes a discoverable **read** call to the `agent_discoverable_tools` table only if that tool is in `read_log_allowlist`.
- `read_log_allowlist` comes from the task's reference actions (`runner/build.py::_derive_read_log_allowlist`).
- The agent-visible `list_discoverable_agent_tools` prints that table.
- Result: after an identical call with an identical result, the listing differs depending on whether that read is in the reference solution.

**Reproducer** (`tests/test_audit.py::test_reproducer_leaky_listing_depends_on_the_answer_key`):
- Setup: task_085, unlock and call `get_all_user_accounts_by_user_id_3847` with `{"user_id": "f7d3a82c91"}`, then list.
- With the real task, the listing shows "Found 1 record(s)". With the answer key emptied, it shows "No records found".

**Development-split audit** (30 dev tasks, `bm25`, no model calls, about 20 s):

| | Unchanged environment | With local fix |
|---|---|---|
| Reference-free probe calls (F) | 90, 0 flagged | 90, 0 flagged |
| Reference-constructed probe calls (R) | 479, of which 442 agent-visible | 479, of which 442 agent-visible |
| Agent-visible outputs flagged as answer-dependent | **145** | **0** |
| Nondeterministic outputs (real ≠ control) | 0 | 0 |
| Tasks flagged | **17 of 30** | 0 |
| Distinct mechanisms (grouped by tool) | **1** (`list_discoverable_agent_tools`) | none |

**This is one shared defect affecting 17 tasks, not 17 defects.**
- Independently of the audit, the code predicts the flagged set: a task is exposed exactly when its reference contains a discoverable call to a tool that doesn't mutate state.
- That prediction gives the same 17 tasks. The 4 other tasks with discoverable calls (028, 031, 058, 069) have only write calls, which are always logged, so their listing does not vary.

**Minor, separate:** the "No agent tools have been called yet" branch in `list_discoverable_agent_tools` checks for "No results found". The actual message is "No records found", so that branch never runs.

## 2. The local fix (`bench/fixes.py`, opt-in, disclosed)

- The evaluation log is written exactly as before; the call path is unchanged and only observed.
- The agent-visible listing is rebuilt from agent-facing state: every discoverable call that reached tau2's logging point, in order, regardless of the allowlist.
- Verified:
  - listing identical between real and answer-key-emptied environments;
  - DB state (hash) identical to the unchanged environment;
  - agent-visible tool schemas byte-identical;
  - scripted end-to-end runs graded identically: task_015 reference 1.0 → 1.0, task_085 side-channel script 0.0 → 0.0;
  - the patch is fully undone on exit.
- **It is an environment change.** The listing's wording and content change: it now lists called tools by name, where the original printed raw table records. Its effect on agent success is not measured. Runs using it are flagged "modified benchmark environment" and are never leaderboard-comparable.

## 3. What this does and does not show

**Exposure: shown, within the exercised coverage.** Hidden grading information changes an agent-visible output.

**Exploitation: not shown.**
- In S001, the only live run, the agent never called the listing tool.
- No experiment tests whether agents use it.

**Optimization-driven score inflation: not shown.** No optimizer was run.

**Coverage limits:**
- Dev split only (30 of 97 tasks), with the `bm25` config only. The `alltools` shell, grep and dense-search tools were not exercised.
- Reference-constructed probes follow the reference path. States off that path were exercised only by 3 generic reference-free probes per task.
- Only agent-visible tool outputs are compared. Outputs of user-simulator tools and the static prompt are covered separately by the input gate.
- The perturbation empties specific grading fields. The initial state and user scenario are unchanged.

"No flag" in the fixed environment means no answer dependence was observed for these calls and states. The false-positive evidence is **0 flags in 569 fixed-environment probe calls and 0 in 180 reference-free calls**, plus a synthetic nondeterminism test that is classified as inconclusive, not as a leak. That is a measured rate within this coverage, not a general guarantee.

Removing answer fields is a diagnostic intervention, not a grader.

## 4. Closest prior work (read 2026-09-27; numbers taken from the papers via summarised fetches, spot-check before citing)

| Work | What it demonstrates | What it does not | How this differs |
|---|---|---|---|
| **Meerkat** (arXiv 2604.11806, plus the authors' blog) | Auditing trace repositories with clustering and an LLM finds real cheating. The blog reports ForgeCode prompts containing graded answers: a clean rerun dropped it from 81.8% to ~71.7%. Their paper reports AP/ROC on labelled sets | It does not intervene in environments. Its real-world findings were confirmed by hand without a precision figure. The claim that coding agents *introduced* the shortcuts is a stated belief in the blog, not tested | It detects **exposure** in the environment **before any agent exploits it**, by intervention, and does not need traces of cheating |
| **Reward Hacking Challenges Oversight of Autonomous Research Agents** (arXiv 2609.28614) | Research agents hack known channels: spontaneously in 30.5% of research-pipeline tasks; 74.6% of attempts in a permitted red-team setting; evasion under review feedback. Hacks are confirmed by panel plus a hidden rerun | It assumes the leak channels are known and designed in. It does not search tool environments for unknown answer-dependent outputs | It **finds an unknown channel** in a widely used benchmark and measures false positives with a nondeterminism control |
| **Rethinking the Evaluation of Harness Evolution** (arXiv 2607.12227) | On Terminal-Bench 2.1, with matched rollouts, one evolution method (AHE) does not consistently beat parallel or sequential sampling. Its held-out gain is +0.6 on average | One benchmark and one method. No integrity audit, though the case study notes attempts to weaken tests and task facts written into prompts | Nothing here about evolution. It only suggests evolved-harness integrity is an open measurement need |
| **AutoSaddler** (arXiv 2608.23041, github.com/microsoft/AutoSaddler) | Held-out gains of about +9 to +10 on GAIA2, SWE-Bench Pro and Terminal-Bench. Released code supports only GAIA2 (Meta-ARE) and a test scenario | No tau-bench adapter. No reward-hacking analysis beyond prompt rules and split hygiene | Integration would need 8 missing pieces (harness format, async evaluator, splits, evidence builder, prompt pack, path protection, settings, held-out runner) |
| Also related (abstract-level only): Automated Benchmark Auditing (2605.26079); ImpossibleBench (2510.20270); Agentic Benchmark Checklist (2507.02825) | LLM auditing of benchmarks, impossible-task exploitation tests, and a rigour checklist | Not intervention on hidden grading fields | Complementary |

**Assessment.** Differential testing and counterfactual intervention are established ideas in software testing. What this study adds is an application: intervening on **hidden grading fields** of an agent tool environment, with a nondeterminism control, a measured false-positive rate within stated coverage, and a mechanism-level grouping of findings. It found a real, previously unreported (to my search) shared defect affecting 57% of dev tasks.

That is a useful, incremental contribution. A short search cannot establish that nobody has done it, so it is **not labelled novel**.

## 5. Recommendation

**Finish and hand off this artifact, then resume the original policy experiment.**
- **Why stop here.** The audit direction produced a complete, checkable result. Going further means one of two things, both outside the 60-day scope and current budget:
  - (a) other benchmarks or domains;
  - (b) an optimizer study to test exploitation and score inflation.
- **What finishing means:** Nidhi decides whether to submit the upstream issue.
- **Then** resume S002 and the one-intervention experiment. Primary runs use the **unchanged official environment**, with exposure flagged per trajectory. The fixed environment is at most a disclosed sensitivity check.

## 6. Cost-estimation plan for any paid follow-up (not approved, not started)

The per-rollout cost must be **measured**, not extrapolated from S001, which ended after 6 calls.
1. From S002's six traces, measure full-price and cache-aware cost per rollout for the agent and the user simulator separately.
2. For an optimizer study, the number of rollouts is roughly iterations × 2 × batch (the batch is evaluated before and after each patch) + accepted patches × dev-set size. Add optimizer cost per iteration.
   - AutoSaddler's paper reports about $14.56 per patch with an Opus-class optimizer on GAIA2.
   - Only matched budgets make comparisons meaningful. Even a 10-iteration, batch-3 study is about 60 + (accepted × dev) rollouts plus about 10 optimizer iterations. That likely exceeds $100 before any repetition. **Not feasible on current credits.**
3. Any spontaneous-discovery test must use:
   - a fresh optimizer context and an isolated workspace that excludes this report, the reproducer, answer keys and grading internals;
   - explicit limits on its feedback (scores and traces only);
   - an explicit list of files it may modify.
