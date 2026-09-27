"""Builds the worked example for the `discovery_example_v1` variant from a real execution.

The protocol shown (unlock response format, JSON-string arguments, call result shape) is produced by
running a real discoverable tool in a disposable environment (dev task_047's initial state; no reference
solution is used), then replacing the real tool name, identifiers and domain wording with neutral
placeholders so the example cannot hint at which real tool any task needs. `tests/test_variants.py` checks
that the frozen file equals a fresh build, and that reversing the substitutions reproduces the real outputs.

    uv run --extra bench python -m bench.discovery_example   # prints the example
"""

import json

REAL_TOOL, REAL_ARGS, SOURCE_TASK = "get_user_dispute_history_7291", {"user_id": "c7d8e9f0a1"}, "task_047"
# real text -> placeholder, applied in order
SUBSTITUTIONS = [
    ("Retrieve a user's credit card transaction dispute history from the transaction_disputes table. Returns all "
     "credit card transaction disputes filed by the user, including dispute IDs, transaction IDs, dispute reasons, "
     "statuses, and submission dates.", "Retrieve a customer's record history."),
    ("User transaction dispute history retrieved successfully.", "Record history retrieved successfully."),
    ("Transaction dispute history for user", "Record history for user"),
    ("No transaction disputes found for this user.", "No records found for this user."),
    (REAL_TOOL, "get_record_history_0000"),
    ("c7d8e9f0a1", "u0000example"),
]


def real_outputs() -> tuple[str, str]:
    from tau2.data_model.message import ToolCall
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench.independence import fresh_env

    env = fresh_env(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"),
                    get_tasks("banking_knowledge", task_ids=[SOURCE_TASK])[0])

    def call(name, args):
        return env.get_response(ToolCall(id="x", name=name, arguments=args, requestor="assistant")).content

    unlocked = call("unlock_discoverable_agent_tool", {"agent_tool_name": REAL_TOOL})
    called = call("call_discoverable_agent_tool", {"agent_tool_name": REAL_TOOL, "arguments": json.dumps(REAL_ARGS)})
    return unlocked, called


def neutralize(text: str) -> str:
    for real, placeholder in SUBSTITUTIONS:
        text = text.replace(real, placeholder)
    return text


def restore(text: str) -> str:
    for real, placeholder in reversed(SUBSTITUTIONS):
        text = text.replace(placeholder, real)
    return text


def build() -> str:
    unlocked, called = (neutralize(t) for t in real_outputs())
    tool, uid = "get_record_history_0000", "u0000example"
    args = json.dumps({"user_id": uid})
    return f"""## Worked example: using an internal tool (placeholder names, not a real customer or tool)

A knowledge-base procedure says: "To review a customer's record history, use `{tool}`." The customer's identity was verified earlier in the conversation (their user_id, `{uid}`, came from the lookup), and they asked you to review their history.

Step 1. Unlock the tool named in the procedure:
`unlock_discoverable_agent_tool({json.dumps({"agent_tool_name": tool})})`
Result:
```
{unlocked.strip()}
```

Step 2. Check what it needs and whether you may use it now. It needs `user_id`, which you already have from the lookup. The prerequisites are met: identity is verified and the customer asked for this.

Step 3. Call it through the wrapper, with the arguments as a JSON string:
`call_discoverable_agent_tool({json.dumps({"agent_tool_name": tool, "arguments": args})})`
Result:
```
{called.strip()}
```

Step 4. Use the result to continue the procedure, and tell the customer what you found. If the result had been an error, you would correct the arguments rather than report success.
"""


if __name__ == "__main__":
    import bench  # noqa: F401

    print(build())
