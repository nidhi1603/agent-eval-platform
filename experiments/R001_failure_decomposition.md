# R001: why the 19 live conversations failed (2026-09-28, $0)

- **Method.** Each saved live conversation (S001, S002, S003; gpt-5-mini low effort, BM25) was compared with its dev task's `required_documents` and reference actions, and classified by the **first reference action it failed**.
  - A match means the same requestor, the same tool, and the same key arguments. For discoverable-tool calls, the inner tool name and parsed inner arguments are compared.
- **Rules, applied in order:** USER-SIM → ARGUMENT → RETRIEVAL → TOOL-USE → POLICY → OTHER. Definitions are in `docs/PHASE2_RESEARCH.md` §2.
- **Reproduce:** `research/failure_decomposition/analyze.py` and `taskstats.py`. Only dev tasks are read.
- **Who did it:** an independent analysis by a subagent; it was not told the hypothesis.

All 19 have reward 0.

| Task / arm | Required-doc recall | First failed reference action | Primary cause | Evidence (message index) |
|---|---|---|---|---|
| 015 baseline | 4/5 | the customer's referral-link call uses the wrong card | POLICY | doc 009 at [3] requires a documented referral programme; the tool was handed over anyway at [4] |
| 029 baseline | 1/10 | hand over `submit_cash_back_dispute_0589` | RETRIEVAL | tool never retrieved; one search; transferred at [23] |
| 035 baseline | 1/1 | unlock `emergency_credit_bureau_incident_transfer_1114` | TOOL-USE | name seen at [3] and searched for by name at [4] and [6]; plain transfer at [8] |
| 047 baseline | 5/12 | dispute-history lookup | RETRIEVAL | dispute and replacement tools never seen; Business Platinum docs not retrieved; account closed at [30] |
| 069 baseline | 4/19 | open the new account | RETRIEVAL | product docs not retrieved; could not confirm requirements ([22], [26]) |
| 080 baseline | 5/19 | account lookup | TOOL-USE | lookup and freeze tools seen at [3] and [17]; "can't freeze" at [22]; transfer at [24] |
| 089 baseline | 3/10 | verification log with an invented time | ARGUMENT | never read the clock; "2026-09-27 17:06:00 UTC" at [8] |
| 019 baseline | 1/6 | verification log missing | USER-SIM (ambiguous) | the customer withheld her full name and quit at [9] |
| 019 denial_check | 1/6 | hand over the cash-back dispute tool | RETRIEVAL | tool never seen; wrote reward corrections directly instead ([24], [26]) |
| 031 baseline | 1/3 | hand over `get_card_last_4_digits` | RETRIEVAL | doc never retrieved; one search |
| 031 denial_check | 1/3 | same | RETRIEVAL | the customer asked for a lookup tool ([15], [19]); no re-search |
| 066 baseline | 5/15 | account lookup | RETRIEVAL | tool never seen; wrong products recommended at [16]; transfer at [20] |
| 066 denial_check | 4/15 | account lookup | TOOL-USE | seen at [3]; "cannot access account-level tools" at [20] |
| 087 baseline | 1/10 | verification log with an invented time | ARGUMENT | "2026-09-27 00:00:00 UTC" at [10]; transfer at [22] |
| 087 denial_check | 5/10 | account lookup | RETRIEVAL (ambiguous with TOOL-USE) | account lookup never seen; card tools seen at [3], but capability denied at [14] and [32] |
| 094 baseline | 6/13 | account lookup | TOOL-USE | "those specific agent tools aren't exposed here" at [16] |
| 094 denial_check | 3/13 | account lookup | TOOL-USE | seen at [3]; denied at [14]; transfer at [18] |
| 095 baseline | 7/15 | account lookup | TOOL-USE | names the tool and says it has no access at [26] |
| 095 denial_check | 10/15 | account lookup | TOOL-USE | searched for the tool by name 3 times; transfer at [38] |

**Totals:**

| Primary cause | Conversations |
|---|---|
| Retrieval | 8 |
| Tool use | 7 |
| Argument | 2 |
| User simulator | 1 |
| Policy | 1 |

- **Recall:** 68 of 200 required documents were retrieved (0.34).
- **Searching:** 8 of 19 conversations made a single search.
- **Transfers:** 11 conversations transferred to a human; the reference transfers in 1.
- **Most conversations have more than one sufficient cause.**

**Across the 30 dev tasks:**
- a discoverable agent tool is needed in 21;
- a customer tool is handed over in 9;
- verification is logged in 26;
- a transfer is expected in 4;
- 27 are graded on database state and 3 on actions.

**Adapter-only bound (judgement):**
- task 035 likely passes;
- 094 and 095 are possible but need exact APY and credit amounts from documents that were not retrieved;
- the rest stay blocked.

That is about **1 of 19 plausible, 5 at most**.
