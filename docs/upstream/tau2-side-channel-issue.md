# FILED as https://github.com/sierra-research/tau2-bench/issues/574 (2026-09-27): banking_knowledge — `list_discoverable_agent_tools` reveals reference-derived tool membership

Status: filed by Nidhi's authorization. The filed text adds pinned links to the reproducer and fix at commit 8f60cae, and a Related section (#329, #405, #502).

**Version:** tau2-bench v1.0.1, commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619`.

**Summary.** In `banking_knowledge`, a discoverable *read* call is written to the
`agent_discoverable_tools` table only if that tool appears in the task's reference actions
(`runner/build.py::_derive_read_log_allowlist`, passed as `read_log_allowlist`;
`domains/banking_knowledge/tools.py`, the `underlying_mutates or agent_tool_name in self._read_log_allowlist`
branch). The agent-visible tool `list_discoverable_agent_tools` lists that table. After making a
discoverable read, an agent can therefore learn whether that read tool's name appears in the reference-derived
allowlist. This is tool-name membership: it says nothing about whether the arguments or the position in the
conversation match the reference. Because the listing prints every logged record, one listing can reveal this
membership for several previously called tools.

**Runnable reproducer** (tau2 API only, no LLM calls or keys): `repro/tau2_listing_allowlist.py` in
<LINK AT A SPECIFIC COMMIT: to be added once the repository is published>. Exit code 1 means the listings differ.

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

**Impact.** The listing exposes reference-derived tool membership to the agent. Whether agents exploit it, and
any effect on scores, have not been tested or measured.

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
