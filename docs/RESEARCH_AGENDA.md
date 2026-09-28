# Research agenda: what to try from recent work, and in what order

Prepared 2026-09-27, as principal research engineer. Three scans: the DAIR harness collection, recent tool-use/policy work, recent evaluation methodology. Sources were read on arXiv (primary text) by research subagents; every arXiv ID was resolved to its title. Numbers marked † were checked word-for-word in the source; others come from full-text reading and should be spot-checked before citing. The DAIR.AI "Harness Engineering" collection (21 papers) was triaged in full; only its 2025–26 entries plus mechanisms from ReAct/Reflexion/Voyager/DSPy are listed.

**Selection rule.** A paper earns a slot only if its mechanism addresses a failure we *measured* (19 live conversations) and it can be tried at zero cost first. Headline numbers on other benchmarks count for little: none of these papers studies a multi-turn, policy-bound customer-service agent under a ~$2.58 budget.

Our measured failures: (F1) found a discoverable tool, never unlocked it (unlock in 2/17 conversations that saw names); (F2) premature "not available" claims; (F3) fabricated argument values (2 invented verification timestamps); (F4) unauthorized write (rewards without an approved dispute; the environment enforces nothing); (F5) an answer-key side channel (reported upstream).

## Verdicts

### Build now (zero cost) — done in this round

| Paper | Mechanism it inspired (our versions are not implementations of these methods) | Addresses | Implemented as |
|---|---|---|---|
| **Reflexion** (Shinn, 2303.11366) + **Voyager** (Wang, 2305.16291) | Deterministic trigger decides *when* to reflect / verify, instead of always | F1, F2 | `bench/nudge.py`: pre-send check at the denial/transfer signature, once per conversation |
| **Meta-Harness** (Lee, 2603.28052, App. A.2) | Additive information beat prompt/control-flow edits (6 of 7 early edits regressed) | F1, F2 | The nudge adds only names already in context; no standing instruction |
| **Darwin Gödel Machine** (Zhang, 2505.22954, App. H) | Hidden provenance check for hallucinated tool use | F3 | `verification_time_from_clock` (observed rule); `values_for_review` in continuations |
| **PCAS / FORGE** (Palumbo, 2602.16708; v1/v2 vs v3 differ) | Check between proposal and execution against recorded evidence | F4 | `bench/guard.py` with evidence sources declared per rule |
| **ToolSandbox** (Lu, 2408.04682, §2.3; Fig. 3 fabricated timestamp†) | Milestones and minefields beside the official score | F1–F4 diagnosis | `bench/diagnostics.py` |
| **False success in tau2** (Advani, 2606.09863; Table 1†, App. A†) | ~45–47% of single-control failures are confident false-success closings; LLM judges ~0.64 AUROC | labelling | closing-message label (our adapted patterns) |
| **GAUGE** (Bodhwani, 2609.12191, §4.5†) | Judge-free completion bit | labelling | `completion_bit` |
| **PartHackBench** (Yang, 2609.29578) | Historical milestone credit inflates scores; use final-state predicates | diagnostics design | reference-action match labelled "historical"; final-state checklist queued |
| **OpenJarvis** (Saad-Falcon, 2605.17172, §3.3) | Accept an edit only if its target failure cluster improves and no other cluster drops | protocol | acceptance gate in the protocol below |
| **Selection-Aware Stress Testing** (Xu, 2608.30916) | Discovery gains vanished on confirmation; pre-register "no claim"; tasks as clusters; t-based bounds | protocol | added to pre-registration rules |

### Tool use and policy enforcement (third scan: 12 papers, IDs verified on arXiv; numbers from full-text reading, spot-check before citing)

| Paper | What it shows (as read) | How it changes our plan |
|---|---|---|
| **How Strongly Should Task State Influence an LLM Agent?** (Zhang, 2609.25686) | τ²-airline, Qwen3-235B: gated deny rules raise pass^1 0.39→0.54, wrongful-write episodes 54%→35%; replaying gold writes blocks 0/49; an **advisory** warn-once arm let 8 violating writes through under user pressure; silent refusals read as completed work unless the block notice arrives in the same turn (§5.5) | Confirms our split: **enforcement blocks, capability hints advise**. Our block reason reaches the model in the same turn, before it can reply. Next zero-cost step: replay the reference writes of all dev tasks through the observed rules to measure over-blocking |
| **Outcome Monitors** (Panthi, 2608.19303) | A nonbinding receipt that lists the **recovery tools available** raised τ-bench retail +12–14 points; removing the tool list erased the gain | Direct support for the pre-send check's design (it lists tools already seen) |
| **AgentTether** (Zhao, 2607.06273) | τ-bench **Banking** (97 tasks): 94% of failures behavioural; root cause a median 4 steps before failure; one-shot fix messages followed less than half the time; on Banking, **Reflexion repaired 22/83 initially failed tasks, the same as blind retry (22/83)**, i.e. no gain over retry (Qwen3.7-max; different setup from ours) | Caution for our Reflexion-inspired check: measure whether the note is *followed*, and whether it adds value beyond an extra attempt; prefer per-turn checks over preambles |
| **LedgerAgent** (Uddin, 2606.20529) | Hand-written predicates with allow/revise/block, incl. argument grounding (a value must come from observed state); +12–15 pass^1 on τ² retail/airline, no extra model calls | Generalise `verification_time_from_clock` to an argument-provenance rule for IDs; "revise" rather than hard block |
| **PolicyGuard** (Kang, 2606.29225) | Dialogue-grounded verifier with conversation-specific remediation; a gpt-5.4-mini agent 0.20→0.36 pass^4 on τ²-airline; argument-only guards starved legitimate writes | Block messages must name the missing prerequisite and next step (ours do); an LLM verifier is a small-budget option for rules we cannot make deterministic |
| **Fabrication After Tool Failure** (Sethi, 2609.14758) | One failure mode is declining while citing an invented capability limit (our F2); a forced status line cut dishonest answers 14.1%→0.87% | Candidate later package: a "capability check" line before any denial, detectable by regex |
| **Calibration is the Bottleneck** (Zhao, 2609.00949) | Retry-once on stop-without-tool-call, plus flagging never-given parameter values; effect varies from +11.5 to −21.0 pp by model family | Any intervention must be A/B tested on our model; the sign can flip |
| **ContrAgent** (Xiao, 2609.18128); **Near-Miss** (Rabinovich, 2603.29665) | Contracts that both block live and grade saved traces; 8–17% of write trajectories skipped a required policy read yet reached the right final state | Our diagnostics already replay the observed rules over saved traces; add "required read before write" checks |
| **CASD** (Singh, 2609.26261) | A coding agent reading a pool of saved trajectories found absence rules (a call no rollout makes) and wrote better prompts, beating GEPA on 3 of 4 | Our diagnostics found the same absence (unlock in 2/17); a corpus-level prompt revision is a zero-rollout option to compare later |
| **PROCTOR** (Wahi, 2609.02246) | Canary tasks no honest agent can pass expose answer-key cheating | Add canaries to the F001 audit line of work |
| **Policy Loopholes** (Cao, 2609.14400) | Scores become unreliable when policy ambiguity meets permissive tools | banking_knowledge tools are permissive (T001); audit policy ambiguity before calling a write an agent error |

### Try with a small budget (after approval; each < $1)

| Experiment | Mechanism / source | Cost basis | Gate to run |
|---|---|---|---|
| **D001 pilot** (frozen): four instruction packages at 4 saved failure points | MCP-Zero (2506.01056) one-example; Play2Prompt (2503.14432, Table 3†) descriptions vs demos | 16 agent-only continuations, ~$0.30 | Nidhi's approval ($0.50) |
| **N001**: pre-send check vs baseline, *with* observed rules and the disclosed rewards prototype on, at the 13 prefixes where it would fire | Reflexion/Voyager trigger; Outcome Monitors (recovery-tool list); measure whether the note is **followed** (AgentTether), unlock-given-seen, harms proposed/blocked/executed, and legitimate actions wrongly blocked | ~13–26 continuations, est. $0.20–0.45 (to be measured from D001) | D001 read; plan frozen; approval |
| **DSPy-style demonstration** from the 2 conversations that unlocked correctly | DSPy (2310.03714) bootstrapped demos | continuations only | only if D001's example package shows a signal |

### Later (needs budget or more data)

| Paper | Why later |
|---|---|
| **GEPA** (Agrawal, 2507.19457) | Reflective prompt evolution; ~$86 across six tasks in its GPT-4.1-mini runs; our rollouts are multi-turn. Use its text-feedback idea (feed the evaluator's per-check breakdown into diagnosis) now; the loop later |
| **Meta-Harness loop** | ~60 harnesses/20 iterations; revisit with ≥50 evaluations of budget |
| **Grounded checklist partial credit** (Qin, 2608.27487) | Build final-state checklists from tau2 criteria (deterministic items, abstain when evidence is missing); zero-cost but needs careful per-task construction |
| **Benchmarking the Benchmarks** (Bhat, 2607.02577) | 18.5% evaluator–human disagreement; add an "evaluator artifact" label to our codebook when we label more traces |
| **τ-Knowledge** (Shi, 2603.04370, §7.1) | Label user-simulator errors per turn (they report 4 task-critical in 194 trajectories); apply to our 19 when labelling next |
| **Counsel** (Pisupati, 2606.21627) | Calibrate any LLM labeller on its tau-bench subset before trusting it |
| **Causal Agent Replay** (Shah, 2606.08275) | Counterfactual step attribution fits our replay tooling, but each resample is a paid conversation |
| **Deployment Decision Reliability** (Srinivasan, 2608.11323); **How Many Tasks** (Huang, 2607.12338) | Cite now for "why not binary reward at n=6"; fitting variance components needs more data |

### Skip (for this project)

| Paper | Reason |
|---|---|
| Continual Harness (2605.09998), Prime Agent (2608.23552) | Long-horizon games; cross-episode memory is a side-channel risk on a benchmark. Prime Agent's lesson (§3.5: an exploit stored as a skill) supports our guard design |
| Recursive Language Models (2512.24601) | Solves long context; ours is short, and a KB grep would change the retrieval condition |
| Rubric induction (Quinn, 2608.13564) | Needs positive traces; we have none |

## Updated experiment protocol (additions)

1. **Acceptance gate (OpenJarvis §3.3).** A harness change is adopted only if its target failure improves at its known failure points *and* no other measured failure or harm count gets worse. S003 would have been rejected here before full runs.
2. **"No claim" is a pre-registered outcome** (2608.30916). No superiority claim from one small comparison. When tasks are *sampled*, treat them as clusters and prefer t-based to Gaussian bounds. For a few *fixed* diagnostic prefixes (D001), report per-case outcomes and repeated-attempt variability only; repeated attempts at the same prefix are not additional independent tasks.
3. **Offline replay before any live test.** Every new check is first replayed over all saved conversations to count firings and harm paths, and its firing points are reviewed for applicability by reading (done for the nudge: 13 firings; the first-named tool appears in the reference in 7 and no named tool does in 3, which is *reference-name overlap*, not correctness; 12 of 13 firings would name a write tool the reference does not use; applicability review in `experiments/N001_applicability_review.md`).
6. **Guard validation uses complete scripted conversations**, not raw reference replay: the dev references are grading expectations, not complete conversations (26/30 log a verification, 0/30 read the clock), so raw reference replay lacks the clock evidence needed to assess the clock rule.
4. **Final-state, not historical, credit** for any partial-credit metric (2609.29578).
5. **State-grounded labels anchor LLM-judge labels** (2606.09863): judges anchor on confident closings.

## The research question, as sharpened

> At the decision points where a small model fails to use tools it has already found, does surfacing that information at the moment of failure, with enforced prerequisites, increase correct tool use without increasing prohibited actions, and at what cost?

This is narrower than "improve the agent", testable offline first, and every component needed to answer it is implemented and tested at zero cost.
