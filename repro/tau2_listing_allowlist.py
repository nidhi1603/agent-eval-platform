"""Standalone reproducer for tau2-bench (v1.0.1, b7ea907): `list_discoverable_agent_tools` output
depends on the reference-derived `read_log_allowlist`. Uses only tau2's own API; no LLM calls, no keys.

    python repro/tau2_listing_allowlist.py      # from an environment with tau2-bench installed

Builds the task_085 environment twice through tau2's `_build_env_kwargs`. The two builds differ only in
`read_log_allowlist`: the value tau2 derives from the task's reference actions, and an empty set.
It makes the same three calls in each, then prints both listings. Exit code 1 = the listings differ
(defect present), 0 = identical.
"""

import sys

from tau2.data_model.message import ToolCall
from tau2.data_model.simulation import TextRunConfig
from tau2.runner.build import _build_env_kwargs, build_environment
from tau2.runner.helpers import get_tasks

TOOL = "get_all_user_accounts_by_user_id_3847"
CALLS = [
    ("unlock_discoverable_agent_tool", {"agent_tool_name": TOOL}),
    ("call_discoverable_agent_tool", {"agent_tool_name": TOOL, "arguments": '{"user_id": "f7d3a82c91"}'}),
    ("list_discoverable_agent_tools", {}),
]


def run(task, allowlist):
    kwargs = _build_env_kwargs(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"), task)
    kwargs["read_log_allowlist"] = allowlist
    env = build_environment("banking_knowledge", env_kwargs=kwargs)
    init = task.initial_state
    env.set_state(initialization_data=init.initialization_data if init else None,
                  initialization_actions=init.initialization_actions if init else None, message_history=[])
    outs = [env.get_response(ToolCall(id=f"c{i}", name=n, arguments=a, requestor="assistant")).content
            for i, (n, a) in enumerate(CALLS)]
    return outs


def main() -> int:
    from tau2.runner.build import _derive_read_log_allowlist

    task = get_tasks("banking_knowledge", task_ids=["task_085"])[0]
    derived = _derive_read_log_allowlist(task)
    with_ref, without = run(task, derived), run(task, set())
    print("reference-derived allowlist:", sorted(derived))
    print("read result identical in both builds:", with_ref[1] == without[1])
    print("\n--- listing, reference-derived allowlist ---\n" + with_ref[2])
    print("\n--- listing, empty allowlist ---\n" + without[2])
    differs = with_ref[2] != without[2]
    print("\nlisting differs:", differs)
    return int(differs)


if __name__ == "__main__":
    sys.exit(main())
