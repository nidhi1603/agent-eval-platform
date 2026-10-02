# Where failed conversations first go wrong: an offline tally (2026-10-01, $0)

**Question (from the P002 review).** Before choosing the next intervention: across failed conversations, what is the first actionable mistake? Was the rule and evidence already available? Could a deterministic check without the answer key catch it? Counts are by CONVERSATION and by distinct TASK, so one long conversation, or one task repeated, does not dominate.

## Corpus and method

**Corpus:** every failed conversation (official reward 0 or none) in H008, H009 and P001. That is 79: gpt-5-mini, medium effort, alltools, standard agent and harness v3.1/v3.2 arms.
- **Audited (56):** the H008/H009 safety audit had already identified the earliest consequential error. Readers mapped it to a class and could move it to an earlier error.
- **Full read (23):** H008/H009 failures with no audited action (11), plus all of P001 (12).
- **Excluded:** P002 continuations (selected states) and the held-out split.

**Method:**
- Instructions (`INSTRUCTIONS.md`) and the corpus were committed before any reading.
- **Two independent readers** labelled every conversation, blind to arm and batch.
- **Agreement on the first-mistake class: 60 of 79.** 8 of the 19 differences are one convention split: a transfer read as the act (TRANSFER) versus the never-retrieved document read as the root cause (RETRIEVAL). The differences were not adjudicated, since this tally ranks; it does not decide a verdict. Both readers' counts are in `tally.json`.

**Process notes.**
- One reader opened `export.py`, which shows how the corpus was built but nothing about any individual conversation.
- Another read the domain prompt files and grepped the tau2 tool source.
- Tool outputs in the full-read files are truncated at 1,500 characters, so some monthly sums could not be recomputed.

## Answer to the review's provisional candidate: unsupported completion claims

**Claims are not the first failure.**
- Unsupported completion claims appear in 21 (reader A) or 23 (reader B) of the 79 failed conversations.
- In all but one, the first claim comes AFTER an earlier consequential mistake.
- One conversation (task_017) has a claim at the first-mistake turn, which only one reader classed CLAIM.

A claims check would improve honesty in about a quarter of failed conversations. It would not have prevented these task failures.

## Recurring first mistakes (`patterns.py` → `patterns.json`)

| Pattern | Conversations | Tasks | Notes |
|---|---|---|---|
| Cash-back discrepancy: the agent rewrote rewards itself, or transferred, instead of handing over `submit_cash_back_dispute` | 12 | 017, 019 | "Who acts" error: the documented path is a customer-side tool |
| Credit-limit increase submitted, then stopped ("decision by email") without the remaining checks and approval | 8 | 050 | Treats a pending request as the end of the procedure |
| Account closure without the retention protocol | 8 | 047 | |
| No documented procedure: the agent invented one ("according to our docs") instead of saying so and transferring | 8 | 012 | |
| Transfer reason code, or transferring instead of acting | 8 | 004, 023, 058, 089 | See also the transfer check below |
| Wrong computed amount (ATM temporary maximum; rebate spend windows; APY stacking) | 8 | 019, 023, 089, 095 | Some are contested; truncated outputs limit checking |
| Gave a referral tool after the program's end date | 6 | 015 | The only recurring TIMING failure |
| Required emergency or customer-side tool not used | 4 | 031, 035 | |
| Fraud alert cleared right after the customer reported an unauthorized charge | 2 | 087 | P001 only |
| Unassigned (interruptions, customer-simulator issues, single cases) | 15 | | |

**Availability, for the 60 agreed conversations (`tally.json` agreed_detail):**
- **Policy step skipped or misread (16):** the governing rule AND the needed evidence were already in context in all 16. This is a knowledge-to-action gap, not retrieval.
- **Detectable without the answer key:** "yes" by both readers in only 3 of 60 conversations (2 transfer, 1 arguments); "partial" for most. A generic deterministic check catches few of these first mistakes outright.

**Transfer check (deterministic, using the answer key for analysis only):**
- On tasks whose reference actions include a transfer, **0 of 15 conversations used the expected reason code**.
- 20 conversations transferred on tasks that expect no transfer.
- Both readers marked a transfer situation as present in 41 to 43 conversations and mishandled in 36.

**Fraud and waiting periods.** Neither is a recurring first failure in this corpus:
- fraud: 2 conversations, one task;
- timing: one recurring pattern, an expired referral program on one task (6). Other timing slips, such as the 48-hour replacement wait, came after earlier failures.

## What this suggests (for review; nothing built)

1. **Transfer decisions: when to transfer, and with which reason code.** The most cross-cutting first failure:
   - first mistake in at least 16 conversations across at least 6 tasks (the transfer pattern, plus the cash-back transfers);
   - a wrong or missing reason code in every transfer-expected conversation;
   - many transfers where none was expected.

   A deterministic check is partly possible without the answer key. The bank's transfer-reason tiering document exists in the knowledge base, so a check could require it to be retrieved and the chosen code to match a documented tier for the situation. Choosing the tier itself needs judgment.

   Prior evidence for caution: the v3.1 transfer hold made the agent search, but in P002 it re-sent the same wrong code.
2. **Procedure completion: who acts, and finishing the documented steps** (cash-back handover, CLI completion, retention protocol).
   - The largest by conversations (about 28), but concentrated in 4 tasks.
   - The rule and evidence were available in every agreed case.
   - Caution: harness v2's procedure checklist was tried in H002 and gave no benefit (0/20) at +42% cost. A new attempt should explain why it would differ.
3. **Not first:** unsupported claims, fraud handling, waiting periods.

**Limits.**
- 79 failed conversations from about 18 dev tasks, concentrated by task: each H008/H009 task appears about 8 times.
- Pattern definitions were written after reading the labels, as a summary of them.
- Disagreements were not adjudicated.
- Development data only; the held-out split is untouched.

## Files

- **Inputs:** `export.py`, `INSTRUCTIONS.md`, `audited_items.json`, `convs/`, `parts.json`.
- **Labels:** `labels_{audited,part1,part2}_{A,B}.json`.
- **Analysis:** `tally.py` → `tally.json`; `patterns.py` → `patterns.json`.
