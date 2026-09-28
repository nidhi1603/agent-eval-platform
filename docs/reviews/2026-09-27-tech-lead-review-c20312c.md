# Decision record: tech-lead review of `c20312c`

**Roles.** The reviewer (ChatGPT, acting as senior tech lead) reviewed the pushed code and reproduced several failures with scripted runs. The principal engineer (Claude Code) verified each claim against the code and the pinned benchmark before deciding, and recorded the decisions below. Decisions on spending and publishing are Nidhi's.

**Outcome.** All five findings were confirmed and accepted, with one partial disagreement on how to handle an unknown tool type (item 4b). No change to the architecture; the fixes are in measurement, preflight and claims. Spend: $0.

## Findings

| # | Reviewer finding | Verified how | Verdict | What changed |
|---|---|---|---|---|
| 1a | A later model error erased earlier actions (e.g. an executed rewards write) and the command still returned success | Read `continue_case`: calls accumulated in memory; the caller replaced the record on exception; `main` returned 0 | **Accept** | Records persist progressively (`run_NN.json`); an exception yields `status: error` with every proposal, call, harness event, final state, score and linked ledger entries kept; exit code 3 when any run errored or was not run. Test: unlock + rewards write + failed third model call keeps both calls and `forbidden_successful` |
| 1b | Results truncated to 600 characters before provenance, so later values were flagged as unseen | Code read | **Accept** | Full results are the evidence; a 300-character `result_preview` is separate. Test: an account ID beyond character 600 is not flagged |
| 2a | Completion scored from calls, not final state | Code read; freeze then unfreeze scripted | **Accept** | `completion_state` read from the environment after the continuation. Test: freeze, then unfreeze gives 0/3 |
| 2b | Failed handoffs/unlocks counted as successes | Pinned benchmark: failures return `error=False` with text "Error: …" | **Accept** | Success judged from receipts (`Tool unlocked:`, `Tool given to user:`, not `Error…`). Test: failed give + failed unlock count as failed receipts |
| 2c | A proposal at the round limit was discarded unrecorded | Code read | **Accept** | Every generated proposal is recorded, with `not_executed_reason`. Test: `max_rounds=1` keeps the forbidden proposal |
| 2d | Harness-blocked proposals missing from the forbidden score | Code read | **Accept** | Scores at five levels: proposed (incl. blocked/withheld), blocked, attempted, successful, final state. Test with the rewards prototype on |
| 3 | Continuation runner did not enforce plan fingerprints, split, arms; no manifest; no exposure check for new calls | Code read (a zeroed hash would have run) | **Accept** | `preflight()` before any network call: approval, variant sha256s, dev split, source traces, runs→cases/variants/arms. Manifest (plan hash, trace hashes, instruction hashes, settings, benchmark pin, code revision) saved first. Exposure checked on prefix + continuation via `independence.check_sequence`; inconclusive = `unknown` |
| 4a | The verification rule enforces a log, not identity | Pinned benchmark: `log_verification` accepted an invented identity and reported success | **Accept** | Renamed `write_requires_verification_log`; documented as a log prerequisite with its unprotected paths; a test documents that an invented-identity log satisfies it |
| 4b | Missing tool-type metadata allows the action | Code read | **Accept, with one change** | Missing metadata (no toolkit) now raises `GuardConfigError`. **Disagreement:** an *unknown tool name* (the model invented one) still passes through. The environment rejects it with no state change, and blocking it would replace the benchmark's own error with ours, changing what the agent sees |
| 4c | Handing a customer a tool is exempt | Code read | **Accept as documented scope**, not a code change now | Listed under `unprotected` in `guard.RULES`; the customer's own writes are outside an agent-side guard by construction |
| 5a | A failed unlock was treated as used, suppressing the pre-send check | Code read | **Accept** | Only success receipts count as used. Test: failed unlock, then denial, fires |
| 5b | "Relevance" was reference-name overlap; `irrelevant_write_tools_named` did not filter writes | Code read | **Accept** | Renamed (`reference_name_overlap`, `first_overlap_position`); `write_names_not_in_reference` filters by tool type. New count: **12 of 13** firings name a write tool the reference does not use. Applicability of the 13 firing points reviewed by reading (`experiments/N001_applicability_review.md`) |

## Answers to the five architecture questions

| Question | Reviewer | Decision |
|---|---|---|
| Block permissions, advise on capability | Yes; bounded advisory retry; keep original, note and revision privately | **Agree.** Nudge events now store the full draft text, full draft tool calls and the note; the revision is the next recorded proposal |
| Database-backed rewards rule | Acceptable as a separately identified prototype; compare nudge on/off with identical guard access | **Agree.** N001 arms must share guard configuration; results never described as observed-evidence-only |
| Offline nudge evidence enough for N001? | Not yet | **Agree, and the applicability review supports it:** the reviewer judged the first suggestion applicable and authorized at 5/13, the first suggestion was a harm-risk write at 5/13, and the draft was already correct at 2/13 (selected firing points; no intervention executed). v1 is not ready. Next candidate (reads only, after a verification log) is to be evaluated offline before any N001 plan |
| Writes-only verification scope | Yes, as explicitly partial | **Agree**; documented as partial with unprotected paths |
| Free reference audit before D001? | Not needed; raw reference replay is invalid for the clock rule | **Agree, and verified:** 26/30 dev references log a verification and 0/30 read the clock. Replaced in the agenda with complete scripted positive and negative controls, required before N001 |

## Other corrections accepted

- **AgentTether.** On Banking, Reflexion repaired 22/83 initially failed tasks, the same as blind retry (22/83). Verified in the paper's Table I. "No gain" now reads "no gain over blind retry", with the model difference noted.
- **Wording.** Our checks are "inspired by" Reflexion, Voyager and Meta-Harness, not implementations of them.
- **`docs/STATUS.md`.** Marked as a superseded historical snapshot, with pointers to the current documents.
- **Statistics.** The blanket t-bounds rule was refined. For fixed diagnostic prefixes, report per-case outcomes and repeated-attempt variability only.

## D001 status

- Scoring was revised before any run (`scoring_revision` in the plan). Cases, instruction packages (fingerprints unchanged) and run order are unchanged.
- Still awaiting Nidhi's explicit approval ($0.50). Nothing was run.
