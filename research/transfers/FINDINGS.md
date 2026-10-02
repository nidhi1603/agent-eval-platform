# Transfer decisions: an offline decision table (2026-10-01, $0)

**Question (from the tally review).** Before choosing a transfer intervention, separate three things at each decision point: did the agent lack the rule (retrieval), see it and misapply it (decision), or decide correctly and pick a wrong code (code validation)? Successful transfers and appropriate non-transfers are included, so a check is not designed only against failures. Policy-based judgment is kept apart from the answer key.

## Corpus and method

**Decision points (68)**, from EVERY H008, H009 and P001 conversation, successful ones included (`export.py`):
- **45 transfer calls;**
- **14 "customer asked for a human" points with no later transfer.** These were picked by a keyword rule that proved loose: 10 of the 14 were judged not real decisions, mostly words used after a transfer had already happened.
- **9 conversations on a transfer-expected task with no transfer;** 3 of these were judged not real decisions.
- 19 of the 68 points are in conversations that passed. **55 are real decisions.**

**Readers:**
- Two independent readers labelled every point, blind to arm, outcome and the task files. They judged from the bank's policy (`prompts/`, knowledge-base documents; reason-code tiers in doc 042) and what the agent could see.
- Record, transaction and action results were complete. Retrieval outputs were clipped, with every document id listed; readers opened the full documents on disk.
- **Agreement:** decision correct 61 of 68, observed mistake 60, suspected cause 58. A blind adjudicator settled the 14 points with a disagreement on those fields (`adjudication.json`).
- The adjudicator also tightened one rule: content the agent actually received from a search hit counts as retrieved; a filename in a directory listing does not.

**Answer-key comparison (separate, in `KEY`).**
- task_035's reference transfer checks no arguments (compare_args `[]`), so any code passes there. Only task_004 and task_012 grade the reason code.
- This **also corrected the earlier failure tally.** Its "0 of 15" counted task_035 transfers as wrong; it is now "0 of 13 failed conversations on tasks that grade the code" (`research/post_verification/`).

## Results (55 real decisions)

| Observed mistake (what) | Points | Suspected cause (why) | Tasks |
|---|---|---|---|
| Transferred instead of acting | 19 | rule never retrieved 10; rule seen, misapplied 7; fact not obtained 2 | missing rule: 019 ×8, 017, 089. Misapplied: 058 ×3, 047, 095, 017, 023 |
| Wrong reason code | 9 | rule never retrieved 7; misapplied 2 | 035 ×4, 004 ×4, 019 |
| Other | 11 | misapplied 9; other 2 | 035 ×7 (required emergency tool skipped before transferring; repeat transfers), 012 ×3 (invented procedure), 050 |
| Failed to transfer | 4 | misapplied 4 | 004 ×2, 012 ×2 (customer consented; guideline 5 in the system prompt) |
| None | 12 | | |

**Successful conversations (15 decision points).**
- 8 were correct with no mistake.
- 4 transfers passed with a code the readers judged wrong under policy. All are task_035, where the grade ignores the code.
- 2 were repeat transfers; 1 was transferred instead of acting.
- A reason-code check would have changed those 4 codes. Under the grader that is harmless; under policy it is a fix.

**Reason code against the tier document (doc 042), across all 45 transfer calls:**

| Tier document content in context before the call | Code correct by policy | Wrong | Unclear |
|---|---|---|---|
| yes (10) | **8** | 2 | 0 |
| no (35) | 8 | 12 | 15 |

The "in context" signal is deterministic (`tier_doc_content_seen_before`): the document's title or tier text appears in an earlier tool result. It can also match an index listing, so 10 is an upper bound. In the 30 transfers with a clear code, codes were right in 8 of 10 when doc 042 had been seen and 8 of 20 when it had not. This is observational: tasks differ between the two groups, so it does not show cause.

**Policy against answer key** (the 9 transfers where the key grades a code): they agree on all 9 (5 right, 4 wrong). For the other 36 transfers the key does not grade the code.

## Separating the mechanisms (the review's three cases)

1. **Missing rule, so retrieval.**
   - Transferring instead of acting when the governing procedure was never retrieved: 10 points, 8 of them on task_019, the cash-back dispute procedure (doc 003).
   - Wrong codes without the tier document: 7.
2. **Rule seen, misapplied, so decision-making.**
   - Transferring instead of acting with the rule in context: 7, across 5 tasks.
   - Skipping the required emergency tool before the transfer: task_035.
   - Not transferring after consent: 4.
   - Invented procedures: task_012.
3. **Correct decision, wrong code, so code validation.** 9 wrong codes, 7 of them where the tier document was never retrieved.

## Which mechanism to address (for review; nothing built)

**Proposal: reason-code grounding.** Before a `transfer_to_human_agents` call executes, if the tier document's content is not yet in the agent's context, the harness puts doc 042 into context. It then asks the agent to re-choose the code from the highest tier that applies.

**Why this one:**
- The cause is mostly missing information (7 of 9 wrong codes), and the remedy is specific: one known document, not a generic "search first" hold.
- It is deterministic and needs no answer key.
- It cannot obstruct a correct decision to transfer: the transfer still happens, possibly with a different code.
- The evidence: codes were right in 8 of 10 transfers when the document had been seen.

**Why not the others first:**
- Transferring instead of acting is the largest group, but its causes split. Its biggest part is one task's procedure (task_019, doc 003), which needs task-specific retrieval.
- The misapplied cases are spread across tasks and judgment-heavy. Both readers had judged only 3 of 60 tally cases fully detectable without the answer key.

**Expected effect, stated narrowly:**
- It can only affect the code, and only task_004 and task_012 grade the code: 9 graded transfers in this corpus.
- It will not fix transferring instead of acting, skipped emergency steps, or failures to transfer.
- **The P002 caution applies:** the v3.1 transfer hold made the agent search, but it re-sent the same wrong code. So grounding must put the tier document's TEXT in context and ask specifically for the code. Re-asking alone is not enough.

**Suggested test, before any live run:** a next-message probe at the existing wrong-code transfer points, like D005. Give the model doc 042's text and the request to re-choose the code, and measure the code it picks. This needs a small paid probe and its own plan.

## Files

- **Inputs:** `export.py`, `INSTRUCTIONS.md`, `points/`, `parts.json`.
- **Labels:** `labels_part{1-4}_{A,B}.json`, `adjudication_items.json`, `adjudication.json`.
- **Analysis:** `tally.py` → `tally.json`.
