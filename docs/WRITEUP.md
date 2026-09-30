# Evaluating a banking support agent on τ-Knowledge: what I built, found and stopped

Nidhi Rajani, September 2026.
- **Authorship.** Implementation was AI-assisted (Claude Code). A second model (ChatGPT, acting as tech lead) reviewed each stage. Research direction, every spending approval and every decision to publish were mine.
- **Reproduce it.** After installing dependencies and the pinned benchmark data, `make demo` reproduces selected deterministic checks and displays saved experimental results, with no model calls or API spend. It runs offline: it makes no network connection. It does not regenerate the stochastic model outputs; those are the saved traces.
- **Spend.** The live runs cost **$2.26** in usage-based estimates (list prices; not reconciled with the provider).

## Conclusion

I built a reproducible banking-agent evaluation system, identified an answer-dependent tool output in the benchmark, and tested several harness interventions. The small diagnostic studies showed inconsistent tool discovery and exposed trade-offs between action, evidence requirements and correctness. They did not establish a reliable performance improvement.

## The setting

- **Benchmark:** τ-Knowledge `banking_knowledge` (Shi et al., arXiv 2603.04370), tau2-bench **v1.0.1 at `b7ea907`**. Code and data are pinned and verified on every run.
- **The agent:** `gpt-5-mini` (low reasoning effort) with the bank's policy as instructions.
  - It has 15 always-available tools, among them knowledge-base search, customer lookup, verification logging and transfer.
  - There are also 44 **discoverable** agent tools, such as freezing a card or applying a credit. The agent must find their names in the 698-document knowledge base, unlock them, then call them through a wrapper. Four more tools can be handed to the customer.
- **Retrieval:** BM25 (not the official `alltools` configuration). Nothing here is leaderboard-comparable.
- **Data split:** 30 development tasks and 67 held-out tasks. The held-out tasks were never run.

## Two kinds of evaluation, never combined

| | Full conversations | Saved-prefix continuations |
|---|---|---|
| What runs | the agent with a simulated customer (`gpt-5.2`), start to finish | the agent only, from a saved conversation cut at a chosen decision point, with the environment restored to that exact state |
| Stops at | the end of the conversation | the agent's first text reply, or a round limit |
| Graded by | tau2's official evaluator (reward 0 or 1) | local checks fixed in advance (a correct call's receipt, the environment's final state, forbidden writes), plus labels from reading the transcripts |
| Used in | S002, S003 | D001, D002, D003 |

A continuation's "0 completed" means **no target state change before the first text reply**. It is not a failed task: the agent may have been, appropriately, asking for consent. The two kinds are reported separately and never merged into one success rate.

## What I built

- **A local runner** that executes development tasks through tau2's official path and saves complete traces: messages, tool calls, retrievals, official evaluation, spend and provenance.
- **Spending admission control.**
  - Before each model call, the runner reserves a conservative upper bound on its cost. It refuses the call if the approved allocation can't cover it.
  - Retries are metered, and the ledger is written as calls happen.
  - Every paid run needed my explicit approval, which was recorded in the plan and committed *before* the run.
- **Integrity checks.**
  - The agent is built without the task object. Its prompt and tool schemas must be byte-identical to an agent built from a copy of the task with the answers erased.
  - **Differential replay** re-executes every agent-visible tool output against the real task, the real task again, and a copy with the answer key erased. Any output that changes with the answers is flagged.
- **A continuation runner** for saved-prefix diagnostics.
  - It restores the environment, runs the agent, and saves progressively, so a later error never erases earlier actions.
  - It scores five levels: proposed, blocked, attempted, successful, final state.
  - Preflight checks the plan's fingerprints before any network call.
- **Proposal-time review inside the agent:**
  - permission rules that can block a call;
  - a pre-send check that can advise once;
  - an argument-evidence checker (identifiers must come from the verified customer's retrieved records; amounts need a stated, sourced calculation) that can record or enforce.
- **Tests:** the suite reports 174 passing tests and 14 expected failures covering known defects in the unused Kubernetes execution path. All reported experiments used the separate local runner. Reproduced code defects have regression tests.

## Findings

### 1. The benchmark exposed hidden answer data (F001, $0). This is a benchmark finding, not an agent result
- The agent-callable tool `list_discoverable_agent_tools` prints a log. The benchmark writes a read call into that log only if the tool's name is in the task's reference solution.
- Under probes built from the reference solutions, agent-visible output depended on hidden reference data in **17 of 30** development tasks, all through this one mechanism.
- A local, opt-in fix rebuilds only the agent-visible listing. The fix preserves the grading logic, and the tested scripted conversations kept their grades. With the fix, no flags remain on 532 agent-visible outputs.
- This shows exposure only; I did not test whether an agent exploits it.
- Reported upstream with a standalone reproducer: [sierra-research/tau2-bench#574](https://github.com/sierra-research/tau2-bench/issues/574).

### 2. Full conversations: 0/6, and one instruction that didn't help (S002 $0.60, S003 $1.12)
- **Baseline (S002):** 0 of 6 pre-registered development tasks, one attempt each. Reading every trace, the most common failure was concluding something was unavailable without searching for it specifically (5 of 6).
- **One paired intervention (S003):** "search specifically before denying anything". 6 new tasks, each with and without the instruction, in a balanced order fixed in advance. Two labellers, blind to the arm, committed their labels before unblinding.
  - **Both arms scored 0/6.**
  - Denials without a prior search fell from 4 to 2.
  - Estimated cost rose 45%.
  - The instruction arm made an unauthorized write that the instruction itself prohibited.
  - **I retired the instruction.**

### 3. In selected failures, the agent found the needed tool but did not use it (T001, $0)
- Across 19 live conversations, a discoverable agent-tool name appeared in tool results the agent received in **17**, all of them in knowledge-base search results. The agent unlocked a tool in only 2.
  - The count is defined by `scripts/count_tool_names_seen.py`, which checks against the benchmark's tool registry.
  - Seeing a name does not mean the tool was relevant or authorized; the replayed failures below are the stronger evidence.
  - This does not rule out retrieval as another bottleneck.
- One concrete case (task_095, message 26):
  - The agent had searched for `get_all_user_accounts_by_user_id_3847` by name, and seen it in results at messages 3 and 15.
  - It then told the customer: "I don't have access to the internal tool referenced in the KB".
- **Replaying that exact saved state, a script ran the documented unlock and call successfully.** The interface works; the agent didn't use it.
- The same check showed that the environment executes writes without identity verification. Authorization exists only in the written policy.

### 4. Saved-prefix diagnostics: fixing one failure exposed the next (D001–D003, $0.53)
**D001: instruction packages at four failure points** (16 continuations).
- **The fix worked at that point:** at task_095 the baseline denied again, and all three instruction packages (interface explanation, worked example, both) made the documented lookup.
- **What happened next:** two of those three runs then applied a **$100 savings credit with no recorded derivation**, where the task reference is $98.
- **Why $100 is not simply wrong:** a third run derived $100 explicitly, by counting the Gold card's 0.025% bonus. Doc `_045` treats that bonus as a card bonus that does not stack; doc `gold_account_013` calls it a relationship bonus, and `_045` says relationship bonuses do stack. So a valid calculation still doesn't settle entitlement.
- **A measurement bug the credit exposed:** my provenance flag had accepted "100.0" because it appears inside another account's balance, "2100.00". Fixed.
- Elsewhere: an agent made lookups with guessed account IDs; the baseline repeated a prohibited rewards write; and packages avoided that write only by promising an "investigation" that no tool performs.

**D002: recording vs enforcing the evidence check** (12 continuations, identical instructions).
- **The checker was barely exercised.** The only writes proposed were one legitimate $50 credit per arm.
  - Enforcement blocked it for a missing evidence contract, and the one correction did not repair it.
  - No unsupported write was proposed, so no prevention was shown.
- **Discovery:** 0/6 at the three contexts that required it.

**D003: interface instructions vs interface + evidence section**, with the checker off in both (12 continuations).
- **No consistent directional pattern:** each arm made useful progress at one of the three discovery contexts.
- **Run-to-run variation:** outcomes differed across runs with the same instruction text, so these few observations cannot separate instruction effects from run-to-run variation.
- **No target state change before the first text reply** at those three contexts. One agent was asking for consent; another was offering the correct increase pending confirmation.
- **Narrow safety claim (write-policy only; statements to the customer were not audited):** no unsupported write was observed; the only executed writes were already-authorized $50 credits.
- **Other failures observed:** false capability denials, and a handover summary claiming a clearing attempt that never happened.

## What each check can and cannot tell you

| Property | Checked by | Not established by it |
|---|---|---|
| **Answer independence** of agent-visible outputs | differential replay | whether an agent exploits any dependence |
| **Arithmetic consistency** | evidence checker (decimal, explicit rounding) | whether the formula is the one policy intends |
| **Source provenance** (identifiers from the verified customer's records; amounts from cited records or retrieved documents) | evidence checker | whether the source field fits the purpose, or which conflicting document governs |
| **Authorization** (verification, consent, prerequisites) | a verification-*log* prerequisite (logs accept invented identities); the rest by reading | identity, or binding a write to the right customer |
| **Task success** | tau2's official evaluator (full conversations only) | anything about continuations |

A write can pass provenance and arithmetic, as run 02's $100 would, and still be the wrong amount. Each property is reported separately.

## Engineering decisions

**Kept:**
- the pinned benchmark, frozen plans, approval before spending, and pre-registration;
- differential replay;
- saved-prefix continuations as a cheap diagnostic;
- the progressive, five-level scoring;
- the evidence checker, kept as an offline audit tool: its controls pass, including the reviewer's bypass probes.

**Rejected or retired:**
- the "search before denying" instruction (S003: no outcome change, higher cost);
- the first pre-send check (in an offline review, a reviewer judged its first suggested write irrelevant or insufficiently authorized at five of 13 selected points; the suggestions were never executed);
- implicit number matching for provenance (the `2100.00` collision);
- a blanket harness reply that could deny an earlier real change.

**Paused:**
- evidence enforcement: it cost one valid action and prevented nothing in D002;
- the N001 nudge test.

**Why I stopped:** after D003 the pre-set stopping rule applied. More prompt variants at one sample per cell cannot separate effects from run-to-run variation. Across seven experiments, tool discovery never became reliable, however the instructions were framed.

**Phase 2 (in progress since 2026-09-28):** the direct-tool adapter is built and verified at $0 (`experiments/A001_adapter_equivalence.md`): identical official grades through the wrappers and through the adapter. The paired full-conversation comparison (A002) is planned, not run.

**The engineering candidate that started phase 2:** simplify how available tools are presented to the agent (for example, surfacing retrieved tool names as callable tools), rather than adding more instructions. Any test of that would need more than one sample per point.

## Evidence trail

| What | Where |
|---|---|
| Demonstration: deterministic checks (pins, the exposure and its fix, one failure end to end, evidence-check verdicts) plus the saved results | `make demo` → `bench/demo.py` |
| Tool-name count definition | `scripts/count_tool_names_seen.py` |
| Pins | `bench/pins.py` (tau2 1.0.1 @ `b7ea907`, data commit verified) |
| Plans with fingerprints and recorded approvals; results; findings | `experiments/{S002,S003,D001,D002,D003}_*`, `experiments/T001_tool_discovery_check.md`, `EXPERIMENTS.md` |
| Traces and continuation records, ledgers, manifests | `results/`, `experiments/D00*_runs/` |
| Exposure finding, fix, reproducer | `docs/findings/2026-09-27-answer-dependent-listing.md`, `bench/fixes.py`, `repro/tau2_listing_allowlist.py` |
| Harness | `bench/run.py`, `bench/budget.py`, `bench/independence.py`, `bench/continuation.py`, `bench/guard.py`, `bench/evidence.py` |
| Review decisions, with what was accepted, modified or rejected and why | `docs/reviews/` |

## Spend (usage-based upper bounds)

| Experiment | Kind | Spend |
|---|---|---|
| S001 (first live run, one task) | full conversation | $0.02 |
| S002 | full conversations | $0.60 |
| S003 | full conversations | $1.12 |
| D001 | continuations | $0.24 |
| D002 | continuations | $0.10 |
| D003 | continuations | $0.19 |
| F001, T001, all audits, reviews and tests | offline | $0 |
| **Total** | | **$2.26** |

## Limits

- One agent model, BM25 retrieval, and small counts: six tasks per full-conversation experiment, one sample per cell in the diagnostics. These are counts, not rates.
- The diagnostic contexts were chosen after observing failures in previously inspected development traces. They are selected development cases, not generalization evidence.
- Many labels come from reading transcripts (by me, one blinded pair in S003, and independent reviewers), not from a validated classifier.
- Spend figures are estimates from token usage and list prices.
