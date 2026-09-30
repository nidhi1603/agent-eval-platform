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
                             v3.1 (research/v3_1/README.md): a TRANSFER is held at most once per conversation, and
                             the feedback says the call was not executed and that calling it again will execute it.
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
V2_GATES = GATES + ("duplicate_write", "plan_before_acting", "procedure_checklist", "needs_covered",
                    "transfer_after_asking", "claims_need_receipts")
# v3 = v1's checks + capability search (bench/capability.py); v3.1 = v3 + the explicit, once-only transfer hold
VERSIONS = {"v1": GATES, "v2": V2_GATES, "v3": GATES, "v3.1": GATES}
ALL_GATES = V2_GATES
HARD = {"clock_before_verification", "verification_before_write", "ids_observed", "duplicate_write"}
SOFT = tuple(g for g in V2_GATES if g not in HARD)
PLAN_GATES = {"plan_before_acting", "needs_covered"}  # either one turns on the task_plan tool
ONCE_PER_CONVERSATION = {"plan_before_acting"}
RELEASE_WHEN_EXHAUSTED = {"clock_before_verification"} | set(SOFT)
MAX_PLAN_CALLS_PER_TURN = 3
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
# v3.1's feedback on a held transfer. In H004 every held transfer we can replay (9 of 9) was followed by the agent
# telling the customer a transfer was under way, with none executed: the v1 text never says the call did not run.
TRANSFER_NOT_EXECUTED = ("Harness check (not shown to the customer): your transfer_to_human_agents call was NOT executed. "
                         "The customer has not been transferred and is still with you, so do not tell them a transfer "
                         "is under way. Before you transfer:")
TRANSFER_STILL_OPEN = ("If a transfer is still the right step (a retrieved procedure requires it, or no documented "
                       "procedure fits after searching), call transfer_to_human_agents again: it will be executed, and "
                       "this check will not hold it again in this conversation.")
GENERIC_FEEDBACK = ("Harness check (not shown to the customer): this was not sent or executed. Review the policy and "
                    "the evidence you have, then continue.")
BLOCK_FEEDBACK = "Not executed: blocked by a policy check."
WITHHELD = {
    "verification_before_write": ("Before I can make that change, I need to verify your identity. Could you confirm "
                                  "your full name and the email address or phone number on your account?"),
    "ids_observed": ("I haven't made that change yet: I still need to confirm the exact account details it applies "
                         "to. Could you tell me which account or card you mean?"),
    "duplicate_write": "That change has already been made; I haven't repeated it.",
}
COMPLETION_CLAIM = re.compile(
    r"\b(?:has|have) been (?:frozen|unfrozen|closed|opened|submitted|applied|credited|filed|updated|processed|activated|"
    r"ordered|reset|approved|logged|transferred)\b|\bI(?:[’']ve| have) (?:now )?(?:frozen|unfrozen|closed|opened|submitted|"
    r"applied|credited|filed|updated|processed|activated|ordered|reset|approved)\b|\bis now (?:frozen|closed|open|active)\b",
    re.I)


@dataclass
class Finding:
    gate: str
    message: str                       # structured remediation
    call_ids: list[str] = field(default_factory=list)  # empty: the whole draft (a text reply)
    detail: dict = field(default_factory=dict)


# ---- what the agent has seen --------------------------------------------------------------------------------

def _retrieval_ok(c: dict, r: dict) -> bool:
    """A retrieval call that counts: KB searches as before (no error); a shell command only if it produced output."""
    from bench.kb_evidence import RETRIEVAL_TOOLS, SHELL, succeeded

    return c["name"] in RETRIEVAL_TOOLS and not r.get("error") and (c["name"] != SHELL or succeeded(r))


def searches(ev: Evidence) -> list[str]:
    """Queries (or shell commands) of the agent's retrieval calls: KB_search, or under alltools KB_search_bm25,
    KB_search_dense and shell (bench/kb_evidence.py)."""
    from bench.kb_evidence import query_of

    return [query_of(c) for c, r in ev.results() if _retrieval_ok(c, r)]


def kb_names(ev: Evidence, names: set[str]) -> list[str]:
    """Registry names from `names` in successful retrieval results, in the order first seen. Matched as whole words against
    the registry, not by pattern: customer tools such as get_card_last_4_digits have no numeric suffix."""
    pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b") if names else None
    out: list[str] = []
    for c, r in ev.results():
        text = r.get("content") or ""
        if pattern and _retrieval_ok(c, r) and not text.lstrip().startswith("Error"):  # output only, never a command
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
    explicit = bool(transfer and ctx.get("transfer_hold_once"))  # v3.1
    if explicit and ctx.get("transfer_holds"):
        return []  # already held once in this conversation: the agent was told a repeat would go through
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
    parts = [TRANSFER_NOT_EXECUTED if explicit else
             f"Harness check (not shown to the customer): you are about to {what}. Before you do:"]
    if ctx.get("capability_advice"):
        from bench.capability import ADVICE

        parts.append(ADVICE)
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
    if explicit:
        parts.append("Use a tool only if its documented procedure fits this request and its prerequisites are met; this "
                     "check does not authorize any tool call.")
        parts.append(TRANSFER_STILL_OPEN)
    else:
        parts.append("Use a tool only if its documented procedure fits this request and its prerequisites are met. "
                     "Transfer if a retrieved procedure requires it, or if no documented procedure fits after "
                     "searching. This check does not authorize any action.")
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


# ---- v2 gates (bench/ledger.py) ---------------------------------------------------------------------------------

def _ledger(ev: Evidence, ctx: dict):
    from bench import ledger

    if "ledger" not in ctx:
        ctx["ledger"] = ledger.build(ev.messages, ctx["tool_type"])
    return ctx["ledger"]


def _acting(proposal: dict, ctx: dict) -> dict:
    """What kind of consequential step this draft is: writes, a transfer, or a capability denial."""
    calls = [c for c in proposal.get("tool_calls") or [] if c["name"] != "task_plan"]
    writes = [c for c in calls if c["name"] not in ("unlock_discoverable_agent_tool", "give_discoverable_user_tool")
              and ctx["tool_type"](target(c)[0]) == "write" and target(c)[0] != "log_verification"]
    transfer = [c for c in calls if c["name"] == TRANSFER]
    return {"writes": writes, "transfer": transfer, "denial": not calls and is_denial(proposal.get("content"))}


def _canonical(args) -> str:
    import json

    return json.dumps(args or {}, sort_keys=True, default=str)


def gate_duplicate_write(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    led = _ledger(ev, ctx)
    done = {(w["tool"], _canonical(w["args"])): w for w in led.writes}
    out = []
    for c in _acting(proposal, ctx)["writes"]:
        name, args = target(c)
        w = done.get((name, _canonical(args)))
        if w:
            out.append(Finding("duplicate_write",
                               f"Not executed: {name} with exactly these arguments already succeeded in this conversation "
                               f"(receipt: \"{w['receipt'][:120]}\"). Repeating it would change the account twice. If "
                               "the customer needs a different change, use the arguments for that change.",
                               [c["id"]], {"tool": name}))
    return out


def gate_plan_before_acting(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    act = _acting(proposal, ctx)
    if not (act["writes"] or act["transfer"] or act["denial"]) or _ledger(ev, ctx).plan is not None:
        return []
    return [Finding("plan_before_acting",
                    "Harness check (not shown to the customer): before you change an account, transfer, or say something "
                    "can't be done, record your plan with task_plan: every separate thing the customer wants, and for "
                    "each what you must find out (procedure, eligibility, amounts, tool), with what you have already "
                    "found and its document ID.", [c["id"] for c in act["writes"] + act["transfer"]])]


def gate_procedure_checklist(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    """Before the agent first uses a discovered tool (a write, or handing it to the customer), show it the procedure
    card compiled from the documents it retrieved (bench/compiler.py). Skipped for a tool already shown, and when the
    agent's plan already cites the card's document as a source."""
    from bench import compiler

    calls = proposal.get("tool_calls") or []
    wanted = []
    for c in calls:
        if c["name"] == "give_discoverable_user_tool":
            wanted.append((c, (c.get("arguments") or {}).get("discoverable_tool_name")))
        elif c in _acting(proposal, ctx)["writes"]:
            wanted.append((c, target(c)[0]))
    shown = ctx.get("checklists_shown") or set()
    wanted = [(c, t) for c, t in wanted if t and t not in shown]
    if not wanted:
        return []
    if "cards" not in ctx:
        kb = [r.get("content") or "" for c, r in ev.results() if c["name"] == KB and not r.get("error")]
        ctx["cards"] = compiler.cards_from_results(kb, ctx["agent_tools"] | ctx["user_tools"])
    cited = {n.source for r in (_ledger(ev, ctx).plan or []) for n in r.needs if n.status == "found"}
    out = []
    for c, tool in wanted:
        cards = [k for k in ctx["cards"].get(tool, []) if k.doc_id not in cited
                 and (k.requirements or k.steps or k.customer_points)]
        if not cards:
            continue
        body = "\n".join(k.text(tool) for k in cards[:2])
        out.append(Finding("procedure_checklist",
                           "Harness check (not shown to the customer): before this step, check it against the "
                           f"procedure you retrieved.\n{body}\nConfirm each requirement from what you have established "
                           "(tool results, the customer's answers). If one is not met, or the customer must first be "
                           "asked or told something, do that instead; otherwise continue. This check does not authorize "
                           "the action.", [c["id"]], {"tool": tool, "docs": [k.doc_id for k in cards[:2]]}))
    return out


def gate_needs_covered(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    act = _acting(proposal, ctx)
    led = _ledger(ev, ctx)
    if not (act["writes"] or act["transfer"] or act["denial"]) or led.plan is None:
        return []
    open_needs, unsupported = led.open_needs(), led.unsupported_found()
    if not open_needs and not unsupported:
        return []
    parts = ["Harness check (not shown to the customer): your plan is not covered yet."]
    if open_needs:
        parts.append("Still open: " + "; ".join(f"{n} (for: {r})" for r, n in open_needs[:MAX_NAMES]) +
                     ". Search for each with a query that names it, then update task_plan (found with the doc ID, or "
                     "not_found after trying different wording).")
    if unsupported:
        parts.append("Marked found, but the cited document was not in any search result you received: " +
                     "; ".join(f"{n} ({src or 'no source'})" for n, src in unsupported[:MAX_NAMES]) + ".")
    parts.append("If a remaining need cannot matter for this step, mark it not_found or remove it, and continue.")
    return [Finding("needs_covered", " ".join(parts), [c["id"] for c in act["writes"] + act["transfer"]],
                    {"open": open_needs, "unsupported": unsupported})]


def gate_transfer_after_asking(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    transfer = _acting(proposal, ctx)["transfer"]
    if not transfer or _ledger(ev, ctx).transfer_mentioned_then_customer_replied:
        return []
    return [Finding("transfer_after_asking",
                    "Harness check (not shown to the customer): the policy says not to transfer without asking the "
                    "customer first, unless a retrieved procedure requires an immediate transfer. If none does, ask "
                    "whether they would like to be transferred to a human agent.", [c["id"] for c in transfer])]


def gate_claims_need_receipts(proposal: dict, ev: Evidence, ctx: dict) -> list[Finding]:
    text = proposal.get("content") or ""
    if proposal.get("tool_calls") or not COMPLETION_CLAIM.search(text):
        return []
    led = _ledger(ev, ctx)
    if led.writes or led.tools_given:  # a successful change, or a tool the customer ran themselves
        return []
    return [Finding("claims_need_receipts",
                    "Harness check (not shown to the customer): this reply says a change was made, but no change has "
                    "succeeded in this conversation. Make the change with the right tool first, or tell the customer "
                    "accurately what has and has not been done.", [], {"claim": COMPLETION_CLAIM.search(text).group(0)})]


GATE_FUNCS = {
    "duplicate_write": gate_duplicate_write,
    "plan_before_acting": gate_plan_before_acting,
    "procedure_checklist": gate_procedure_checklist,
    "needs_covered": gate_needs_covered,
    "transfer_after_asking": gate_transfer_after_asking,
    "claims_need_receipts": gate_claims_need_receipts,
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
    for g in ("verification_before_write", "clock_before_verification", "ids_observed", "duplicate_write"):
        if g in gates:
            for f in GATE_FUNCS[g](proposal, ev, ctx):
                if not set(f.call_ids) & flagged:
                    found.append(f)
                    flagged |= set(f.call_ids)
    if found:
        return found
    skip = ctx.get("skip_soft") or set()
    for g in ("plan_before_acting", "procedure_checklist", "needs_covered", "search_before_giving_up",
              "transfer_after_asking", "claims_need_receipts"):
        if g in gates and g not in skip:
            found += GATE_FUNCS[g](proposal, ev, ctx)
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
        dep_search: bool = False     # dependency-following tool search (bench/depsearch.py)
        capability_search: bool = False  # v3: bench/capability.py
        transfer_hold_once: bool = False  # v3.1: a transfer is held at most once, with explicit feedback
        user_tool_names: frozenset = frozenset()

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.harness_events: list[dict] = []
            self.regenerations = 0
            self.soft_fired: dict[str, int] = {}
            self.transfer_holds = 0
            self.plan_calls = 0
            self.checklists_shown: set[str] = set()
            self._dep = None
            self.model_state = None      # the model's own history, saved in the trace's harness audit section
            self.capability_done: set[str] = set()
            self._capability_note: str | None = None
            self._capability_n = 0

        def _dependency_search(self, state, start: int) -> None:
            """Append dependency-search documents to the model's own copy of KB_search results that arrived at
            state.messages[start:]. The benchmark's trajectory keeps the original message objects."""
            from tau2.environment.tool import as_tool

            from bench import depsearch

            if self._dep is None:
                index, docs = depsearch.tool_index(frozenset(self.agent_tool_names) | frozenset(self.user_tool_names),
                                                   str(depsearch.documents_dir()))
                params = {n: list(as_tool(self.adapter_toolkit.tools[n]).openai_schema["function"]["parameters"]
                                  .get("properties", {})) for n in sorted(self.agent_tool_names)}
                self._dep = depsearch.DependencySearch(index, docs, params)
            call_names = {tc.id: tc.name for m in state.messages if getattr(m, "role", None) == "assistant"
                          for tc in (getattr(m, "tool_calls", None) or [])}
            for i in range(start, len(state.messages)):
                m = state.messages[i]
                if getattr(m, "role", None) != "tool" or call_names.get(m.id) != KB or m.error or \
                        (m.content or "").lstrip().startswith("Error"):
                    continue
                earlier = [x.content or "" for x in state.messages[:i] if getattr(x, "role", None) == "tool"]
                known = {k for text in earlier for k in depsearch.KNOWN_ID.findall(text)}
                seen = {d for text in earlier for d in depsearch.DOC_ID.findall(text)}
                n0 = len(self.harness_events)
                extra = self._dep.augment(m.content or "", known, seen, self.harness_events)
                for e in self.harness_events[n0:]:
                    e["kb_call_id"] = m.id   # which search result the documents were appended to
                if extra:
                    state.messages[i] = m.model_copy(update={"content": (m.content or "") + extra})

        def _absorb(self, message, state) -> None:
            start = len(state.messages)
            super()._absorb(message, state)
            if self.dep_search:
                try:
                    self._dependency_search(state, start)
                except Exception as e:  # noqa: BLE001 - fail open, like a checker: the search result is unchanged
                    self.harness_events.append({"event": "dependency_search_error",
                                                "error": f"{type(e).__name__}: {e}"[:300]})

        @property
        def planning(self) -> bool:
            return bool(PLAN_GATES & set(self.gates))

        def _generate(self, state):
            from tau2.environment.tool import as_tool

            from bench import ledger

            tools = list(self.tools) + [t for n, t in sorted(self.offered.items())
                                        if n not in {x.name for x in self.tools}]
            if self.planning:
                tools.append(as_tool(ledger.task_plan))
            # llm_agent's own `generate`, looked up at call time, so the budget meters and tags it as "agent"
            return llm_agent_module.generate(model=self.llm, tools=tools, messages=state.system_messages + state.messages,
                                             call_name="agent_response", **self.llm_args)

        def _ctx(self, ev):
            lookup = ev.tool_type
            return {"agent_tools": set(self.agent_tool_names), "user_tools": set(self.user_tool_names),
                    "tool_type": lookup, "events": self.harness_events, "capability_advice": self.capability_search,
                    "transfer_hold_once": self.transfer_hold_once, "transfer_holds": self.transfer_holds,
                    "offered_reads": [n for n in sorted(self.offered) if lookup(n) == "read"]}

        def _hold(self, proposal, findings, state, in_history=False):
            """Put the draft and its private feedback into the model's history (never the trajectory). When the draft
            is the remainder of a proposal whose task_plan call already ran, the proposal is already there."""
            if not in_history:
                state.messages.append(proposal)
            by_call: dict[str, list] = {}
            for f in findings:
                for cid in f.call_ids:
                    by_call.setdefault(cid, []).append(f)
            whole = [f for f in findings if not f.call_ids]
            whole_text = "\n".join(dict.fromkeys(feedback_text(f, self.feedback) for f in whole))
            for tc in proposal.tool_calls or []:
                fs = by_call.get(tc.id)
                text = ("\n".join(dict.fromkeys(feedback_text(f, self.feedback) for f in fs)) if fs else
                        whole_text or "Not executed: another call in the same message was held by a harness check.")
                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant", content=text,
                                                  error=bool(fs)))
            if not proposal.tool_calls:
                state.messages.append(SystemMessage(role="system", content=whole_text))

        def _run_plan_calls(self, proposal, state):
            """Execute task_plan calls locally. The full proposal and the plan results go into the model's history, in
            that order. Returns the proposal's other calls as a new draft, or None if there are none."""
            from bench import ledger

            state.messages.append(proposal)
            for tc in (x for x in proposal.tool_calls if x.name == ledger.PLAN_TOOL):
                self.plan_calls += 1
                plan, err = ledger.parse_plan(tc.arguments)
                if err:
                    text = f"Plan not recorded: {err}. Call task_plan again with the documented structure."
                else:
                    open_n = [n.need for r in plan for n in r.needs if n.status == "open"]
                    text = (f"Plan recorded: {len(plan)} request(s), {sum(len(r.needs) for r in plan)} need(s)"
                            + (f"; still open: {'; '.join(open_n[:MAX_NAMES])}." if open_n else "; none open."))
                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant", content=text,
                                                  error=bool(err)))
                self.harness_events.append({"event": "plan_invalid" if err else "plan_recorded", "error": err,
                                            "requests": None if err else (tc.arguments or {}).get("requests")})
            rest = [tc for tc in proposal.tool_calls if tc.name != ledger.PLAN_TOOL]
            return proposal.model_copy(update={"tool_calls": rest}) if rest else None

        def _capability_turn(self, search, state, draft=None):
            """A harness turn that runs one capability search through the benchmark's own search tools; no model
            call. The call goes into the model's history so that its results pair up when they arrive. A draft that
            triggered it (a question to the customer) is dropped: neither sent nor kept."""
            from tau2.data_model.message import ToolCall

            from bench import capability

            self._capability_n += 1
            calls = capability.search_calls(search, {t.name for t in self.tools}, self._capability_n)
            self.capability_done.add(search.kind)
            if not calls:
                self.harness_events.append({"event": "capability_search_unavailable", "kind": search.kind})
                return None
            msg = AssistantMessage(role="assistant", content=None, tool_calls=[
                ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"], requestor="assistant") for c in calls])
            state.messages.append(msg)
            self._capability_note = search.note
            self.harness_events.append({"event": "capability_search", "trigger": search.trigger, "kind": search.kind,
                                        "query": search.query, "tools": [c["name"] for c in calls],
                                        "call_ids": [c["id"] for c in calls],
                                        "draft_not_sent": draft.content if draft is not None else None})
            return msg

        def generate_next_message(self, message, state):
            if self.adapter_toolkit is None:
                raise RuntimeError("HarnessAgent needs adapter_toolkit (the environment's toolkit)")
            self.model_state = state
            self._absorb(message, state)
            if self.capability_search:
                from bench import capability

                search = capability.after_verification(messages_as_dicts(state.messages), self.capability_done)
                turn = self._capability_turn(search, state) if search else None
                if turn is not None:
                    return turn, state
            if self.use_adapter:
                harness = self._unlock_turn(state)
                if harness is not None:
                    return harness, state  # not added to the model's history
            if self._capability_note:  # the search results are in: say why the harness searched
                state.messages.append(SystemMessage(role="system", content=self._capability_note))
                self._capability_note = None
            gates = active_gates(self.gates, self.feedback)
            proposal = self._generate(state)
            if self.capability_search:
                search = capability.before_asking(messages_as_dicts([proposal])[0], messages_as_dicts(state.messages),
                                                  self.capability_done)
                turn = self._capability_turn(search, state, draft=proposal) if search else None
                if turn is not None:
                    return turn, state
            in_history = False          # True when `proposal` is the remainder of one already in the history
            corrections = 0
            plan_turns = 0
            advised: set[str] = set()   # soft checks given this turn: each advises once, then releases
            while True:
                if self.planning and any(tc.name == "task_plan" for tc in proposal.tool_calls or []):
                    plan_turns += 1
                    rest = self._run_plan_calls(proposal, state)
                    if rest is None:
                        if plan_turns >= MAX_PLAN_CALLS_PER_TURN:
                            self.harness_events.append({"event": "plan_loop_stopped"})
                            proposal = self._generate(state)
                            calls = [tc for tc in proposal.tool_calls or [] if tc.name != "task_plan"] or None
                            proposal = proposal.model_copy(update={"tool_calls": calls, "content": proposal.content or (
                                None if calls else "Could you tell me a little more about what you need?")})
                            in_history = False
                        else:
                            proposal, in_history = self._generate(state), False  # a plan call is not a correction
                            continue
                    else:
                        proposal, in_history = rest, True
                ev = Evidence(messages=messages_as_dicts(state.messages),
                              tool_type=toolkit_type_lookup(self.adapter_toolkit))
                draft = messages_as_dicts([proposal])[0]
                ctx = self._ctx(ev)
                ctx["skip_soft"] = advised | {g for g in ONCE_PER_CONVERSATION if self.soft_fired.get(g)}
                ctx["checklists_shown"] = self.checklists_shown
                findings = review(draft, ev, ctx, gates)
                if not findings:
                    break
                budget_left = corrections < MAX_CORRECTIONS and self.regenerations < MAX_REGENERATIONS
                if not budget_left:
                    hard_kept = [f for f in findings if f.gate not in RELEASE_WHEN_EXHAUSTED]
                    if hard_kept:
                        self.harness_events.append({"event": "withheld", "gates": [f.gate for f in hard_kept],
                                                    "draft_text": proposal.content,
                                                    "tool_calls": draft.get("tool_calls")})
                        if in_history:  # every call in the history needs a result before the next message
                            for tc in proposal.tool_calls or []:
                                state.messages.append(ToolMessage(id=tc.id, role="tool", requestor="assistant",
                                                                  content="Not executed.", error=True))
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
                    if f.gate in SOFT:
                        advised.add(f.gate)
                        self.soft_fired[f.gate] = self.soft_fired.get(f.gate, 0) + 1
                    if f.gate == "procedure_checklist":
                        self.checklists_shown.add(f.detail["tool"])
                    if f.gate == "search_before_giving_up" and f.detail.get("trigger") == "transfer":
                        self.transfer_holds += 1
                self._hold(proposal, findings, state, in_history=in_history)
                corrections += 1
                self.regenerations += 1
                proposal, in_history = self._generate(state), False  # every regenerated proposal is reviewed again
            if not in_history:
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
