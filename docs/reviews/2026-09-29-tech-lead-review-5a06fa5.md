# Decision record: ChatGPT review of 5a06fa5 (harness v2), 2026-09-29

| Point | Decision | Evidence or action |
|---|---|---|
| An extra call before a tool's first use is acceptable for the pilot; measure it | Accept | H002 records interventions per check and cost per arm |
| H002 (baseline / v1 / v2) replaces H001; mark H001 superseded | Accept | `H001_plan.json` status set; H002 frozen with commits, settings, tasks, comparisons, outcomes and budget handling |
| Call it a BM25 pilot; it does not isolate the compiler | Accept | Stated in the plan's `kind`, `settings_note` and hypotheses |
| The $7–9 forecast is provisional | Accept | Forecast basis stated (1.3× and 1.7× assumptions); cap $12.00 |
| A rule-based compiler is sufficient; describe it precisely | Accept | README wording changed |
| Verbatim ≠ applicable or complete; 015 should not count as detection | Accept | README and EXPERIMENTS: reach vs detection; 16/19 with relevant content |
| Confirm a real call next to a plan call passes all checks against the updated state | Confirmed | `test_a_real_call_next_to_a_plan_call_still_passes_every_check_before_it_runs` (end to end) |
| A plan citation must not establish consent, ownership, eligibility or completion | Confirmed | `test_a_plan_citing_a_document_changes_no_hard_check`. Also, no v2 check enforces consent, ownership or eligibility at all (stated) |
| Plan statuses are about discovery, not prerequisite states | Accept | README "Limits" |
| Later: show the checklist with the tool before the model proposes a call | Defer | Candidate after H002, only if the checklists help |
| Don't switch to "intervene only when unmet" yet | Accept | The ledger cannot yet evaluate requirements |
| Stop expanding v2 until the pilot returns | Accept | – |
