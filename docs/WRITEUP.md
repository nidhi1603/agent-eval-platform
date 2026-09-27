# What I found evaluating a banking support agent on τ-Knowledge

Nidhi Rajani, September 2026.
- Implementation was AI-assisted (Claude Code). Research decisions, approvals and spending were mine.
- Everything below is reproducible from this repository. The live runs used about $1.74 of API credit (full-price estimate).

## The question

Can I measure *why* an LLM support agent fails on a realistic banking benchmark, and test one change against the measured failure honestly?
- Benchmark: τ-Knowledge `banking_knowledge`, tau2-bench v1.0.1 at a pinned commit.
- Honestly means: tasks fixed before running, paired comparison, blinded labelling, and all outcomes reported.

## What I built

- **A local runner** that executes one development task through tau2's official path and saves a complete trace. A trace holds messages, tool calls, retrievals, the official evaluation, spend and provenance.
  - Only development tasks are allowed. The held-out split was never touched.
- **Spending admission control.**
  - Before each call, the runner reserves a conservative upper bound on its cost. It refuses the call if the approved allocation can't cover it.
  - Provider retries are disabled, so every attempt is metered. The ledger is written to disk as each call is made.
  - It is an estimate, not a billing guarantee. Every run stayed within its allocation.
- **An integrity gate.** The agent is built without the task object. Its full system prompt and tool schemas must be byte-identical to an agent built from the task with its answer key erased.
- **Differential replay**, used as both a per-run check and an audit.
  - Each tool call is replayed against three environments: the real task, the real task again (to catch randomness), and the task with its answer key erased.
  - An output that is stable but changes when the answers are erased depends on hidden grading data.

## Findings

**1. A benchmark integrity defect (F001, $0).**
- One tool the agent can call, `list_discoverable_agent_tools`, prints a log. The benchmark writes a read call into that log only if the tool's name is in the reference solution.
- Under probes built from the reference solutions, agent-visible output depended on hidden reference data in **17 of 30 development tasks, through one shared mechanism**.
- A local fix keeps the grading logic unchanged and removes the dependence: no flags on 532 agent-visible outputs.
- This shows exposure only. I did not test whether any agent exploits it.
- Reported upstream with a standalone reproducer: [sierra-research/tau2-bench#574](https://github.com/sierra-research/tau2-bench/issues/574).

**2. A measured baseline (S002, $0.60).**
- Setup: gpt-5-mini agent, gpt-5.2 customer simulator, BM25 retrieval, 6 pre-registered tasks, one attempt each.
- Result: **0/6**.
- Reading every trace, the most common failure was the agent concluding something was unavailable ("not documented", "I can't do that here") without searching for it specifically. That happened in 5 of 6.
- Each label cites message numbers and knowledge-base document IDs. The measured cost was about $0.10 per conversation, half of it for the customer simulator.

**3. One controlled intervention that didn't help (S003, $1.12).**
- The instruction: search specifically before denying anything, without skipping required transfers or authorization.
- Design: 6 new tasks, each run with and without the instruction, back to back, in a balanced order fixed in advance.
- The plan was published before the run. Two independent labellers, blind to the arm, labelled the conversations, and their labels were committed before unblinding.
- **Both arms scored 0/6.**
  - The instruction reduced denials-without-a-prior-search from 4 to 2 conversations.
  - It raised estimated cost by 45% (full price; 24% cache-aware).
  - In the instruction arm, the agent made an unauthorized write that the instruction itself prohibited.
- I retired the instruction.

**4. The actual bottleneck (T001, $0).**
- Across all 19 live conversations, the agent unlocked a discoverable tool in only 2, though tool names appeared in its search results in 16. In one case it searched for a tool by name, found it, and told the customer it had no access to it.
- Replaying the exact saved states where the agent gave up, the documented unlock-and-call sequence **works**.
- Therefore the interface isn't broken; the model doesn't use it.
- The same check showed that the environment executes writes with **no identity verification**. Authorization lives only in the written policy.

## What I'd say I learned

- Check the benchmark before trusting its scores. A cheap differential replay found a defect a leaderboard would never show.
- A prompt instruction changed the agent's *behaviour* (more searching) without changing *outcomes*, and it cost more. Blinded, paired, pre-registered comparisons are what made that visible at n = 6. An anecdote would have looked like improvement.
- Read the traces before designing the fix. The failure I targeted (not searching) was a symptom. The cause visible in T001 is that the agent doesn't act on tools it has found. And because the environment doesn't enforce authorization, making the agent act more needs a harness-level guard, not only a prompt.

## Limits

- n = 6 per experiment, one attempt per arm. These are counts, not rates.
- BM25 retrieval, not the official `alltools` configuration, so nothing here is leaderboard-comparable.
- A single agent model.
- Spend figures are estimates from token usage and list prices, not reconciled against the provider's bill.
- Labels come from trace reading (two independent labellers for S003), not an automated classifier.

## Next step (not started)

A small development diagnostic on known failures:
- From two saved failure points where a retrieved document names the needed tool, compare the agent's next few steps with and without a clarified tool-discovery instruction.
- Measure correct tool use *and* whether verification and consent are kept.

Only if that works: test whether it improves completed tasks, with a harness-level check that blocks writes before identity verification.

## Where things are

| Artifact | Location |
|---|---|
| Defect report and fix | `docs/findings/2026-09-27-answer-dependent-listing.md`, `bench/fixes.py`, `repro/tau2_listing_allowlist.py` |
| Plans, results, labels | `experiments/S002_*`, `experiments/S003_*`, `experiments/T001_tool_discovery_check.md`, `EXPERIMENTS.md` |
| Traces | `results/S001_task_015/`, `results/S002/`, `results/S003/` |
| Runner, spend control, audit | `bench/run.py`, `bench/budget.py`, `bench/independence.py`, `bench/audit.py`, `bench/batch.py` |
| Tests (81 passing, plus 14 expected failures documenting known platform defects) | `tests/` |
