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


class GuardConfigError(Exception):
    """A rule needs metadata the harness did not provide. Fails loudly instead of silently allowing."""


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

def _write_requires_verification_log(tool_call, ev: Evidence) -> Decision:
    """A VERIFICATION-LOG prerequisite, not identity verification: log_verification records whatever it is given
    and reports success even for invented identities (checked against the pinned benchmark). This rule only
    requires that such a log exists earlier in the agent's conversation; it does not check the identity fields
    against a lookup or bind the log to the customer whose resource a write touches."""
    name, _ = target(tool_call)
    raw = tool_call["name"] if isinstance(tool_call, dict) else tool_call.name
    # log_verification is how verification is recorded; unlocking and giving tools only register tools
    if raw in ("unlock_discoverable_agent_tool", "give_discoverable_user_tool") or name == "log_verification":
        return Decision(True)
    if ev.tool_type is None:
        raise GuardConfigError("write_requires_verification_log needs tool-type metadata (guard_toolkit not set)")
    # An unknown (invented) name has no type: the environment rejects it without any state change, so it is
    # passed through and the agent sees the benchmark's own error, not ours.
    if ev.tool_type(name) != "write":
        return Decision(True)
    if ev.verification_logged():
        return Decision(True)
    return Decision(False, "write_requires_verification_log",
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
    "write_requires_verification_log": {
        "check": _write_requires_verification_log, "evidence": "observed",
        "policy": "Domain policy: 'for any scenario involving accessing customer information in internal databases, "
                  "you must first verify their identify before proceeding' and 'After verification, you must call "
                  "the verification...' (log_verification). Applied here to writes only.",
        "checks_only": "that a verification LOG exists earlier in the agent's conversation. It does not establish "
                       "identity (log_verification accepts invented identities) and is not bound to the customer "
                       "whose resource the write touches",
        "unprotected": ["reads of customer data (verification-enabling lookups are needed first)",
                        "tools handed to the customer (give_discoverable_user_tool) and the customer's own writes",
                        "writes whose target belongs to a different customer than the one logged"]},
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
EVIDENCE_FEEDBACK = ("Identifiers must come from records you retrieved for this customer. For any amount, state in the same "
                     "message: 'Calculation: <formula over named inputs> = <name>', 'Sources: name=record:<record_id>.<field>; "
                     "name=policy:<doc_id>:<value>' and 'Result: <amount> USD|points'. You may correct the call once.")
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
    """Static read/write/generic metadata from the environment's tool definitions (not data).
    A name absent from the toolkit (the model invented it) has no type: None, and the environment's own rejection
    stands. A KNOWN tool whose type cannot be read is a configuration error, never treated as unknown."""
    def lookup(name):
        if not toolkit.has_tool(name):
            return None
        try:
            return str(toolkit.tool_type(name).value).lower()
        except Exception as e:  # noqa: BLE001 - any failure on a known tool must not fail open
            raise GuardConfigError(f"tool-type metadata unreadable for known tool {name!r}: {e!r}") from e
    return lookup


def make_guarded_agent_class():
    import tau2.agent.llm_agent as llm_agent_module
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import AssistantMessage, SystemMessage, ToolMessage

    from bench import nudge as nudge_mod

    class GuardedLLMAgent(LLMAgent):
        """tau2's LLMAgent with proposal-time review: permission rules that block (`guard_rules`) and pre-send
        checks that advise once (`harness_nudges`, bench/nudge.py). The runner sets `guard_toolkit` (static tool
        types and discoverable names), and `guard_db` only when an environment_db rule is enabled. Every
        intervention is appended to `events`; rejected drafts never enter the trajectory."""

        guard_rules: tuple[str, ...] = ()
        harness_nudges: tuple[str, ...] = ()
        guard_toolkit = None
        guard_db = None
        discoverable_names: frozenset = frozenset()
        agent_tool_names: frozenset = frozenset()
        # Argument-evidence check (bench/evidence.py): None (off), "record" (assess and log every proposal, never
        # block) or "enforce" (writes that fail get one private correction; a second failure is withheld).
        # Reads are only ever recorded.
        evidence_mode: str | None = None

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.events: list[dict] = []
            self.nudges_fired = 0

        def _evidence(self, state) -> Evidence:
            return Evidence(messages=messages_as_dicts(state.messages),
                            tool_type=toolkit_type_lookup(self.guard_toolkit) if self.guard_toolkit else None,
                            db=self.guard_db)

        def _regenerate(self, state):
            # llm_agent's own `generate`, looked up at call time, so the budget meters and tags it as "agent"
            return llm_agent_module.generate(model=self.llm, tools=self.tools,
                                             messages=state.system_messages + state.messages,
                                             call_name="agent_response", **self.llm_args)

        def _evidence_review(self, proposal, ev, state, corrections):
            """None to continue with this proposal, "regenerate" after adding private feedback, or a withheld
            replacement message."""
            from bench import evidence as evidence_mod

            if ev.tool_type is None:
                raise GuardConfigError("the evidence check needs tool-type metadata (guard_toolkit not set)")
            failing = []
            for tc in proposal.tool_calls:
                name, _ = target(tc)
                if tc.name in ("unlock_discoverable_agent_tool", "give_discoverable_user_tool"):
                    continue
                try:
                    a = evidence_mod.check_arguments(tc, proposal.content, ev)
                except Exception as e:  # noqa: BLE001 - a checker defect must not end the conversation in either arm
                    a = evidence_mod.Assessment(False, [{"arg": None, "kind": "checker", "status": "checker_error",
                                                         "detail": f"{type(e).__name__}: {e}"}])
                if not a.findings:
                    continue
                kind = ev.tool_type(name)
                enforce = self.evidence_mode == "enforce" and kind == "write"
                self.events.append({"event": "evidence_assessed", "mode": self.evidence_mode, "tool": name,
                                    "tool_type": kind, "attempt": corrections, "allowed": a.allowed,
                                    "enforced": enforce, "findings": a.findings, "flags": a.flags,
                                    "draft_text": proposal.content, "arguments": tc.arguments})
                if enforce and not a.allowed:
                    failing.append((tc, a))
            if not failing:
                return None
            if corrections >= 1:
                self.events.append({"event": "evidence_withheld", "tools": [target(tc)[0] for tc, _ in failing]})
                return AssistantMessage(role="assistant", content=(
                    "I did not execute that proposed change, because I couldn't document the values it depends on."))
            state.messages.append(proposal)
            problems = {id(tc): [f"{f['arg']}: {f.get('problem') or f.get('status')} ({f.get('detail', '')})"
                                 for f in a.findings if not (f.get("basis") if f["kind"] == "id"
                                                            else f.get("status") in ("supported", "unchecked"))]
                        for tc, a in failing}
            for tc in proposal.tool_calls:
                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant", error=id(tc) in problems,
                                                  content=("Not executed: evidence check failed. " +
                                                           "; ".join(problems[id(tc)]) + ". " + EVIDENCE_FEEDBACK)
                                                  if id(tc) in problems else
                                                  "Not executed: another tool call in the same message failed the evidence check."))
            self.events.append({"event": "evidence_blocked", "tools": [target(tc)[0] for tc, _ in failing]})
            return "regenerate"

        def _generate_next_message(self, message, state):
            proposal = super()._generate_next_message(message, state)
            blocks = 0
            corrections = 0
            while True:
                ev = self._evidence(state)
                decisions = [(tc, check(tc, ev, self.guard_rules)) for tc in proposal.tool_calls or []]
                blocked = [(tc, d) for tc, d in decisions if not d.allowed]
                if blocked:
                    for tc, d in blocked:
                        self.events.append({"event": "blocked", "attempt": blocks, "rule": d.rule, "reason": d.reason,
                                            "tool_call": tc.name, "arguments": tc.arguments})
                    # Private feedback: visible to the model on its next generation, never part of the trajectory.
                    state.messages.append(proposal)
                    for tc, d in decisions:
                        state.messages.append(ToolMessage(
                            id=tc.id, role="tool", requestor="assistant", error=not d.allowed,
                            content=d.reason if not d.allowed else
                            "Not executed: another tool call in the same message was blocked by a policy check."))
                    if blocks == MAX_CONSECUTIVE_BLOCKS:
                        self.events.append({"event": "fallback_after_repeated_blocks", "rule": None})
                        return AssistantMessage(role="assistant", content=(
                            "I'm not able to complete that action right now because a required policy condition "
                            "is not met."))
                    blocks += 1
                    proposal = self._regenerate(state)
                    continue  # every proposal, including the last, is checked
                if self.evidence_mode and proposal.tool_calls:
                    held = self._evidence_review(proposal, ev, state, corrections)
                    if held == "regenerate":
                        corrections += 1
                        proposal = self._regenerate(state)
                        continue  # the correction is reviewed again by every rule and check
                    if held is not None:
                        return held
                if "locked_named_tool_before_denial_or_transfer" in self.harness_nudges and self.nudges_fired == 0:
                    draft = messages_as_dicts([proposal])[0]
                    names = nudge_mod.trigger(draft, ev.messages, set(self.discoverable_names))
                    if names:
                        self.nudges_fired += 1
                        text = nudge_mod.note(names, set(self.agent_tool_names))
                        self.events.append({"event": "nudged", "check": "locked_named_tool_before_denial_or_transfer",
                                            "names": names, "note": text, "draft_text": proposal.content,
                                            "draft_tool_calls_full": [{"name": tc.name, "arguments": tc.arguments}
                                                                      for tc in proposal.tool_calls or []]})
                        state.messages.append(proposal)
                        if proposal.tool_calls:
                            for tc in proposal.tool_calls:
                                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant",
                                                                  content="Not executed yet. " + text))
                        else:
                            state.messages.append(SystemMessage(role="system", content=text))
                        proposal = self._regenerate(state)
                        continue  # the regenerated proposal is reviewed again (the nudge fires at most once)
                return proposal

    return GuardedLLMAgent
