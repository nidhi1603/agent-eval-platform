# Decision record: tech-lead direction for phase 2 (2026-09-28)

**Context.** Nidhi asked what we had found, given that the original aim was a harness that beats the published results. The reviewer (ChatGPT) agreed the goal is unfinished and recommended one architectural intervention, built and verified at $0 before any paid comparison. The principal engineer (Claude Code) verified each point.

| # | Reviewer point | Verified how | Verdict |
|---|---|---|---|
| 1 | 17/19 means *some* discoverable agent-tool name appeared, not "the right tool was found" | Counting script definition | **Accept.** My explanation to Nidhi overstated it |
| 2 | We did test harness code (D002 enforcement), not only prompts | – | **Accept** |
| 3 | The paper names two causes, retrieval *and* reasoning over complex policies | arXiv abstract: agents "struggle to retrieve the correct documents … and to reason accurately over complex internal policies"; best about 25.5% | **Accept.** I had said "the paper blames retrieval" |
| 4 | Custom leaderboard submissions allow modified scaffolds; all tasks and 4+ trials are expected | tau2 `docs/leaderboard-submission.md`: "Modified Scaffolds", "All tasks completed", "4+ trials … strongly prefer" | **Accept** |
| 5 | Build a direct-tool adapter: names only from agent-visible information; schemas through the permitted interface; original execution preserved; customer tools separate; availability ≠ authorization; nothing else changed | – | **Accept, implemented (A001).** One design decision is mine: unlock eagerly through the benchmark's own unlock call, which I confirmed is in-memory only and grading-neutral, instead of showing schemas before any unlock |
| 6 | Milestones: (1) show the adapter works, at $0; (2) full conversations, baseline vs adapter, same tasks, repeated; (3) held-out tasks and published comparison only if (2) warrants it | – | **Accept.** Milestone 1 done. Milestone 2 drafted as `experiments/A002_plan.json` |
| 7 | 6 tasks × 2 × 3 = 36 conversations, about $3.60 at earlier rates; a forecast, not a requirement | S002/S003 per-conversation rates | **Accept, with a budget flag.** Forecast $3.40–$5.00 against about $2.05 of remaining credit. The plan states both options (add credit, or 1 attempt per arm) |

**A002 draft choices, for review:**
- **Tasks:** fixed by rule before any run. The eligible pool is the dev tasks whose reference solution calls a discoverable agent tool (21 of 30); sort by hash and take 6: task_061, task_092, task_031, task_066, task_091, task_041.
- **Arm order:** balanced within and across tasks. Two earlier drafts were imbalanced and were replaced before anything ran.
