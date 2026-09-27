# DRAFT (not filed): banking_knowledge — `list_discoverable_agent_tools` reveals reference-trajectory membership

Status: draft for review. Not submitted; filing is Nidhi's decision.

**Version:** tau2-bench v1.0.1, commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619`.

**Summary.** In `banking_knowledge`, a discoverable *read* call is written to the
`agent_discoverable_tools` table only if that tool appears in the task's reference actions
(`runner/build.py::_derive_read_log_allowlist`, passed as `read_log_allowlist`;
`domains/banking_knowledge/tools.py`, the `underlying_mutates or agent_tool_name in self._read_log_allowlist`
branch). The agent-visible tool `list_discoverable_agent_tools` lists that table. After making a
discoverable read, an agent can therefore learn whether that read is part of the reference solution.

**Reproduction** (no LLM calls):
1. Build the environment for `task_085` with `retrieval_variant="bm25"` twice: once with
   `read_log_allowlist=_derive_read_log_allowlist(task)`, once with an empty allowlist.
2. In each, call `unlock_discoverable_agent_tool(get_all_user_accounts_by_user_id_3847)`, then
   `call_discoverable_agent_tool` with the reference arguments `{"user_id": "f7d3a82c91"}`, then
   `list_discoverable_agent_tools()`.
3. The read returns the same result in both environments. The listing shows
   `Found 1 record(s) in 'agent_discoverable_tools'` with the reference allowlist and
   `No records found` without it.

**Expected.** Agent-visible outputs do not depend on the task's evaluation criteria.

**Impact.** Small per call: one bit about a read the agent has already made. But the channel runs from the answer key
to the agent. We have not tested whether any agent or optimized harness uses it.

**Scope measured locally** (30 tasks of our development split, `bm25`, no LLM calls; reference-constructed probes, i.e. replaying each task's
reference actions against environments built from the task and from a copy with its evaluation criteria
emptied): the listing depends on the reference actions in 17 of 30 tasks, matching the tasks whose reference
contains a discoverable call to a non-mutating tool (consistent with the mechanism above). One mechanism, many tasks. Other agent-visible tool outputs
exercised showed no such dependency (coverage-limited).

**Related minor bug.** The empty-state branch checks for "No results found", but `query_database_tool`
returns "No records found", so the friendly message is never shown.

**Possible fixes.** Keep the eval-only log out of agent-visible tools: let `list_discoverable_agent_tools`
list every unlocked or called tool from separate agent-facing state, and use the allowlisted log only for
grading.
