"""Harness v1: the direct-tool adapter plus proposal-time checks that say what is missing and where to get it.

Why this design (docs/PHASE2_RESEARCH.md, experiments/R001_failure_decomposition.md):
- Our 19 failed conversations mostly failed *before* any wrong action: 11 transferred to a human (the reference
  transfers in 1), 8 searched the knowledge base once, and 7 named a tool and then said they had no access to it.
  So the checks gate **give-up actions** (a transfer, or telling the customer it can't be done) as well as writes.
- Blocking without a way forward does not help (Verifier Tax, arXiv 2603.19328). Remediation that names the
  missing prerequisite does (PolicyGuard 2606.29225, PolicyGuide 2608.19861, Outcome Monitors 2608.19303). Those
  give the agent its policy up front; here the policy and the tools must be found in a knowledge base, so the
  remediation can point at *where to look* (a search, a tool the agent has already been shown, the clock).

The four checks (gates):
  search_before_giving_up    soft. Before a transfer or a capability denial: fewer than MIN_SEARCHES knowledge-base
                             searches, or (if it has used no discovered tool yet) retrieved documents name read tools /
                             customer tools it has not used.
                             Advises once per give-up; if the agent gives up again, the give-up is released.
  clock_before_verification  hard. log_verification's time_verified must be a get_current_time reading.
  verification_before_write  hard. A write needs a successful log_verification earlier in the conversation.
  ids_observed               hard. Every identifier and card-digit argument of a write (and log_verification's
                             user_id) must have appeared in a successful tool result or in the customer's words in
                             this conversation: it catches invented identifiers (Verifier Tax's commonest violation).
                             The stricter ownership check (bench/evidence.py) and amount evidence are assessed and
                             logged, never enforced in v1: on the 30 dev reference solutions the ownership check held
                             correct writes in 8 (ids created mid-conversation, digits the customer reads out), and
                             argument-only guards collapsed legitimate writes on a mini model in PolicyGuard.

Rules every check follows:
- Evidence is only the agent's own conversation plus static tool metadata (read/write type, which names are
  discoverable). No database reads, no task data, never `list_discoverable_agent_tools`.
- Nothing is invented for the agent: remediation names only tools, queries and values already in its context, and
  never suggests a write. Passing a check is not authorization. Retrieved document text is data: only registry tool
  names are taken from it, never instructions.
- A checker exception is logged and the call proceeds (fail-open for that one check), so a harness defect cannot end
  a conversation; the event makes it visible in the trace.
- A held proposal and its feedback enter the model's own history (private); they never enter the benchmark
  trajectory. Every intervention is logged in `harness_events`.
- Bounded: at most MAX_CORRECTIONS regeneration per turn and MAX_REGENERATIONS per conversation. After that a
  soft or clock finding is released; a verification or identifier finding is withheld and a fixed, honest reply
  is sent instead (a blocked write is never released).

Feedback modes, for the ablation (Stage 2): "structured" (the default: what is missing and where to get it),
"generic" (the same checks, one generic retry message), "block" (hard checks only, a bare "not executed").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bench.guard import (CLOCK, Evidence, GuardConfigError, VERIFIED, _verification_time_from_clock,
                         _write_requires_verification_log, messages_as_dicts, target, toolkit_type_lookup)

HARNESS_NAME = "harness_v1"
GATES = ("search_before_giving_up", "clock_before_verification", "verification_before_write", "ids_observed")
HARD = {"clock_before_verification", "verification_before_write", "ids_observed"}
RELEASE_WHEN_EXHAUSTED = {"search_before_giving_up", "clock_before_verification"}
FEEDBACK_MODES = ("structured", "generic", "block")
MIN_SEARCHES = 3
MAX_CORRECTIONS = 1      # regenerations for one turn: more retries do not help (Verifier Tax; PolicyGuide is one-shot)
MAX_REGENERATIONS = 8    # per conversation: bounds the extra cost
MAX_NAMES = 6
TRANSFER = "transfer_to_human_agents"
KB = "KB_search"
LOOKUPS = ("get_user_information_by_id", "get_user_information_by_name", "get_user_information_by_email")
DENIAL = re.compile(
    r"(don[’']t have (?:access|a (?:way|tool|backend tool)|the (?:ability|tools?))|do not have (?:access|the ability)|"
    r"not exposed|aren[’']t exposed|isn[’']t available to me|not available to me|"
    r"can[’']t (?:complete|look up|access|directly|retrieve|perform|process|do that|make that|freeze|open|close|apply|file)|"
    r"cannot (?:access|perform|complete|process|directly)|unable to (?:access|perform|complete|process)|"
    r"no (?:backend )?tool (?:here|available)|outside (?:of )?what I can do)", re.I)
GENERIC_FEEDBACK = ("Harness check (not shown to the customer): this was not sent or executed. Review the policy and "
                    "the evidence you have, then continue.")
BLOCK_FEEDBACK = "Not executed: blocked by a policy check."
WITHHELD = {
    "verification_before_write": ("Before I can make that change, I need to verify your identity. Could you confirm "
                                  "your full name and the email address or phone number on your account?"),
    "ids_observed": ("I haven't made that change yet: I still need to confirm the exact account details it applies "
                         "to. Could you tell me which account or card you mean?"),
}


@dataclass
class Finding:
    gate: str
    message: str                       # structured remediation
    call_ids: list[str] = field(default_factory=list)  # empty: the whole draft (a text reply)
    detail: dict = field(default_factory=dict)


# ---- what the agent has seen --------------------------------------------------------------------------------

def searches(ev: Evidence) -> list[str]:
    return [str((c.get("arguments") or {}).get("query", "")) for c, r in ev.results()
            if c["name"] == KB and not r.get("error")]


def kb_names(ev: Evidence, names: set[str]) -> list[str]:
    """Registry names from `names` in successful KB results, in the order first seen. Matched as whole words against
    the registry, not by pattern: customer tools such as get_card_last_4_digits have no numeric suffix."""
    pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b") if names else None
    out: list[str] = []
    for c, r in ev.results():
        text = r.get("content") or ""
        if pattern and c["name"] == KB and not r.get("error") and not text.lstrip().startswith("Error"):
            for m in pattern.finditer(text):
                if m.group(1) not in out:
                    out.append(m.group(1))
    return out


def used_names(ev: Evidence) -> set[str]:
    """Discoverable tools the agent has called or handed over successfully (direct or via the wrappers)."""
    used = set()
    for c, r in ev.results():
        text = (r.get("content") or "").lstrip()
        if r.get("error") or text.startswith("Error"):
            continue
        if c["name"] == "give_discoverable_user_tool":
            used.add((c.get("arguments") or {}).get("discoverable_tool_name"))
        elif c["name"] != "unlock_discoverable_agent_tool":
            used.add(target(c)[0])
    return used


def unused_tools(ev: Evidence, agent_tools: set[str], user_tools: set[str], tool_type) -> tuple[list[str], list[str]]:
    """(agent READ tools, customer tools) named in retrieved documents and not yet used. Writes are never suggested."""
    used = used_names(ev)
    reads = [n for n in kb_names(ev, agent_tools) if n not in used and tool_type(n) == "read"]
    users = [n for n in kb_names(ev, user_tools) if n not in used]
    return reads[:MAX_NAMES], users[:MAX_NAMES]


def is_denial(text: str | None) -> bool:
    return bool(text) and bool(DENIAL.search(text))


# ---- gates --------------------------------------------------------------------------------------------------

def gate_search_before_giving_up(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    calls = proposal.get("tool_calls") or []
    transfer = [c for c in calls if c["name"] == TRANSFER]
    denial = not calls and is_denial(proposal.get("content"))
    if not (transfer or denial):
        return []
    queries = searches(ev)
    reads, users = unused_tools(ev, ctx["agent_tools"], ctx["user_tools"], ctx["tool_type"])
    # The failure signature is never using the discovery mechanism at all. An agent that has already called or handed
    # over a discovered tool is following a documented procedure (e.g. an emergency tool, then a transfer), so other
    # tools named in its search results are not a reason to hold it.
    engaged = bool(used_names(ev) & (ctx["agent_tools"] | ctx["user_tools"]))
    if engaged:
        reads, users = [], []
    if len(queries) >= MIN_SEARCHES and not reads and not users:
        return []
    what = "transfer the customer to a human agent" if transfer else "tell the customer this can't be done"
    parts = [f"Harness check (not shown to the customer): you are about to {what}. Before you do:"]
    if len(queries) < MIN_SEARCHES:
        done = "; ".join(f'"{q[:80]}"' for q in queries[-3:]) or "none"
        parts.append(f"- You have searched the knowledge base {len(queries)} time(s) (queries: {done}). The procedure for "
                     "a request is usually in its own document: search again with different wording that names the "
                     "specific product and the action the customer asked for.")
    if reads:
        parts.append(f"- Documents you retrieved name lookup tools you have not used: {', '.join(reads)}. You can call "
                     "them directly now.")
    if users:
        parts.append(f"- Documents you retrieved name customer tools you have not handed over: {', '.join(users)} "
                     "(give_discoverable_user_tool).")
    parts.append("Use a tool only if its documented procedure fits this request and its prerequisites are met. Transfer "
                 "if a retrieved procedure requires it, or if no documented procedure fits after searching. This check "
                 "does not authorize any action.")
    return [Finding("search_before_giving_up", "\n".join(parts), [c["id"] for c in transfer],
                    {"searches": len(queries), "unused_reads": reads, "unused_customer_tools": users,
                     "trigger": "transfer" if transfer else "denial"})]


def gate_clock_before_verification(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    out = []
    for c in proposal.get("tool_calls") or []:
        if _verification_time_from_clock(c, ev).allowed:
            continue
        readings = sorted(ev.clock_readings())
        stated = (target(c)[1] or {}).get("time_verified")
        fix = (f"Use the exact reading you received: '{readings[-1]}'." if readings else
               "Call get_current_time now and use the exact value it returns.")
        out.append(Finding("clock_before_verification",
                           f"Not executed: log_verification needs time_verified to be a time returned by get_current_time "
                           f"in this conversation (you gave '{stated}'). {fix}", [c["id"]],
                           {"stated": stated, "readings": readings}))
    return out


def gate_verification_before_write(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    out = []
    for c in proposal.get("tool_calls") or []:
        if _write_requires_verification_log(c, ev).allowed:
            continue
        name = target(c)[0]
        out.append(Finding("verification_before_write",
                           f"Not executed: {name} changes the customer's account, and no identity verification is logged "
                           "in this conversation. The policy requires verifying identity first: look up the customer's "
                           f"record ({', '.join(LOOKUPS)}), check that the details they gave match it, call "
                           "get_current_time, then call log_verification. Then retry this action if it is still "
                           "appropriate.", [c["id"]], {"tool": name}))
    return out


def observed_text(ev: Evidence) -> str:
    """Everything the agent has legitimately been told: successful tool results and the customer's messages."""
    from bench.continuation import receipt_ok

    parts = [r.get("content") or "" for c, r in ev.results() if not r.get("error") and receipt_ok(c["name"], r.get("content"))]
    parts += [m.get("content") or "" for m in ev.messages if m.get("role") == "user"]
    return "\n".join(parts)


def _id_args(args: dict):
    from bench import evidence as evidence_mod

    for path, key, value in evidence_mod._leaves(args or {}):
        if key != "agent_tool_name" and (evidence_mod.ID_KEY.search(key) or evidence_mod.DIGITS_KEY.search(key)):
            if value not in (None, ""):
                yield path, str(value).strip()


def gate_ids_observed(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    from bench import evidence as evidence_mod

    out = []
    seen = None
    for c in proposal.get("tool_calls") or []:
        name, args = target(c)
        if c["name"] in ("unlock_discoverable_agent_tool", "give_discoverable_user_tool"):
            continue
        if name != "log_verification" and ctx["tool_type"](name) != "write":
            continue
        if name == "log_verification":
            args = {"user_id": (args or {}).get("user_id")}
        seen = observed_text(ev) if seen is None else seen
        bad = [(path, v) for path, v in _id_args(args) if not re.search(r"(?<![\w-])" + re.escape(v) + r"(?![\w-])", seen)]
        if name != "log_verification":
            try:  # stricter evidence (ownership, amounts): assessed and logged only
                a = evidence_mod.check_arguments(c, proposal.get("content"), ev)
                ctx["events"].append({"event": "evidence_assessed", "tool": name, "allowed": a.allowed,
                                      "findings": a.findings, "flags": a.flags, "enforced": False})
            except Exception as e:  # noqa: BLE001 - logging only
                ctx["events"].append({"event": "checker_error", "tool": name, "detail": f"{type(e).__name__}: {e}"[:300]})
        if not bad:
            continue
        reads = [n for n in ctx.get("offered_reads", []) if n != name]
        where = (f" Lookups you can call: {', '.join(reads[:MAX_NAMES])}." if reads else
                 f" Look it up first (for the customer: {', '.join(LOOKUPS)}; for their products, the lookup tool the "
                 "relevant procedure names), or ask the customer.")
        problems = "; ".join(f"{p}='{v}'" for p, v in bad)
        out.append(Finding("ids_observed",
                           f"Not executed: {name} uses values that have not appeared in any successful tool result or in "
                           f"the customer's messages in this conversation ({problems}). Use exact values you have "
                           f"retrieved or the customer has given.{where}", [c["id"]], {"tool": name, "unobserved": bad}))
    return out


GATE_FUNCS = {
    "search_before_giving_up": gate_search_before_giving_up,
    "clock_before_verification": gate_clock_before_verification,
    "verification_before_write": gate_verification_before_write,
    "ids_observed": gate_ids_observed,
}


def review(proposal: dict, ev: Evidence, ctx: dict, gates=GATES) -> list[Finding]:
    """Findings for one proposal. Hard gates first: a write that fails verification is reported once, by the first
    hard gate that fails (their remediation overlaps), and the soft gate only runs when no hard gate fired."""
    if ev.tool_type is None:
        raise GuardConfigError("harness checks need tool-type metadata (the toolkit was not attached)")
    found: list[Finding] = []
    flagged: set[str] = set()
    for g in ("verification_before_write", "clock_before_verification", "ids_observed"):
        if g in gates:
            for f in GATE_FUNCS[g](proposal, ev, ctx):
                if not set(f.call_ids) & flagged:
                    found.append(f)
                    flagged |= set(f.call_ids)
    if not found and "search_before_giving_up" in gates:
        found += gate_search_before_giving_up(proposal, ev, ctx)
    return found


def feedback_text(f: Finding, mode: str) -> str:
    if mode == "structured":
        return f.message
    if mode == "generic":
        return GENERIC_FEEDBACK
    return BLOCK_FEEDBACK


def active_gates(gates, mode: str) -> tuple[str, ...]:
    """'block' mode has no remediation to give a soft advisory, so the soft gate is off in it."""
    return tuple(g for g in gates if mode != "block" or g in HARD)


# ---- the agent ----------------------------------------------------------------------------------------------

def make_harness_agent_class():
    import tau2.agent.llm_agent as llm_agent_module
    from tau2.data_model.message import AssistantMessage, SystemMessage, ToolMessage

    from bench.adapter import make_direct_tools_agent_class

    DirectToolsAgent = make_direct_tools_agent_class()

    class HarnessAgent(DirectToolsAgent):
        """DirectToolsAgent (the adapter) with the v1 checks. The runner sets `adapter_toolkit`, `agent_tool_names`
        and `user_tool_names`. `use_adapter=False` keeps the benchmark's wrapper interface (for the ablation)."""

        gates: tuple[str, ...] = GATES
        feedback: str = "structured"
        use_adapter: bool = True
        user_tool_names: frozenset = frozenset()

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.harness_events: list[dict] = []
            self.regenerations = 0

        def _generate(self, state):
            tools = list(self.tools) + [t for n, t in sorted(self.offered.items())
                                        if n not in {x.name for x in self.tools}]
            # llm_agent's own `generate`, looked up at call time, so the budget meters and tags it as "agent"
            return llm_agent_module.generate(model=self.llm, tools=tools, messages=state.system_messages + state.messages,
                                             call_name="agent_response", **self.llm_args)

        def _ctx(self, ev):
            lookup = ev.tool_type
            return {"agent_tools": set(self.agent_tool_names), "user_tools": set(self.user_tool_names),
                    "tool_type": lookup, "events": self.harness_events,
                    "offered_reads": [n for n in sorted(self.offered) if lookup(n) == "read"]}

        def _hold(self, proposal, findings, state):
            """Put the draft and its private feedback into the model's history (never the trajectory)."""
            state.messages.append(proposal)
            by_call = {cid: f for f in findings for cid in f.call_ids}
            whole = [f for f in findings if not f.call_ids]
            for tc in proposal.tool_calls or []:
                f = by_call.get(tc.id)
                text = feedback_text(f, self.feedback) if f else (
                    feedback_text(whole[0], self.feedback) if whole else
                    "Not executed: another call in the same message was held by a harness check.")
                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant", content=text,
                                                  error=f is not None))
            if not proposal.tool_calls:
                state.messages.append(SystemMessage(role="system", content=feedback_text(whole[0], self.feedback)))

        def generate_next_message(self, message, state):
            if self.adapter_toolkit is None:
                raise RuntimeError("HarnessAgent needs adapter_toolkit (the environment's toolkit)")
            self._absorb(message, state)
            if self.use_adapter:
                harness = self._unlock_turn(state)
                if harness is not None:
                    return harness, state  # not added to the model's history
            gates = active_gates(self.gates, self.feedback)
            proposal = self._generate(state)
            corrections = 0
            advised = False
            while True:
                ev = Evidence(messages=messages_as_dicts(state.messages),
                              tool_type=toolkit_type_lookup(self.adapter_toolkit))
                draft = messages_as_dicts([proposal])[0]
                findings = review(draft, ev, self._ctx(ev), gates)
                if advised:  # the soft check advises once per give-up; a repeated give-up is released
                    findings = [f for f in findings if f.gate != "search_before_giving_up"]
                if not findings:
                    break
                budget_left = corrections < MAX_CORRECTIONS and self.regenerations < MAX_REGENERATIONS
                if not budget_left:
                    hard_kept = [f for f in findings if f.gate not in RELEASE_WHEN_EXHAUSTED]
                    if hard_kept:
                        self.harness_events.append({"event": "withheld", "gates": [f.gate for f in hard_kept],
                                                    "draft_text": proposal.content,
                                                    "tool_calls": draft.get("tool_calls")})
                        reply = AssistantMessage(role="assistant", content=WITHHELD[hard_kept[0].gate])
                        state.messages.append(reply)
                        return reply, state
                    self.harness_events.append({"event": "released", "gates": [f.gate for f in findings]})
                    break
                for f in findings:
                    self.harness_events.append({"event": "held", "gate": f.gate, "feedback": self.feedback,
                                                "attempt": corrections, "detail": f.detail,
                                                "message": feedback_text(f, self.feedback),
                                                "draft_text": proposal.content, "tool_calls": draft.get("tool_calls")})
                advised = advised or any(f.gate == "search_before_giving_up" for f in findings)
                self._hold(proposal, findings, state)
                corrections += 1
                self.regenerations += 1
                proposal = self._generate(state)  # every regenerated proposal is reviewed again
            state.messages.append(proposal)
            return (self._translate(proposal) if self.use_adapter else proposal), state

    return HarnessAgent


def replay_saved(trace_messages: list[dict], agent_tools: set[str], user_tools: set[str], tool_type,
                 gates=GATES) -> list[dict]:
    """Offline: which checks would have fired at each agent proposal of a saved conversation, judged from the
    messages the agent had seen before it. Nothing is regenerated; this counts first firings only."""
    from bench.continuation import agent_visible

    out = []
    for i, m in enumerate(trace_messages):
        if m["role"] != "assistant":
            continue
        ev = Evidence(messages=list(agent_visible(trace_messages, i)), tool_type=tool_type)
        ctx = {"agent_tools": agent_tools, "user_tools": user_tools, "tool_type": tool_type, "events": [],
               "offered_reads": [n for n in kb_names(ev, agent_tools) if tool_type(n) == "read"]}
        draft = {"role": "assistant", "content": m.get("content"), "tool_calls": m.get("tool_calls") or []}
        for f in review(draft, ev, ctx, gates):
            out.append({"i": i, "gate": f.gate, "detail": f.detail})
    return out
