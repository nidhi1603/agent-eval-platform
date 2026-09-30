# Harness v3: v1's checks + capability search (2026-09-30, $0)

**Code:** `bench/capability.py` (triggers and queries) and `bench/harness.py` (`{"version": "v3"}`). v1 and v2 are unchanged.

**Why:** `research/public_trajectories/FINDINGS.md`.
- The top standard agents reach about 0.84 of a task's required documents; gpt-5-mini reaches about 0.4.
- They get there by searching for the capability they need ("tool to …"), and by reading the customer's records with lookup tools instead of asking the customer for identifiers.

## What v3 does

| Trigger | When | What the harness does |
|---|---|---|
| `after_verification` | A successful `log_verification` has arrived, and no record lookup has shown an account id | Searches "tool to retrieve all of the customer's accounts by user id" |
| `before_asking` | The agent's reply would ask the customer for an account, card or transaction identifier that no record lookup has shown | Does **not** send that reply; searches for the tool that provides the identifier |
| (advice) | v1's advisory before a transfer or a denial | Gains one line: search for the tool that does what the customer asked |

- **Frequency:** each kind at most once per conversation.
- **How the search runs:** through the benchmark's own search tools (KB_search, or under alltools KB_search_bm25 and KB_search_dense with k=5), as a harness turn. There is no model call, and the search is visible in the trajectory. The call and its results enter the model's history, with one line saying why the harness searched. The adapter then offers any tool the results name.
- **What the harness never does:** call a lookup tool itself, or write anything.
- **Queries:** three fixed templates; nothing per task or document. "An identifier is already known" counts only record lookups. Documents and unlock receipts mention parameter names such as `card_id:`, so they do not count (a bug caught by the end-to-end test).

## Offline evidence

| Check | Result |
|---|---|
| **Tests** (`tests/test_harness_v3.py`, 14) | Triggers and their once-only rule; known identifiers; the benchmark's own tools used; the spec; v1's advisory unchanged outside v3. End to end under bm25 and alltools: the search runs after verification; a question asking for a card number is not sent and a search runs instead; the account-lookup tool becomes callable; the model is told why; answer independence is conclusive |
| **Reference controls** (`research/harness_v1/reference_controls_v3.json`, `…_v3_alltools.json`) | **30/30 same reward, 0 hard-check firings** under both bm25 and alltools. The post-verification search fires in 26/30. Agent input tokens are 1.29× (bm25) and 1.21× (alltools) the standard agent's |
| **Replay over 113 saved gpt-5-mini conversations** (`replay.py`, BM25, top 5 counted) | The account-lookup document (`_009`) is reached in **81/90** conversations that need it (16/90 as they happened). Required-document recall 0.40 → 0.49. A trigger fires in 106/113. 4.6 documents added per conversation |

### Limits

- **The replay shows availability, not use.** Whether gpt-5-mini then uses the lookup tools and completes more tasks is what the live comparison tests.
- **The wording was chosen with knowledge of dev results.** The three query templates were written after the trajectory study showed that capability wording finds the account-lookup document on dev tasks. They are general (accounts, cards, transactions), not per task, but they were not chosen blind.
- **Customer-only identifiers.** `before_asking` can hold a question that was legitimate, for example digits only the customer has. It fires once per kind, so the agent can ask again.
- **Dense search.** It runs in the capability searches (alltools). The agent's own searches are not changed.
