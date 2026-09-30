"""Progress metrics for a conversation, with reads and writes kept apart.

This module exists because of a bug. research/h002/analyze.py counted every `call_discoverable_agent_tool`
reference action as a "reference write", so lookups made through that wrapper (read tools such as
get_all_user_accounts_by_user_id_3847) were counted as writes. The error ran through H002–H004
(research/h004/relabel_progress.py). Here every reference action and every agent call is classified by the
UNDERLYING tool's read/write type, seen through the discoverable wrappers.

Matching rules are H002's, unchanged. A reference action counts as matched when a successful call exists with the
same requestor and underlying tool, and all compared arguments are equal after str().strip().lower(). The compared
arguments are the action's compare_args minus wrapper keys, or all inner arguments for discoverable calls whose
compare_args are only wrapper keys. Order is ignored. A match is a diagnostic: it is not evidence of consent, order
or policy compliance.
"""

import json

WRAPPER_KEYS = {"agent_tool_name", "arguments", "discoverable_tool_name"}
CALL_AGENT, CALL_USER = "call_discoverable_agent_tool", "call_discoverable_user_tool"
UNLOCK, GIVE = "unlock_discoverable_agent_tool", "give_discoverable_user_tool"


def _inner(args):
    a = (args or {}).get("arguments")
    if isinstance(a, str):
        try:
            return json.loads(a)
        except ValueError:
            return {}
    return dict(a or {})


def key(requestor, name, args):
    """(requestor, underlying tool, comparable args), through the wrappers."""
    args = args or {}
    if name == CALL_AGENT:
        return requestor, args.get("agent_tool_name"), _inner(args)
    if name == CALL_USER:
        return requestor, args.get("discoverable_tool_name"), _inner(args)
    if name == UNLOCK:
        return requestor, "UNLOCK:" + str(args.get("agent_tool_name")), {}
    if name == GIVE:
        return requestor, "GIVE:" + str(args.get("discoverable_tool_name")), {}
    return requestor, name, dict(args)


def matched(ref, calls) -> bool:
    r_req, r_name, r_args = key(ref.requestor, ref.name, ref.arguments)
    cmp = ref.compare_args
    for req, name, args in calls:
        if (req, name) != (r_req, r_name):
            continue
        keys = [k for k in (cmp if cmp is not None else r_args.keys()) if k not in WRAPPER_KEYS]
        if ref.name in (CALL_AGENT, CALL_USER) and (cmp is None or set(cmp) <= WRAPPER_KEYS):
            keys = list(r_args.keys())
        if all(str(args.get(k)).strip().lower() == str(r_args.get(k)).strip().lower() for k in keys):
            return True
    return False


def underlying(name: str, args: dict | None) -> str | None:
    return key("x", name, args)[1]


def kind(name: str, args: dict | None, tool_type) -> str:
    """'write' | 'read' | 'other' by the UNDERLYING tool's type (the wrappers themselves are not typed as the tool).
    Unlocks and hand-overs are 'other': they change nothing in the database."""
    if name in (UNLOCK, GIVE):
        return "other"
    t = tool_type(underlying(name, args))
    return t if t in ("read", "write") else "other"


def progress(messages: list[dict], refs: list, tool_type) -> dict:
    """Per conversation (trajectory dicts: role, tool_calls [{id, name, arguments}], tool results with
    tool_call_id / content / error). `tool_type` maps an underlying tool name to 'read' | 'write' | other."""
    results = {m.get("tool_call_id"): m for m in messages if m.get("role") == "tool"}
    ok_calls, agent = [], {"read_calls": 0, "attempted_writes": 0, "successful_writes": 0}
    for m in messages:
        for c in m.get("tool_calls") or []:
            res = results.get(c["id"]) or {}
            ok = not res.get("error") and not (res.get("content") or "").lstrip().startswith("Error")
            if ok:
                ok_calls.append(key(m["role"] if m["role"] == "user" else "assistant", c["name"], c["arguments"]))
            if m["role"] == "assistant":
                k = kind(c["name"], c["arguments"], tool_type)
                if k == "read":
                    agent["read_calls"] += 1
                elif k == "write":
                    agent["attempted_writes"] += 1
                    agent["successful_writes"] += ok
    out = dict(agent)
    for bucket in BUCKETS:
        out[f"ref_{bucket}"], out[f"ref_{bucket}_matched"] = 0, 0
    for a in refs:
        b = bucket_of(a, tool_type)
        out[f"ref_{b}"] += 1
        out[f"ref_{b}_matched"] += matched(a, ok_calls)
    return out


# Reference actions by who acts, through which channel, and the underlying tool's type:
#   discoverable_writes  the agent's writes through call_discoverable_agent_tool (what H002-H004 meant by "writes")
#   discoverable_reads   the agent's lookups through the same wrapper (miscounted as writes in H002-H004)
#   base_writes          e.g. log_verification;  base_reads: e.g. get_user_information_by_email
#   customer             actions the customer performs with its own tools;  other: unlocks and hand-overs
BUCKETS = ("discoverable_writes", "discoverable_reads", "base_writes", "base_reads", "customer", "other")


def bucket_of(ref, tool_type) -> str:
    if ref.requestor == "user":
        return "customer"
    k = kind(ref.name, ref.arguments, tool_type)
    if k == "other":
        return "other"
    return ("discoverable_" if ref.name == CALL_AGENT else "base_") + k + "s"
