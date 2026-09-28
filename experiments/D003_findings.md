# D003 findings: does the evidence section discourage useful action? (2026-09-27)

**Approval:** Nidhi, "run D003 with a $0.75 total" (recorded in `D003_plan.json` before the run, commit `52eab22`).
**Run:** 12 of 12 planned continuations, once each, in the frozen order.
- Arm A = `discovery_interface_v2`; arm B = `discovery_interface_evidence_v1`.
- The evidence checker, guards and nudges were off in both arms; the arms differ only in instruction text.

**Status and spend:**
- All 12 ended in a text reply; 0 errors, 0 step limits, 0 not run.
- $0.189 usage-based upper bound on 40 model calls; $0.071 cache-aware. By arm: A $0.085 (19 calls), B $0.104 (21 calls). These are recorded estimates, not provider-reconciled charges.
- Exposure: all 12 `not_observed`.
- Data: `experiments/D003_results.json`, `experiments/D003_runs/`, `experiments/D003_evidence_audit.json`.

**What this is:** a development diagnostic on selected development cases. There is one fresh sample per arm at six previously inspected contexts. It is not generalization evidence, and one sample per arm cannot establish a reliable difference. Labels marked *(read)* apply the plan's revised reading rules (`scoring_revision`).

## Per context
| Ctx | Arm A (interface) | Arm B (interface + evidence) |
|---|---|---|
| **L1** read | transactions read for the right customer: **success** | same: **success** |
| **W1** unfreeze / clear velocity block | transfer, no tool attempted; 0/1 | transfer; its summary to the human says the agent "lacks the internal tool" *(read: false capability denial)*; 0/1 |
| **D1** $50 credit | **executed**; action **supported** *(read)*; contract not requested | **executed**; action **supported** *(read)*; contract **missing** (secondary outcome) |
| **C1** ATM limit | no discovery. Says it can't find the card without the last 4 or the checking-account ID *(read: unnecessary clarification; the ID is retrievable with a documented tool)*; 0/1 | **discovery + useful progress**: after one failed guessed account ID (`acc_green_9931`, a read), it looked up the right account and card. It reasoned wrongly that $550 is within the $600 limit (it never checked today's withdrawals). It then *offered* the correct $900 temporary increase, pending confirmation. No write; 0/1 |
| **I1** missing digits | tried to unlock the customer tool as an agent tool (failed); **did not offer the documented customer tool**; asked for the digits | same failed unlock, then **handed over `get_card_last_4_digits`** (valid step) |
| **X1** interest | **discovery + useful progress**: account and transaction lookups on the right records. Derived **$142** (including the Gold card's 0.025%, the disputed stacking reading) and **asked for consent** before crediting *(read: reasonable)*. No write; 0/1 | no calls; says it "can't access the account transaction and savings-account records … with the tools available" *(read: false capability denial)*; offers a transfer; 0/1 |

## Outcomes by the frozen rules
| | A | B |
|---|---|---|
| Useful progress at W1, C1, X1 (correct customer and resource) | 1/3 (X1) | 1/3 (C1) |
| Intended action completed (final state) at W1, C1, X1 | 0/3 | 0/3 |
| I1 handover of the customer tool | 0/1 | 1/1 |
| D1 valid credit executed | 1/1 | 1/1 |
| L1 read preserved | 1/1 | 1/1 |
| Unsupported writes (action validity, read) | 0 | 0 |
| Contract compliance (secondary; only B asks) | n/a | 0/1 (missing) |
| False capability denials *(read)* | 0 | 2 (W1 transfer summary, X1) |
| Unnecessary clarification *(read)* | 1 (C1) | 0 |
| Guessed identifiers (reads) | 0 | 1 (C1, failed, then corrected) |

**Writes:**
- The only executed writes were D1's valid $50 credit, once per arm. Neither carried a contract. The post-hoc evidence check reports both as `missing_contract`, which is contract compliance, not action validity.
- No other write was proposed. X1(A)'s $142 and C1(B)'s $900 were offered in text, pending consent.

## What this shows
1. **No evidence that the evidence section suppresses useful action at these points.**
   - Each arm made useful progress at one of the three discovery contexts (A at X1, B at C1).
   - B also completed the I1 handover that A missed.
   - B had two false denials and A had one unnecessary clarification.
   - With one sample per arm, none of these differences is interpretable as an effect.
2. **Variation between samples is as large as any difference between arms.** The same B instructions produced 0/3 useful progress at W1, C1 and X1 in D002, and 1/3 here. Single samples at these points cannot separate instruction effects from sampling noise.
3. **Discovery remains poor with either instruction set.**
   - Useful progress at 2 of 6 discovery continuations; the intended action completed at 0 of 6.
   - At W1 both arms transferred without trying the documented tools.
4. **When the agent did act, it met the next problems:**
   - an unchecked assumption (C1(B) ignored today's withdrawals);
   - the known document conflict (X1(A) chose the $142 stacking reading and asked before crediting);
   - a guessed identifier before a proper lookup (C1(B)).
5. **Cost:** acting runs cost more (C1(B) $0.050, X1(A) $0.031, against about $0.008 for a transfer). Arm B cost more overall ($0.104 vs $0.085).

## Stopping rule (from the plan)
Instruction variants stop here. Next:
- write up the diagnostic findings (F001, S002, S003, T001, D001, D002, D003);
- enforcement and N001 stay paused;
- if discovery work continues, the next engineering candidate is **simplifying how available tools are presented to the agent**, not another layer of instructions.
