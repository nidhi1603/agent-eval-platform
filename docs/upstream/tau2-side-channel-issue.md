# DRAFT (not filed): banking_knowledge — `list_discoverable_agent_tools` reveals reference-trajectory membership

Status: draft for review. Not submitted; filing is a decision for the repository owner.

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

**Impact.** Small: one bit about a read the agent has already made. But it is a channel from the answer
key to the agent, so an optimized harness could exploit it (for example, by probing reads).

**Possible fixes.** Keep the eval-only log out of agent-visible tools: let `list_discoverable_agent_tools`
list every unlocked or called tool from separate agent-facing state, and use the allowlisted log only for
grading.
