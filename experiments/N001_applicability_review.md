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

1. **The targeted failure is real and common.** At 10 of 13 points the agent's denial or transfer was inappropriate; at 9 of those, a documented tool covered the request.
2. **The check's suggestions are uneven.**
   - **Clearly helpful at 5/13:** the first named tool is applicable *and* authorized now (F08, F09, F11, F12, F13, all lookups).
   - **Mixed at 6.**
   - **Unhelpful at 2** (F01, F05): the only name is the rewards write.
3. **Harm risk at 5/13.** The first named tool is a write that does not apply or whose prerequisites are not met (F01, F03, F04, F05, F07). The observed permission rules would not stop most of these: they check only a verification log and the clock.
4. **The two appropriate drafts (F05, F10) are exactly where the check would have interrupted a correct reply.** That is a cost of firing on every denial.

## Decision (principal engineer)

- **`locked_named_tool_before_denial_or_transfer` v1 is not ready for a paid test (N001).** It stays in the code (off by default) with this record.
- **Next candidate, to be evaluated offline first:** name only **read** tools, and fire only after a verification log exists.
  - *Rationale:* every clearly helpful point had an authorized lookup first. Every harm-risk point had a write first. F10 fired before verification.
  - Offline, this would have removed the harmful first suggestions at F01, F03, F04, F05 and F07, and the premature firing at F10. That is an inference from this table, not yet measured.
- It is **not** implemented in this round: the review asked for no new experiments during these fixes.
- The reviewer's labels are one reader's judgment, and 13 points are a small set. They inform the design; they are not a measured effect.
