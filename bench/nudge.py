"""Pre-send checks that advise, never block (a harness change; the benchmark is unchanged).

Inspired by (not an implementation of) Reflexion's heuristic-triggered reflection (arXiv 2303.11366) and Voyager's
self-verification step (arXiv 2305.16291), and from Meta-Harness's observation that additive information
beat prompt rewrites (arXiv 2603.28052, App. A.2): instead of a standing instruction on every turn (S003,
which raised cost 45% without improving success), a deterministic trigger fires only at the failure
signature we measured, and the note it adds contains only information the agent has already seen.

One check so far:
  locked_named_tool_before_denial_or_transfer
    Fires when the agent is about to (a) tell the customer it cannot do something, or (b) transfer to a
    human, while discoverable tools named in tool results it received are still locked. The note lists
    those names (already in its context) and restates the documented unlock-and-call sequence, including
    that prerequisites still apply. At most once per conversation. The draft never enters the trajectory.

Evidence: only the agent's own conversation plus static tool metadata (which names are discoverable).
"""

import re

from bench.guard import target

DISCOVERABLE_NAME = re.compile(r"\b([a-z][a-z_]+_\d{4})\b")
DENIAL = re.compile(r"(don[’']t have (?:access|a (?:way|tool|backend tool))|do not have access|not exposed|"
                    r"can[’']t (?:complete|look up|access|directly|retrieve|perform)|cannot (?:access|perform|complete)|"
                    r"aren[’']t exposed|no (?:backend )?tool (?:here|available)|unable to (?:access|perform|complete))", re.I)
MAX_NAMES = 6
NUDGES = ("locked_named_tool_before_denial_or_transfer",)


RESULT_START = re.compile(r"^\s*(\d+)\.\s", re.M)


def _ranked_names(content: str, discoverable: set[str]):
    """(rank, name) for names in one tool result. KB search results are numbered '1. ...', '2. ...'; a name's
    rank is the position of the result it appears in (1 = the retriever's top result). Other tool results rank 1."""
    starts = [(int(m.group(1)), m.start()) for m in RESULT_START.finditer(content)]
    for n in DISCOVERABLE_NAME.finditer(content):
        if n.group(1) not in discoverable:
            continue
        rank = 1
        for r, pos in starts:
            if pos <= n.start():
                rank = r
        yield rank, n.group(1)


def locked_named_tools(messages: list[dict], discoverable: set[str]) -> list[str]:
    """Discoverable tool names that appeared in tool results the agent received and were never unlocked or
    given. Ordered by the best search-result position they appeared in (the retriever's own ranking), then
    most recent first. Ordering by recency alone buried the one relevant tool under later broad searches."""
    best: dict[str, tuple[int, int]] = {}
    used: set[str] = set()
    results = {m.get("tool_call_id"): m.get("content") or "" for m in messages if m.get("role") == "tool"}
    for step, m in enumerate(messages):
        if m.get("role") == "tool":
            for rank, n in _ranked_names(m.get("content") or "", discoverable):
                prev = best.get(n)
                if prev is None or rank < prev[0] or (rank == prev[0] and step > prev[1]):
                    best[n] = (rank, step)
        for c in m.get("tool_calls") or []:
            args = c.get("arguments") or {}
            receipt = results.get(c.get("id"), "").lstrip()
            # only a successful receipt counts as used: a failed unlock leaves the tool locked
            if c["name"] == "unlock_discoverable_agent_tool" and receipt.startswith("Tool unlocked:"):
                used.add(args.get("agent_tool_name"))
            elif c["name"] == "give_discoverable_user_tool" and receipt.startswith("Tool given to user:"):
                used.add(args.get("discoverable_tool_name"))
            elif c["name"] == "call_discoverable_agent_tool" and receipt and not receipt.startswith("Error"):
                used.add(target(c)[0])
    ordered = sorted(best, key=lambda n: (best[n][0], -best[n][1]))
    return [n for n in ordered if n not in used]


def trigger(proposal: dict, messages: list[dict], discoverable: set[str]) -> list[str] | None:
    """The locked names to mention if the check fires on this proposal, else None."""
    text = proposal.get("content") or ""
    transferring = any(c["name"] == "transfer_to_human_agents" for c in proposal.get("tool_calls") or [])
    denying = bool(text) and not proposal.get("tool_calls") and bool(DENIAL.search(text))
    if not (transferring or denying):
        return None
    names = locked_named_tools(messages, discoverable)
    return names[:MAX_NAMES] or None


def note(names: list[str], agent_tools: set[str]) -> str:
    agent = [n for n in names if n in agent_tools]
    user = [n for n in names if n not in agent_tools]
    parts = ["Harness note (not shown to the customer). Before you send this: documents you retrieved in this "
             "conversation name tools you have not used."]
    if agent:
        parts.append(f"Internal tools you can unlock: {', '.join(agent)}. To use one, call unlock_discoverable_agent_tool "
                     "with its exact name, then call_discoverable_agent_tool with its arguments as a JSON string.")
    if user:
        parts.append(f"Tools you can give the customer: {', '.join(user)}, via give_discoverable_user_tool.")
    parts.append("Use one only if it performs what the customer asked and the procedure's prerequisites are met "
                 "(identity verification, consent, required approvals). If none applies, or a transfer is required, "
                 "continue as you intended.")
    return " ".join(parts)
