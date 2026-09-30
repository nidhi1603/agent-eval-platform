# H004 preparation: dependency-following tool search ($0)

**What it is:** `bench/depsearch.py`, the harness option `{"dep_search": true}` (see its docstring).
- After a knowledge-base search names an agent tool that takes an identifier the agent does not hold yet, the harness searches the tool documents for what provides that identifier.
- The new documents are appended to the model's own copy of that search result. The benchmark trajectory is unchanged.
- The mechanism and parameters are the offline probe's (`research/h002/tool_retrieval_probe.py`). Rankings are verified identical in the tests.

## Offline evidence

| Check | Result |
|---|---|
| **Tests** (`tests/test_depsearch.py`, 12) | A missing identifier triggers the search; held identifiers and `user_id` do not. Documents are never repeated. Each parameter is searched once per conversation, and the query budget caps a conversation. The model sees the added documents; the trajectory does not. The adapter offers tools named only in the added documents. The verification and identifier checks still hold and withhold an unverified write. |
| **Reference controls** (`research/harness_v1/reference_controls_v1dep.json`) | 30/30 same reward; 0 hard-check firings; 0 search errors. |
| **Replay over 58 saved conversations** (`dep_replay.py`, `dep_replay.json`) | Required tool-document recall 0.40 → 0.53 (the probe: 0.39 → 0.52). Doc `_018` is reached through the search in 31 conversations, `_028` in 5, `_016` in 5. |

### Known costs and limits

- **It fires almost always.** The reference controls ran 112 queries in 30/30 tasks and added 170 documents. Agent input tokens are 1.20× v1's.
- **In the replay:** about 2,200 tokens and 2.7 irrelevant documents added per conversation, and the 4-query budget was used up in 29 of 58 conversations.
- **Doc `_009` is never reached** (0 of 52 conversations that needed it). It is not special-cased.
- **The v1 checks now see more.** v1's `search_before_giving_up` advisory lists tools named in any search result it has seen, which now includes the added documents. v1's code is unchanged; its input is what differs.
- **Evidence availability only.** A replay cannot show what the agent does with the extra documents. H004 measures that.

**The plan:** `experiments/H004_plan.json`, frozen and not run. It needs Nidhi's approval in chat: "run H004 with $12.00".
