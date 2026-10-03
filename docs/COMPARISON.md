# What this project adds to the standard tau2 setup, and what it does not

**Scope.**
- "Standard setup" means tau2-bench v1.0.1's standard `LLMAgent` and runner, as used in our experiments. It is not every capability available anywhere in tau2.
- This comparison comes from our own implementation and experiment records, not from a fresh audit of the upstream source.
- A feature we added is not automatically something upstream cannot do.

**Bottom line.**
- Our harness adds explicit controls around the model, and the evaluation layer adds ways to test those controls.
- These have not produced a proven overall score improvement. Some additions worked locally, some introduced problems, and some were rejected.
- We have more explicit controls and diagnostic capability. We have not shown a better banking agent overall.

## Runtime harness: controls around the model

| Capability | Standard setup | What ours adds | Evidence | Limits |
|---|---|---|---|---|
| **Evidence-based identity verification** (v3.2 `verification_evidence`) | the model is instructed to verify the customer | code allows `log_verification` only when the customer independently supplied at least two identity fields that match the retrieved record. Values the agent showed first and the customer echoed back do not count | unit and end-to-end tests. It held the 10 saved unsupported verifications D005 selected. Three echo verifications found in the H008/H009 audits motivated it | in the live P001 pilot, every verification passed first time, so the check never had to block. It covers four identity fields only. The benchmark's own `log_verification` accepts invented identities |
| **Tracking what the customer actually saw** (provenance by delivery) | conversation history alone | separates messages the customer received from drafts the harness intercepted. Only delivered messages can make a value "shown by the agent" | `make demo-provenance`: after a leaking draft is intercepted, the customer's own later evidence still counts. Regression tests fail under the old rule | proves the scripted behaviour and the fix, not general verification security or live recovery reliability |
| **Checking outgoing identity disclosures** (`disclosure_check`) | the model is instructed not to disclose information before verification | an output check intercepts recognised date-of-birth, email, phone and address values of an unverified customer before delivery | caught 4 of 4 D005 leaks. It would have caught 13 of 1,301 saved agent messages. Blind model review agreed 23 of 23. In P002, 6 of 8 selected continuations reached valid verification and resumed work after it intervened | narrow coverage: recognised formats of four fields. It misses confirming that a field matched, confirming an account exists, and revealing the internal user ID, all found by reviewers. It never fired in the live P001 pilot |
| **Explicit feedback when an action is held** (v3.1 transfer hold) | no custom hold | feedback says the action did NOT execute, and what the next permitted step is; held at most once | false "transfer under way" claims fell from 26 of 27 to 2 of 27 in the selected single-reply test (D004). 0 unsupported transfer statements in H008 and H009. This repaired our own earlier hold, which had produced 30 such statements in 27 of 84 harness conversations | in full conversations, the hold changed no decisive action for the better. It caused one loss in H008 by interacting with capability search |
| **Direct access to discovered tools** (adapter) | the model follows the benchmark's discover-unlock-call workflow | discovered tools are offered as ordinary callable functions, with the benchmark's own definitions | official grades are the same through the wrappers and through the adapter (A001). Discovered-tool use rose about 16× (H002) | not established as beneficial overall. Greater exposure came with more violations (H008: 11 tools in reach on average vs 0.6) |
| **Checks before execution** | policy compliance depends on the model's decisions | configurable hard checks: verification before writes, verification time from the clock, identifiers the agent has observed. Duplicate writes are checked in harness v2 only | makes selected requirements enforceable in code. All 30 reference solutions keep their reward, with 0 hard-check firings | coverage is incomplete. v3.1 had more write-policy violations than the standard agent (H008: 11 in 7 conversations vs 3 in 2), through newly reachable tools the checks did not cover. Adding dependency search raised violations from 8 to 20 (H004, both arms harnesses) |

## Evaluation infrastructure

| Addition | What we built beyond the setup we started with |
|---|---|
| **Budget enforcement** | reservations before every model call; caps per conversation and per batch; settlement at the provider-billed cost; spend from interrupted runs still counted after a resume |
| **Answer-dependence testing** | re-executes agent-visible outputs against a copy of the task with the answer key erased, to check whether they change. This found the tool-listing flaw reported upstream (sierra-research/tau2-bench#574) |
| **Controlled experiment management** | frozen plans, decision rules written in code before the run, matched and balanced comparisons, and the settings the running agent actually used, recorded per conversation |
| **Targeted replay probes** | reconstruct a saved decision point and compare feedback variants without paying for complete conversations. Before any call, a check confirms the replay matches the original (same tool-list hash, history aligned with the original call log) |
| **Harness-state restoration** | builds on tau2's own replay (database and simulated customer) by restoring the harness agent's private history and unlocked tools |
| **More detailed outcome measurement** | separates attempted actions, successful receipts, reference-matched actions, policy violations and unsupported completion claims |
| **Review and reproducibility workflows** | blinded exports, separate model readers (not human annotators), adjudication, corrections kept in the record, and a runnable provenance demo |

## What to show first

1. **Evidence provenance:** `make demo-provenance`.
2. **Feedback after a held action:** 26 of 27 → 2 of 27, with its full-conversation limit.
3. **Reproducible evaluation:** frozen plans, spend control, answer-dependence testing, and the defects these caught ([RESULTS.md](RESULTS.md)).

Present each with its limit. That keeps the comparison credible.
