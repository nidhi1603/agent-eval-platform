## Worked example: using an internal tool (placeholder names, not a real customer or tool)

A knowledge-base procedure says: "To review a customer's record history, use `get_record_history_0000`." The customer's identity was verified earlier in the conversation (their user_id, `u0000example`, came from the lookup), and they asked you to review their history.

Step 1. Unlock the tool named in the procedure:
`unlock_discoverable_agent_tool({"agent_tool_name": "get_record_history_0000"})`
Result:
```
Tool unlocked: get_record_history_0000
Description: Retrieve a customer's record history.

Tool: get_record_history_0000
Description: Retrieve a customer's record history.
Parameters:
  - user_id: string (required) - The user's unique identifier in the system

You can now use this tool by calling `call_discoverable_agent_tool` with agent_tool_name='get_record_history_0000' and the required arguments.
```

Step 2. Check what it needs and whether you may use it now. It needs `user_id`, which you already have from the lookup. The prerequisites are met: identity is verified and the customer asked for this.

Step 3. Call it through the wrapper, with the arguments as a JSON string:
`call_discoverable_agent_tool({"agent_tool_name": "get_record_history_0000", "arguments": "{\"user_id\": \"u0000example\"}"})`
Result:
```
Record history retrieved successfully.

Executed: get_record_history_0000
Record history for user u0000example:

No records found for this user.
```

Step 4. Use the result to continue the procedure, and tell the customer what you found. If the result had been an error, you would correct the arguments rather than report success.

