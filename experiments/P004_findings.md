# P004 findings: standard agent vs standard agent + transfer re-check (run 2026-10-02)

**Approved:** "run P004 with $9.00" (Nidhi, in chat). **Plan:** frozen at be7e8f2, before any call.
**Spend:** $6.01 billed in total, $19.08 upper bound. Of that, $0.38 is a conservative count of the two operator-stopped conversations (below).
**Execution:** 60 of 60 conversations finished; 30 of 30 pairs complete; 0 interrupted by cap, provider or crash; 0 component defects.

## Verdict (frozen rule): STOP

| Condition | Result | Met |
|---|---|---|
| C1: net passes at least +1 | 3 vs 3, **net 0** | no |
| C2: a correction executed AND the conversation passed | **none** | no |
| C3: no observed regression on the specified transfer outcomes | 0 | yes |
| C4: unsupported transfer statements not higher (blind read) | 0 vs 0 statements, 0 vs 0 conversations | yes |
| C5: no violating write after a hold | 0 writes after a hold | yes |
| C6: billed cost at most 1.5x | $2.60 vs $3.03 | yes |

**What STOP means (as frozen):** no further spending on this candidate under this plan, and no tuning cycle. It does NOT establish that the component has no useful effect, because one conversation per task gives the screen limited power.

## Completion

| | Baseline | Recheck |
|---|---|---|
| Passes (of 30) | 3 | 3 |
| Pass only in this arm | task_017 | task_031 |
| Both pass | task_023, task_035 | task_023, task_035 |

Neither arm passed task_004 or task_012, the two tasks whose reward depends on the code.

## What the component did (all 10 firings)

- **Delivery:** every hold delivered the exact frozen text (sha256 equal to P003's treatment, with doc 042) as the held transfer's result. Each fired once.
- **Replies:** in 9 of 10 the agent re-sent the SAME code. 1 changed the code (task_089: technical_system_error → fraud_or_security_concern); that task's code is not graded, and the conversation failed.
- **No harm observed:** every hold was followed by an executed transfer, and no write followed a hold.
- **Code-graded tasks:**
  - **task_004, the ONE live opportunity:** the re-check fired, and the agent re-sent `kb_search_unsuccessful_customer_requests_transfer` instead of the graded `account_ownership_dispute`. The baseline transferred with `customer_requests_human_no_specific_reason`. Both failed.
  - **task_012:** neither arm made a transfer, so the component never had a chance to act.
- **So the mechanism had one live chance on a score-relevant task, and did not correct the code.** P003's 20 of 27 vs 13 of 27 came from selected saved histories. This one live case does not contradict it statistically, but nothing here confirms it in full conversations either.

## Other measures (descriptive; one conversation per task, so arm differences here are mostly conversation-path noise)

| | Baseline | Recheck |
|---|---|---|
| Conversations with an executed transfer | 16 | 10 |
| Required transfers made (of 4 tasks) | 3 | 3 |
| Unwanted transfers | 13 | 7 |
| Executed writes | 76 | 80 |
| Agent calls | 837 | 734 |
| Billed cost | $3.03 | $2.60 |

The hold acts only after a transfer is proposed, and every held transfer was re-sent. So the gap in transfer counts arises before any hold, and is not attributable to the component.

**Blind claims read:** 199 flagged messages, read by an independent reader from the text alone. 33 were read as transfers done or under way, and all of those followed a successful transfer. The automatic labeller disagreed with the reader on 95, as it is deliberately broad.

## Deviation (disclosed)

The batch process was killed by my tool's 2-hour background limit with 57 of 60 conversations finished.
- Two recheck conversations were in flight: task_077 and task_085. They were never graded.
- They were journaled as operator-stopped, and their spend counts conservatively: billed calls plus each unresolved call's full reservation, $0.38 in total.
- They were rerun fresh within the same approved $9.00, along with task_077's baseline, which had not started.
- No outcome had been read before the rerun, and both reruns failed, as did their partners.

## Files

- `experiments/P004_results.json`, `P004_journal.jsonl`
- `research/p004/summary.json`, `decision.json`
- `research/p004/blind.json`, `key.json`, `claims_tally.json`
