# What successful standard agents do: a study of public leaderboard trajectories (2026-09-30, $0)

**Source.** Sierra's public trajectories for the standard agent under alltools: GPT-5.5 xhigh (pass^1 44.6) and Qwen 3.8 Max (55.2), 97 tasks × 4 trials each. Downloaded with Nidhi's permission to `~/Desktop/tau2-public-trajectories` (outside this repository; sha256 in EXPERIMENTS.md).

**Held-out rule.** Only the **30 development tasks** are read. Conversations on the 67 held-out tasks are dropped at load time and never inspected.

**Scripts:** `analyze.py`, `how_found.py`, `query_wording_probe.py`. They use this repo's own `bench/metrics.py` and `bench/kb_evidence.py`.

## 1. Our pilot tasks were mostly ones the best models also fail

Dev tasks are bimodal (passes of 4 trials, GPT-5.5 / Qwen):
- **Solved by both, at least 3 of 4 each (12 tasks):** 089, 047, 050, 058, 017, 035, 031, 023, 012, 019, 004, 015.
- **Passed 0 times in 8 by either (9 tasks):** 027, 066, 091, 092, 087, 085, 061, 069, 029. Four more were passed at most once (077, 095, 101, 041).
- **Our 10 pilot tasks (H002, H004):** only **3** are in the solved group (089, 058, 023). The other 7 were passed in 3 of 56 top-model attempts.
- **Pass rates on our pilot tasks:** GPT-5.5 0.33, Qwen 0.35. On the other 20 dev tasks: 0.45 and 0.68.
- **Consequence:** H002–H005 measured a harness mostly on tasks where no agent succeeds. Every pass we saw except one was on 023 or 058; the exception was task_061 in H004's search arm, a task neither top model passed.

## 2. The gap between gpt-5-mini and the top models is reaching the right documents

Per conversation, dev tasks:

| | GPT-5.5 pass / fail | Qwen pass / fail | gpt-5-mini standard (H005, n=4) | gpt-5-mini v1 (H005, n=4) |
|---|---|---|---|---|
| Required-document recall (full) | 0.84 / 0.79 | 0.84 / 0.83 | **0.38** | **0.44** |
| Documents read in full | 41 / 57 | 44 / 64 | 39 | 40 |
| BM25 / dense / shell calls | 4.8 / 2.3 / 3.7 (pass) | 3.9 / 3.8 / 10.0 (pass) | 8.3 / **0** / 4.0 | 6.8 / **0** / 6.8 |
| Tools unlocked | 1.9 / 4.0 | 2.1 / 4.9 | 0.25 | (adapter) |

- **The top models reach about 0.84 of the required documents whether they pass or fail.** Retrieval is not what separates their passes from their failures. Their failures are on long workflows: discoverable writes matched are 171/309 in GPT-5.5's failed conversations, against 51/51 in its passes.
- **gpt-5-mini reads as many documents, but the wrong ones.** 56% of required documents never reach it (the top models: 15–16%).
- **The account-lookup document (`_009`):**
  - reached in **52/60** (GPT-5.5) and **51/60** (Qwen) of the conversations that need it;
  - reached in **0/3** of gpt-5-mini's;
  - GPT-5.5 reaches it through **plain BM25** in 40 of the 52.

## 3. How they find them: they search for the capability, not the situation

- **Query wording:** 35% (GPT-5.5) and 34% (Qwen) of their search queries use the knowledge base's procedural words (internal, tool, lookup, retrieve). gpt-5-mini: 3%.
- **Example, task_089** (4/4 for both top models; never passed by us in any experiment):
  - GPT-5.5 searches "Internal tool lookup checking accounts by user id account_id …" with BM25 and dense together. It unlocks `get_all_user_accounts_by_user_id_3847` and `get_debit_cards_by_account_id_7823`, reads the customer's accounts, cards and transactions, then finds and calls the limit-increase tool.
  - gpt-5-mini (standard) greps product documents by the customer's words, reads the right limit-increase document, and **transfers without unlocking any tool**.
  - harness v1 retrieves the card-lookup tool but not the account lookup. It asks the customer for an account id they do not have, and the customer asks for a transfer.
- **A wording prefix alone does not fix it** (`query_wording_probe.py`). Prefixing gpt-5-mini's own 113 conversations' queries with "Internal tool lookup procedure:" moves recall from 0.39 to 0.43, and `_009` from 16/90 to 21/90.
- **What gets searched for is what matters** (BM25, tau2's index):
  - "retrieve customer account information tool user_id" → `_009` at **rank 1**;
  - "account lookup tool" → rank 2;
  - "which accounts does this customer have" → not in the top 10.

## 4. What this implies (hypotheses for the next design; not yet tested live)

1. **Evaluate where success is possible.** A comparison on the 12 dev tasks that both top models solve can detect an improvement. One on our pilot set largely cannot. The selection uses public results of other models, not our own outcomes.
2. **Target the procedure the winners follow:** verify; **look up the customer's records with the lookup tools** before asking the customer for identifiers; **search for the tool that does the needed thing**; use BM25 and dense together.
3. **v1's existing strengths are complementary.** It already makes discovered tools callable (gpt-5-mini barely unlocks: 0.25 per conversation). What it lacks is getting the right tool documents retrieved.

## Limits

- Two models, the 30 dev tasks, and only 4 of our own alltools conversations per arm (H005, stopped early).
- These are descriptive contrasts between different models. They do not show that giving gpt-5-mini the same search behaviour will produce the same results.
- The trajectories come from tau2 commit fc0055d; ours use b7ea907. Both are 1.0.1.
