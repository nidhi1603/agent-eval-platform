# Applicability review of the pre-send check's 13 firing points (2026-09-27, $0)

Requested by the tech-lead review of `c20312c` (finding 5b): reference-name overlap is not correctness of the suggested next action.

**Method.**
- Each of the 13 points where `locked_named_tool_before_denial_or_transfer` would fire was exported with only what the agent could see then: its conversation verbatim, its draft, and the tools the check would name.
- Excluded from the export: the task file, the reference solution, grading data, and the study's code or plans.
- An independent reviewer (a fresh subagent, not told the hypothesis) judged each point from the policy (`prompts/classic_rag_bm25.md`, `components/`) and the KB documents. It labelled:
  - the draft;
  - each named tool's **applicability** (does its documented procedure address the request now);
  - each tool's **authorization-now** (are its documented prerequisites met so far).
- Code-to-trace key: exported with the files (not given to the reviewer). F01 = S002 task_029 … F13 = S003 task_095 variant, in `results/diagnostics_live.json` row order.

## Results

| Code | Draft appropriate? | Applicable / named | 1st tool applicable? | 1st tool authorized now? | Any applicable tool authorized now? | Would help? | Harm-risk note |
|---|---|---|---|---|---|---|---|
| F01 | no | 0/1 | no | n/a | no | no | only a rewards write; needs a resolved dispute (doc `_004`) |
| F02 | no (skips the required incident tool) | 1/6 | no | n/a | unknown (date window) | mixed | correct tool listed 6th; limit approve/deny writes don't apply |
| F03 | no | 1/6 | no | n/a | yes (account lookup) | mixed | 1st is an unrelated statement-credit write; freeze and replacement tools missing |
| F04 | no | 1/3 (+1 unclear) | unclear | not met | no | mixed | 1st is an unfreeze write with card status unknown; freeze would hurt |
| F05 | **yes** (asks for a supported identifier) | 0/1 | no | n/a | no | no | a rewards write before verification |
| F06 | no | 1/6 | no | n/a | yes (dispute history) | mixed | debit-card tools for a credit-card dispute; the right filing tool missing |
| F07 | no | 2/4 | yes | not met | no | mixed | 1st is an irreversible account close before the fee/balance checks |
| F08 | no | 4/6 | yes | met | yes | yes | writes that don't apply at #4–5 |
| F09 | no | 1/6 (+4 unclear) | yes | met | yes | yes | card close at #3 would hurt |
| F10 | **yes** (verifies first) | 4/4 | yes | not met (unverified) | no | mixed | reads before verification would breach policy |
| F11 | no | 4/6 | yes | met | yes | yes | – |
| F12 | no | 3/6 | yes | met | yes | yes | out-of-scope writes lower in the list |
| F13 | no | 4/6 | yes | met | yes | yes | a statement-credit write at #2 |

## What it shows

These are one reviewer's judgments at 13 points **selected by the trigger itself** from existing traces. They describe those points; they do not estimate how often the failure occurs in general, and no intervention was executed, so no benefit was measured.

1. **The failure recurs among these selected firing points.** The reviewer judged the draft inappropriate at **11 of 13** (appropriate at F05 and F10):
   - at 9 (F03, F04, F06, F07, F08, F09, F11, F12, F13) a documented agent tool covered the request;
   - at F02 the draft transferred without the documented first step (`emergency_credit_bureau_incident_transfer_1114`);
   - at F01 the draft transferred when a documented customer self-service tool (`submit_cash_back_dispute_0589`, doc `credit_cards_(general)_003`) covered the request.
2. **The check's suggestions are uneven.**
   - **At 5 (F08, F09, F11, F12, F13)** the reviewer judged the first suggestion applicable and authorized now; all five are lookups.
   - **Mixed at 6** (F02, F03, F04, F06, F07, F10).
   - **No at 2** (F01, F05): the only name is the rewards write.
3. **Harm risk at 5/13.** The first named tool is a write that does not apply or whose prerequisites are not met (F01, F03, F04, F05, F07). The observed permission rules would not stop most of these: they check only a verification log and the clock.
4. **The two appropriate drafts (F05, F10) are exactly where the check would have interrupted a correct reply.** That is a cost of firing on every denial.

### Reconciliation of the counts (corrected after the review of `4b63830`)
The first version of this file said "inappropriate at 10 of 13; a documented tool covered the request at 9", while its own table has 11 "no" rows. The per-row labels were rechecked against the reviewer's full per-point report, and **the table was right**:
- The reviewer's one-line summary said "10 of 13: 9 … and F02". Its per-point section and its summary table both label **F01** inappropriate too: a transfer when a customer self-service tool covers the request.
- F01 was left out of the summary sentence, most likely because the covering tool is a customer tool, not one the check could name. The earlier headline copied that sentence.
- Two other summary lines in the reviewer's prose also disagree with its table:
  - "help at 6, partly at 5" is 5 and 6 in the table;
  - "harm risk at F01, F03, F05, F07" omits F04, whose first tool is an unfreeze write with unmet prerequisites and applicability unclear.
- The counts above come from the per-row labels, and the harm-risk definition is stated in item 3. F02's first tool (`initial_transfer_to_human_agent_1822`) has type `generic`, not `write`, so it is not in the harm-risk count.

## Decision (principal engineer)

- **`locked_named_tool_before_denial_or_transfer` v1 is not ready for a paid test (N001).** It stays in the code (off by default) with this record.
- **Next candidate, to be evaluated offline first:** name only **read** tools, and fire only after a verification log exists.
  - *Rationale:* at every point where the reviewer judged the first suggestion applicable and authorized, it was a lookup. Every harm-risk point had a write first. F10 fired before verification.
  - Offline, this would have removed the harmful first suggestions at F01, F03, F04, F05 and F07, and the premature firing at F10. That is an inference from this table, not yet measured.
- It is **not** implemented in this round: the review asked for no new experiments during these fixes.
- **After the review of `4b63830`:** it stays a candidate and is **not built until D001 has run**, since clearer interface instructions may address enough of the discovery failure. If it is built, it must also:
  - separate public policy searches and verification-enabling lookups from reads of protected customer data (a verification log does not authorize reading a particular customer's data, the same binding gap as the write rule);
  - check applicability to the current request;
  - describe the log requirement as the limited prerequisite it is;
  - leave required transfers and requests for missing information alone.
- The reviewer's labels are one reader's judgment, and 13 points are a small set. They inform the design; they are not a measured effect.
