# Decision record: tech-lead review of `4b63830`

**Roles.** The reviewer (ChatGPT, acting as senior tech lead) checked the fixes, reran the suite (120 passed, 14 xfailed) and reproduced one guard failure. The principal engineer (Claude Code) verified each point before deciding. Spending and publishing decisions are Nidhi's. The reviewer's technical go-ahead for D001 is not spending approval.

**Outcome.** Three corrections, all accepted after verification. D001 is unchanged and still unrun. Spend: $0.

| # | Reviewer point | Verified how | Verdict | What changed |
|---|---|---|---|---|
| 1 | `toolkit_type_lookup` treats *any* metadata exception as an unknown tool, so a known write (`freeze_debit_card_3892`) with a raising lookup and no verification log is allowed | Read the code (bare `except Exception` → `None`); reproduced with a monkeypatched `tool_type` | **Accept; fixed now**, not deferred to N001 (a two-line change, and a fail-open in a permission rule shouldn't stay in the code) | Name absent from the toolkit (`has_tool` false) → `None`, so the benchmark's own rejection stands. Known tool whose type can't be read → `GuardConfigError`. Test `test_unreadable_metadata_for_a_known_tool_fails_closed` fails on `4b63830` and passes now |
| 2 | N001 table has 11 inappropriate drafts, the narrative 10; reconcile from the labels, don't just edit the headline | Recounted the table; reread the independent reviewer's full per-point report | **Accept** | The per-row labels were right (11). The reviewer's own summary sentence ("9 … and F02") omitted **F01**: a transfer when a customer self-service tool covers the request. Two other lines of that prose also disagree with its table ("help at 6 / partly 5" vs 5/6 in the table; harm list omits F04). Counts now come from the rows; the reconciliation is written into the file |
| 3 | Wording: "clearly helps at five", "real and common", "timestamp rule would falsely block reference solutions" | Found each in `N001_applicability_review.md`, the c20312c record, `EXPERIMENTS.md` and `RESEARCH_AGENDA.md` | **Accept** | "A reviewer judged the first suggestion applicable and authorized at five points"; "the failure recurs among these selected firing points"; "raw reference replay lacks the clock evidence needed to assess the clock rule". No prevalence or benefit claims: the points are trigger-selected and no intervention ran |

## Answers to the three questions

| Question | Reviewer | Decision |
|---|---|---|
| Invented-tool pass-through | Yes, with correction 1 above | **Agree**; correction applied |
| Reads-only nudge candidate, or drop | Keep as a candidate; run D001 first. A verification log does not authorize reading a particular customer's data | **Agree.** Not built until after D001. If built: separate public policy searches and verification-enabling lookups from protected reads, check applicability, describe the log prerequisite honestly, preserve required transfers and requests for missing information |
| Run D001 as frozen | Yes: four cases × four packages, one attempt, fixed order, guards and nudges off; report all 16, including unfinished or errored runs | **Agree.** It is a diagnostic on selected failure points, not a reliability estimate or a general comparison of packages. Guards stay off in D001, so correction 1 does not change any D001 code path |

## D001 status
Technically cleared by both reviewers. Not run: it needs Nidhi's explicit approval of the $0.50 total.
