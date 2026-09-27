# Research agenda: what to try from recent work, and in what order

Prepared 2026-09-27, as principal research engineer. Sources were read on arXiv (primary text) by research subagents; every arXiv ID was resolved to its title. Numbers marked † were checked word-for-word in the source; others come from full-text reading and should be spot-checked before citing. The DAIR.AI "Harness Engineering" collection (21 papers) was triaged in full; only its 2025–26 entries plus mechanisms from ReAct/Reflexion/Voyager/DSPy are listed.

**Selection rule.** A paper earns a slot only if its mechanism addresses a failure we *measured* (19 live conversations) and it can be tried at zero cost first. Headline numbers on other benchmarks count for little: none of these papers studies a multi-turn, policy-bound customer-service agent under a ~$2.58 budget.

Our measured failures: (F1) found a discoverable tool, never unlocked it (unlock in 2/17 conversations that saw names); (F2) premature "not available" claims; (F3) fabricated argument values (2 invented verification timestamps); (F4) unauthorized write (rewards without an approved dispute; the environment enforces nothing); (F5) an answer-key side channel (reported upstream).

## Verdicts

### Build now (zero cost) — done in this round

| Paper | Mechanism taken | Addresses | Implemented as |
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

### Try with a small budget (after approval; each < $1)

| Experiment | Mechanism / source | Cost basis | Gate to run |
|---|---|---|---|
| **D001 pilot** (frozen): four instruction packages at 4 saved failure points | MCP-Zero (2506.01056) one-example; Play2Prompt (2503.14432, Table 3†) descriptions vs demos | 16 agent-only continuations, ~$0.30 | Nidhi's approval ($0.50) |
| **N001**: pre-send check vs baseline, *with* observed rules and the disclosed rewards prototype on, at the 13 prefixes where it would fire | Reflexion/Voyager trigger; measure unlock-given-seen, harms proposed/blocked/executed | ~13–26 continuations, est. $0.20–0.45 (to be measured from D001) | D001 read; plan frozen; approval |
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
2. **"No claim" is a pre-registered outcome** (2608.30916). With ≤6 tasks, tasks are clusters; use t-based bounds, never Gaussian; no superiority claim from one small comparison.
3. **Offline replay before any live test.** Every new check is first replayed over all saved conversations to count firings, relevance and harm paths (done for the nudge: 13 fires, 7 top-1 relevant, 3 irrelevant-only).
4. **Final-state, not historical, credit** for any partial-credit metric (2609.29578).
5. **State-grounded labels anchor LLM-judge labels** (2606.09863): judges anchor on confident closings.

## The research question, as sharpened

> At the decision points where a small model fails to use tools it has already found, does surfacing that information at the moment of failure, with enforced prerequisites, increase correct tool use without increasing prohibited actions, and at what cost?

This is narrower than "improve the agent", testable offline first, and every component needed to answer it is implemented and tested at zero cost.
