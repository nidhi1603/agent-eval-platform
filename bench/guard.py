"""Action-time permission checks at the agent's proposal step (a harness change; the benchmark is unchanged).

Placement: proposals are intercepted before they enter the benchmark trajectory, so tau2's unchanged replay
evaluator (Environment.set_state replays every recorded mutating call; strict by default) receives only
actions actually submitted to the environment. Other enforcement designs could work with consistent replay
instrumentation; this is a practical choice, not the only one. A blocked proposal is shown privately to the
model with the reason, the model regenerates (every proposal is checked, including the last), and after
repeated blocks a fixed refusal is sent: a blocked call is never released. Blocked proposals are absent from
the official trajectory and fully recorded in the research trace.

Every rule declares where its evidence comes from:
  observed        only what the agent itself has seen in this conversation: its own tool calls and their
                  results (plus static tool metadata: whether a tool is a read or a write). These rules add
                  no information channel beyond the agent's own.
  environment_db  the environment's records. A DATABASE-BACKED PROTOTYPE: even an allow/deny result can reveal
                  something the agent could not observe, so runs using it are not comparable to a baseline
                  without disclosing that access.
Rules check the named prerequisite only. Passing a rule is not complete authorization for the action.
Evidence is re-read on every check; nothing is cached as a permanent "authorized" flag. Nothing the agent
or the customer says can satisfy a rule: only tool results (or, for environment_db, records) count.
"""

import json
import re
from dataclasses import dataclass, field

REWARDS_TOOL = "update_transaction_rewards_3847"
MAX_CONSECUTIVE_BLOCKS = 3
CLOCK = re.compile(r"The current time is (.+?)\.?\s*$")
VERIFIED = "Verification logged successfully"


@dataclass
class Decision:
    allowed: bool
    rule: str | None = None
    reason: str | None = None


@dataclass
class Evidence:
    """What a rule may look at. `messages` are the agent's own conversation as dicts with role, content,
    tool_calls [{id, name, arguments}] and, for tool results, tool_call_id and error."""
    messages: list[dict] = field(default_factory=list)
    tool_type: object = None  # callable: tool name -> "read" | "write" | "generic" | None (static metadata)
    db: object = None         # only for environment_db rules

    def results(self):
        """(call, result message) for every tool call the agent made that has a result."""
        by_id = {m.get("tool_call_id"): m for m in self.messages if m.get("role") == "tool"}
        for m in self.messages:
            for c in m.get("tool_calls") or []:
                if m.get("role") == "assistant" and c.get("id") in by_id:
                    yield c, by_id[c["id"]]

    def verification_logged(self) -> bool:
        return any(c["name"] == "log_verification" and not r.get("error") and VERIFIED in (r.get("content") or "")
                   for c, r in self.results())

    def clock_readings(self) -> set[str]:
        out = set()
        for c, r in self.results():
            if c["name"] == "get_current_time" and not r.get("error"):
                m = CLOCK.search((r.get("content") or "").strip())
                if m:
                    out.add(m.group(1).strip())
        return out


def target(tool_call) -> tuple[str | None, dict]:
    """The underlying tool name and arguments, looking through call_discoverable_agent_tool."""
    name = tool_call["name"] if isinstance(tool_call, dict) else tool_call.name
    args = (tool_call["arguments"] if isinstance(tool_call, dict) else tool_call.arguments) or {}
    if name != "call_discoverable_agent_tool":
        return name, args
    inner = args.get("arguments") or "{}"
    try:
        inner = json.loads(inner) if isinstance(inner, str) else dict(inner)
    except (json.JSONDecodeError, TypeError):
        inner = {}
    return args.get("agent_tool_name"), inner if isinstance(inner, dict) else {}


# ---- rules -------------------------------------------------------------------------------------------

def _write_requires_logged_verification(tool_call, ev: Evidence) -> Decision:
    name, _ = target(tool_call)
    raw = tool_call["name"] if isinstance(tool_call, dict) else tool_call.name
    # log_verification is how verification is recorded; unlocking and giving tools only register tools
    if raw in ("unlock_discoverable_agent_tool", "give_discoverable_user_tool") or name == "log_verification":
        return Decision(True)
    if ev.tool_type is None or ev.tool_type(name) != "write":
        return Decision(True)
    if ev.verification_logged():
        return Decision(True)
    return Decision(False, "write_requires_logged_verification",
                    "Blocked by policy check: verify the customer's identity and log it with log_verification "
                    "before making changes to their account. This call was not executed.")


def _verification_time_from_clock(tool_call, ev: Evidence) -> Decision:
    name, args = target(tool_call)
    if name != "log_verification":
        return Decision(True)
    stated = str(args.get("time_verified") or "").strip()
    if stated and stated in ev.clock_readings():
        return Decision(True)
    return Decision(False, "verification_time_from_clock",
                    "Blocked by policy check: time_verified must be a time returned by get_current_time in this "
                    "conversation. Call get_current_time and use its result. This call was not executed.")


def _approved_dispute(db, transaction_id: str) -> bool:
    rows = getattr(getattr(db, "cash_back_disputes", None), "data", None) or {}
    for record in rows.values():
        r = record if isinstance(record, dict) else getattr(record, "__dict__", {})
        if (r.get("transaction_id") == transaction_id and str(r.get("status")).upper() == "RESOLVED"
                and str(r.get("resolution")).upper() == "APPROVED"):
            return True
    return False


def _rewards_update_requires_approved_dispute(tool_call, ev: Evidence) -> Decision:
    name, args = target(tool_call)
    if name != REWARDS_TOOL:
        return Decision(True)
    txn = args.get("transaction_id")
    if txn and _approved_dispute(ev.db, txn):
        return Decision(True)
    return Decision(False, "rewards_update_requires_approved_dispute",
                    "Blocked by policy check: rewards may be updated only after a cash back dispute for this "
                    "transaction has been resolved and approved. This call was not executed.")


RULES = {
    "write_requires_logged_verification": {
        "check": _write_requires_logged_verification, "evidence": "observed",
        "policy": "Domain policy: 'for any scenario involving accessing customer information in internal databases, "
                  "you must first verify their identify before proceeding' and 'After verification, you must call "
                  "the verification...' (log_verification). Applied here to writes only.",
        "checks_only": "a successful log_verification earlier in the agent's conversation; not that the right person "
                       "was verified, nor that the write itself is permitted"},
    "verification_time_from_clock": {
        "check": _verification_time_from_clock, "evidence": "observed",
        "policy": "log_verification requires the actual verification time; the only source of the time is get_current_time",
        "checks_only": "time_verified equals a get_current_time result the agent received"},
    "rewards_update_requires_approved_dispute": {
        "check": _rewards_update_requires_approved_dispute, "evidence": "environment_db",
        "policy": "doc_credit_cards_credit_cards_(general)_004: rewards are updated after a cash back dispute is "
                  "resolved and approved",
        "checks_only": "an approved dispute record for the transaction; not the amount, ownership or other requirements",
        "note": "No agent tool reads cash_back_disputes (only the customer's submit tool writes it, and its result goes "
                "to the customer), so an observed-evidence version of this rule could never allow the legitimate flow."},
}
OBSERVED_RULES = tuple(r for r, spec in RULES.items() if spec["evidence"] == "observed")


def check(tool_call, evidence: Evidence, rules=tuple(RULES)) -> Decision:
    for rule in rules:
        d = RULES[rule]["check"](tool_call, evidence)
        if not d.allowed:
            return d
    return Decision(True)


def messages_as_dicts(messages) -> list[dict]:
    """tau2 Message objects (the agent's state) in the dict form rules read."""
    out = []
    for m in messages:
        d = {"role": m.role, "content": getattr(m, "content", None)}
        if m.role == "tool":
            d.update(tool_call_id=m.id, error=bool(m.error))
        elif getattr(m, "tool_calls", None):
            d["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in m.tool_calls]
        out.append(d)
    return out


def toolkit_type_lookup(toolkit):
    """Static read/write/generic metadata from the environment's tool definitions (not data)."""
    def lookup(name):
        try:
            return str(toolkit.tool_type(name).value).lower()
        except Exception:  # noqa: BLE001 - unknown or invented tool names have no type
            return None
    return lookup


def make_guarded_agent_class():
    import tau2.agent.llm_agent as llm_agent_module
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import AssistantMessage, ToolMessage

    class GuardedLLMAgent(LLMAgent):
        """tau2's LLMAgent with a proposal-time check. The runner sets `guard_rules`, `guard_toolkit` (for static
        tool types) and, only when an environment_db rule is enabled, `guard_db`. Blocked proposals go to `events`."""

        guard_rules: tuple[str, ...] = OBSERVED_RULES
        guard_toolkit = None
        guard_db = None

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.events: list[dict] = []

        def _evidence(self, state) -> Evidence:
            return Evidence(messages=messages_as_dicts(state.messages),
                            tool_type=toolkit_type_lookup(self.guard_toolkit) if self.guard_toolkit else None,
                            db=self.guard_db)

        def _generate_next_message(self, message, state):
            proposal = super()._generate_next_message(message, state)
            for attempt in range(MAX_CONSECUTIVE_BLOCKS + 1):  # the original proposal plus up to 3 regenerations
                ev = self._evidence(state)
                decisions = [(tc, check(tc, ev, self.guard_rules)) for tc in proposal.tool_calls or []]
                blocked = [(tc, d) for tc, d in decisions if not d.allowed]
                if not blocked:
                    return proposal  # every returned proposal has been checked
                for tc, d in blocked:
                    self.events.append({"event": "blocked", "attempt": attempt, "rule": d.rule, "reason": d.reason,
                                        "tool_call": tc.name, "arguments": tc.arguments})
                # Private feedback: visible to the model on its next generation, never part of the trajectory.
                state.messages.append(proposal)
                for tc, d in decisions:
                    state.messages.append(ToolMessage(
                        id=tc.id, role="tool", requestor="assistant", error=not d.allowed,
                        content=d.reason if not d.allowed else
                        "Not executed: another tool call in the same message was blocked by a policy check."))
                if attempt == MAX_CONSECUTIVE_BLOCKS:
                    break
                # llm_agent's own `generate`, looked up at call time, so the budget meters and tags it as "agent"
                proposal = llm_agent_module.generate(model=self.llm, tools=self.tools,
                                                     messages=state.system_messages + state.messages,
                                                     call_name="agent_response", **self.llm_args)
            self.events.append({"event": "fallback_after_repeated_blocks", "rule": None})
            return AssistantMessage(role="assistant", content=(
                "I'm not able to complete that action right now because a required policy condition is not met."))

    return GuardedLLMAgent
