"""Action-time permission checks at the agent's proposal step (a harness change; the benchmark is unchanged).

Why at the proposal step and not at execution: tau2 grades the database by replaying every mutating
tool call recorded in the trajectory (Environment.set_state, strict by default: a replayed call whose
output differs from the recorded one raises). A write blocked at execution would still be recorded,
then re-executed during grading. So a blocked proposal must never enter the trajectory. GuardedLLMAgent
checks each proposed tool call before returning the message; if one is blocked, the model privately sees
its attempt and the reason, and generates again. The blocked proposal is logged in `events`, not in the
conversation.

Evidence comes from the environment's system of record (its database), never from anything the agent
or the user says: an agent message claiming "approved" cannot satisfy a rule. The database is not the
answer key; rules never read the task's evaluation criteria.

One reviewed rule so far:
  rewards_update_requires_approved_dispute
    Policy: doc_credit_cards_credit_cards_(general)_004 ("Applying Resolved Cash Back Dispute Corrections"):
    "After a cash back dispute is resolved and approved, you must update the affected transaction(s)".
    Evidence: a cash_back_disputes record for that transaction_id with status RESOLVED and resolution
    APPROVED. The environment writes such a record when a dispute is submitted and the task's dispute
    settings auto-resolve it; otherwise the record says SUBMITTED.
    Checked per call, from current evidence: nothing is cached as a permanent "authorized" flag.
"""

import json
from dataclasses import dataclass

REWARDS_TOOL = "update_transaction_rewards_3847"
RULES = ("rewards_update_requires_approved_dispute",)
MAX_CONSECUTIVE_BLOCKS = 3


@dataclass
class Decision:
    allowed: bool
    rule: str | None = None
    reason: str | None = None


def _target(tool_call) -> tuple[str | None, dict]:
    """The underlying tool name and arguments, looking through call_discoverable_agent_tool."""
    args = tool_call.arguments or {}
    if tool_call.name != "call_discoverable_agent_tool":
        return tool_call.name, args
    inner = args.get("arguments") or "{}"
    try:
        inner = json.loads(inner) if isinstance(inner, str) else dict(inner)
    except (json.JSONDecodeError, TypeError):
        inner = {}
    return args.get("agent_tool_name"), inner if isinstance(inner, dict) else {}


def _approved_dispute(db, transaction_id: str) -> bool:
    table = getattr(db, "cash_back_disputes", None)
    rows = getattr(table, "data", None) or {}
    for record in rows.values():
        r = record if isinstance(record, dict) else getattr(record, "__dict__", {})
        if (r.get("transaction_id") == transaction_id and str(r.get("status")).upper() == "RESOLVED"
                and str(r.get("resolution")).upper() == "APPROVED"):
            return True
    return False


def check(tool_call, db, rules=RULES) -> Decision:
    name, args = _target(tool_call)
    if "rewards_update_requires_approved_dispute" in rules and name == REWARDS_TOOL:
        txn = args.get("transaction_id")
        if not txn or not _approved_dispute(db, txn):
            return Decision(False, "rewards_update_requires_approved_dispute",
                            "Blocked by policy check: rewards may be updated only after a cash back dispute "
                            "for this transaction has been resolved and approved. This call was not executed.")
    return Decision(True)


def make_guarded_agent_class():
    import tau2.agent.llm_agent as llm_agent_module
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import AssistantMessage, ToolMessage

    class GuardedLLMAgent(LLMAgent):
        """tau2's LLMAgent with a proposal-time check. Set `guard_db` (the environment's database) and
        `guard_rules` before the conversation starts; blocked proposals are appended to `events`."""

        guard_db = None
        guard_rules: tuple[str, ...] = RULES

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.events: list[dict] = []

        def _generate_next_message(self, message, state):
            proposal = super()._generate_next_message(message, state)
            for _ in range(MAX_CONSECUTIVE_BLOCKS):
                decisions = [(tc, check(tc, self.guard_db, self.guard_rules)) for tc in proposal.tool_calls or []]
                blocked = [(tc, d) for tc, d in decisions if not d.allowed]
                if not blocked:
                    return proposal
                for tc, d in blocked:
                    self.events.append({"event": "blocked", "rule": d.rule, "tool_call": tc.name,
                                        "arguments": tc.arguments, "turn_messages_seen": len(state.messages)})
                # Private feedback: visible to the model on its next generation, never part of the trajectory.
                state.messages.append(proposal)
                for tc, d in decisions:
                    state.messages.append(ToolMessage(
                        id=tc.id, role="tool", requestor="assistant", error=not d.allowed,
                        content=d.reason if not d.allowed else
                        "Not executed: another tool call in the same message was blocked by a policy check."))
                # llm_agent's own `generate`, looked up at call time, so the budget meters and tags it as "agent"
                proposal = llm_agent_module.generate(model=self.llm, tools=self.tools, messages=state.system_messages + state.messages,
                                    call_name="agent_response", **self.llm_args)
            self.events.append({"event": "fallback_after_repeated_blocks", "rule": None})
            return AssistantMessage(role="assistant", content=(
                "I'm not able to complete that action right now because a required policy condition is not met."))

    return GuardedLLMAgent
