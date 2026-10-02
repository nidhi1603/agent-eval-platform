# Confirmation pass over P004's fresh standard-agent failures ($0, 2026-10-02)

**Scope.** The 27 baseline conversations in P004 that failed. The pass answers the review's three questions mechanically: which of each task's required documents reached the model, from the agent's own view (`bench/kb_evidence.py`, full or partial). Required documents and reference actions are used only to score.
**Caveat.** These are new conversations on familiar development tasks, not independent validation data. No reading or labelling was done.

## 1. Do missing-procedure failures recur? Mechanically, yes; but "missing" is broad

- **24 of 27** failed conversations never reached at least one required document.
- Required-document lists are long (up to 21 per task), so "some document missing" is nearly universal and is NOT evidence of cause.
- **Recurrence on the same tasks** (earlier H008/H009 standard-agent failures):
  - task_004 and task_012: doc 042, the reason codes;
  - task_019: doc 003 (cash-back dispute) and the card documents;
  - task_031: doc 013;
  - task_058: doc 009;
  - task_047, task_050, task_089: overlapping sets.
- **Missed most across different tasks:**
  - doc 009 "Internal: Retrieving Customer Account Information": 6 tasks;
  - doc 018 "Internal: Retrieving Bank Account Transaction History": 5 tasks;
  - product documents, mainly in multi-card comparison tasks (019, 027, 028, 029, 069, 080).
- **Named but never read:** in 7 tasks (012, 027, 028, 069, 091, 092, 094), at least one missing document's NAME reached the model (in a listing), but its text never did. In task_028, all 11 required documents were in that state.

## 2. Procedures available, yet failed (abandonment or misapplication)

**3 of 27** (task_015, task_041, task_066) reached every required document and still failed. Retrieval cannot address these.

## 3. Reach

- **Transferred although the task's reference has no transfer:** 13 of 27 failures, on **13 different tasks**: 027, 028, 029, 058, 061, 072, 077, 085, 087, 089, 091, 094, 095.
  - All 13 also had a required document missing.
  - This pattern reaches many more tasks than reason codes (2).
  - These transfers were NOT policy-reviewed. A missing document is not shown to be the cause.

## Prior evidence on the obvious mechanism (must be weighed)

H008 already tested "retrieve before giving up": harness v3.1's capability search plus a once-only transfer hold.
- It surfaced doc 009 (the account-lookup document) in 16 conversations, and the lookup tool was offered in 16.
- The agent called the lookup tool in only 6.
- v3.1 retrieved more required documents but passed FEWER database-task conversations than the standard agent.
- H008's candidate explanation: acting within the documents, not finding them, was the bottleneck. That comparison was confounded with the tool adapter, and one task was lost to an interaction between the hold and a decoy tool.

## Implication for choosing a next candidate

- **Reach exists:** 13 tasks transfer instead of acting with a required document unread.
- **The direct mechanism, retrieving the document, has prior negative evidence** at the step after retrieval: using the procedure.
- A new candidate here would need a credible reason to succeed where v3.1 did not. At minimum, a $0 feasibility check: from conversation evidence alone (the customer's request before the transfer), does retrieval surface the missing governing procedure in most of the 13?

Files: `p004_baseline.py`, `p004_baseline.json`.
