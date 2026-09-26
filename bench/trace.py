"""Turn a tau2 simulation (complete or partial) into one self-describing JSON trace."""

import re

import litellm

from bench.budget import TRANSIENT_ERRORS

SCHEMA_VERSION = 2
RETRIEVAL_TOOLS = {"KB_search", "KB_search_bm25", "KB_search_dense", "grep", "shell"}
DOC_ID = re.compile(r"doc_[A-Za-z0-9_()\-]+")
SIDE_CHANNEL_TOOL = "list_discoverable_agent_tools"


class ConfigError(Exception):
    """The run was refused before it started (bad task, missing credential, integrity check, ...)."""


# Attributed causes. The official evaluator's reward and tau2's termination reason are recorded
# separately and never overwritten; this is our reading of *why*, with the evidence used.
NONE = "none"  # the task was solved
AGENT_PER_EVALUATOR = "agent_per_official_evaluator"  # ended normally, evaluator scored < 1
AGENT = "agent"
USER_SIMULATOR = "user_simulator"
GRADER = "grader"
MIXED = "mixed"
PROVIDER = "provider"
CONFIGURATION = "configuration"
INTERRUPTED = "interrupted"
HARNESS = "harness"
UNATTRIBUTED = "unattributed"  # needs trace review
UNCLASSIFIED = "unclassified"  # a state this code does not recognise

AGENT_CAUSES = {NONE, AGENT_PER_EVALUATOR, AGENT}


def attribute(termination_reason: str | None, reward: float | None, error: BaseException | None,
              messages: list[dict], ledger: list[dict]) -> dict:
    if error is not None:
        name = f"{type(error).__name__}: {error}"[:500]
        failing_role = getattr(error, "aep_role", None)
        kind = type(error).__name__
        if kind in {"BudgetExceeded", "KeyboardInterrupt", "SystemExit"}:
            return {"cause": INTERRUPTED, "evidence": name}
        if kind == "BoundViolation":
            return {"cause": HARNESS, "evidence": f"spend bound assumption violated: {name}"}
        if isinstance(error, litellm.ContextWindowExceededError):
            return {"cause": failing_role or UNATTRIBUTED, "evidence": f"context window exceeded in {failing_role} call: {name}"}
        if isinstance(error, (ConfigError, litellm.AuthenticationError, litellm.NotFoundError,
                              litellm.PermissionDeniedError, litellm.BadRequestError)) or kind in {
                "PriceMissing", "PinMismatch", "InvalidValue", "RequestNotAllowed"}:
            return {"cause": CONFIGURATION, "evidence": name}
        if isinstance(error, (*TRANSIENT_ERRORS, litellm.APIError)):
            return {"cause": PROVIDER, "evidence": f"{name} (in {failing_role} call)"}
        return {"cause": HARNESS, "evidence": name}

    if termination_reason in ("agent_stop", "user_stop"):
        if reward is None:
            return {"cause": UNCLASSIFIED, "evidence": "ended normally but has no official reward"}
        if reward >= 1.0 - 1e-6:
            return {"cause": NONE, "evidence": f"{termination_reason}, reward={reward}"}
        return {"cause": AGENT_PER_EVALUATOR,
                "evidence": f"{termination_reason}, reward={reward}. The evaluator does not detect "
                            "user-simulator mistakes; confirm by reading the trace"}
    if termination_reason == "agent_error":
        return {"cause": AGENT, "evidence": "agent broke the communication protocol"}
    if termination_reason == "user_error":
        return {"cause": USER_SIMULATOR, "evidence": "user simulator broke the communication protocol"}
    if termination_reason == "too_many_errors":
        by = {}
        for m in messages:
            if m["role"] == "tool" and m.get("error"):
                by[m.get("requestor")] = by.get(m.get("requestor"), 0) + 1
        cause = AGENT if set(by) == {"assistant"} else USER_SIMULATOR if set(by) == {"user"} else MIXED
        return {"cause": cause, "evidence": f"tool errors by requestor: {by}"}
    if termination_reason == "max_steps":
        counts = {}
        for m in messages:
            counts[m["role"]] = counts.get(m["role"], 0) + 1
        return {"cause": UNATTRIBUTED, "evidence": f"step limit reached; messages by role: {counts}"}
    if termination_reason == "timeout":
        seconds = {}
        for c in ledger:
            seconds[c["role"]] = round(seconds.get(c["role"], 0.0) + (c.get("duration_s") or 0.0), 1)
        return {"cause": UNATTRIBUTED, "evidence": f"wall-clock limit reached; model-call seconds by role: {seconds}"}
    if termination_reason == "infrastructure_error":
        return {"cause": PROVIDER, "evidence": termination_reason}
    return {"cause": UNCLASSIFIED, "evidence": f"termination_reason={termination_reason!r}"}


NOT_A_MEASUREMENT = {PROVIDER, CONFIGURATION, INTERRUPTED, HARNESS, UNCLASSIFIED}


def research_eligibility(trace: dict) -> dict:
    """Whether the run can be used, separately for reliability (task outcome) and cost analysis.

    Ineligible runs are kept and reported, never silently dropped. Timeouts, step limits and
    user-simulator failures stay in the primary scheduled-trial result (the official evaluator scored
    them); their causes are flagged for a clearly labelled secondary analysis. Unresolved billing
    affects cost analysis only.
    """
    common, flags = [], []
    if trace.get("mode") == "mock":
        common.append("mock run (scripted responses)")
    if trace.get("missing_fields"):
        common.append("trace incomplete")

    reliability = list(common)
    if trace.get("evaluation") is None:
        reliability.append("no official evaluation")
    cause = (trace.get("attribution") or {}).get("cause")
    if cause in NOT_A_MEASUREMENT:
        reliability.append(f"run did not measure the agent: cause is {cause}")
    elif cause not in AGENT_CAUSES:
        flags.append(f"secondary analysis: failure cause is {cause}")

    cost = list(common)
    if (trace.get("spend", {}).get("incurred") or {}).get("unresolved_calls"):
        cost.append("spend has unresolved calls")

    indep = trace.get("answer_independence") or {}
    if indep.get("agent_visible_outputs_depending_on_hidden_reference"):
        flags.append("agent saw output that depends on hidden reference data (benchmark side channel)")
    if indep.get("conclusive") is False:
        flags.append("answer-independence check inconclusive (nondeterministic outputs or check error)")
    if indep and indep.get("replay_matches_recorded") is False:
        flags.append("environment replay did not reproduce the recorded tool outputs")
    if trace.get("config", {}).get("retrieval_config") != "alltools":
        flags.append(f"non-official retrieval config: {trace.get('config', {}).get('retrieval_config')}")
    return {"reliability": {"eligible": not reliability, "reasons": reliability},
            "cost": {"eligible": not cost, "reasons": cost},
            "flags": flags}


def serialize_messages(messages) -> list[dict]:
    out = []
    for i, m in enumerate(messages or []):
        d = {"i": i, "role": m.role, "turn_idx": m.turn_idx, "timestamp": m.timestamp}
        if m.role == "tool":
            d.update({"tool_call_id": m.id, "requestor": m.requestor, "error": m.error, "content": m.content})
        else:
            d["content"] = m.content
            d["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                               for tc in (m.tool_calls or [])] or None
            d["usage"] = m.usage
            d["cost_reported_by_benchmark"] = m.cost
            d["provider_model"] = (m.raw_data or {}).get("model") if m.raw_data else None
        out.append(d)
    return out


def tool_calls(messages: list[dict]) -> list[dict]:
    """Each tool call paired with its result, in order. `by` is who called it: agent or user."""
    results = {m["tool_call_id"]: m for m in messages if m["role"] == "tool"}
    calls = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            r = results.get(tc["id"], {})
            calls.append({
                "message_i": m["i"],
                "by": "agent" if m["role"] == "assistant" else "user",
                "name": tc["name"],
                "arguments": tc["arguments"],
                "result_i": r.get("i"),
                "error": r.get("error"),
                "result": r.get("content"),
            })
    return calls


def retrievals(calls: list[dict]) -> list[dict]:
    return [{
        "message_i": c["message_i"],
        "tool": c["name"],
        "arguments": c["arguments"],
        "doc_ids_returned": sorted(set(DOC_ID.findall(c["result"] or ""))),
        "error": c["error"],
    } for c in calls if c["name"] in RETRIEVAL_TOOLS]


def missing_fields(trace: dict) -> list[str]:
    """What a complete trace must contain to be analysed and reproduced. Empty list = complete."""
    missing = []

    def need(ok: bool, name: str):
        if not ok:
            missing.append(name)

    prov, bench, cfg = trace.get("provenance") or {}, trace.get("benchmark") or {}, trace.get("config") or {}
    need(bool(prov.get("repo_revision")), "provenance.repo_revision")
    need(bool(bench.get("tau2_commit")) and bool(bench.get("runtime_tasks_sha256")), "benchmark revision + task hash")
    need(all(cfg.get(k) is not None for k in ("task_id", "retrieval_config", "seed", "max_steps")), "config")
    need(bool(cfg.get("agent", {}).get("model_requested")) and bool(cfg.get("user_simulator", {}).get("model_requested")),
         "config.models_requested")
    need(bool((trace.get("agent_inputs") or {}).get("passed")), "agent_inputs integrity check passed")
    msgs = trace.get("messages") or []
    need(len(msgs) > 1, "messages")
    need(all(c.get("result_i") is not None for c in trace.get("tool_calls") or []), "every tool call has a result")
    need(bool(trace.get("termination_reason")), "termination_reason")
    ev = trace.get("evaluation") or {}
    need(ev.get("reward") is not None and ev.get("reward_basis") is not None, "evaluation.reward + reward_basis")
    observed = trace.get("models_observed") or {}
    need("assistant" in observed and "user" in observed, "models_observed for agent and user")
    spend = trace.get("spend") or {}
    need(spend.get("incurred") is not None and spend.get("reported_by_benchmark") is not None, "spend")
    need(all(c.get("status") != "in_flight" for c in spend.get("ledger") or []), "no call left in flight")
    need(trace.get("answer_independence") is not None, "answer_independence check")
    return missing


def models_observed(messages: list[dict]) -> dict:
    seen: dict[str, set] = {}
    for m in messages:
        if m.get("provider_model"):
            seen.setdefault(m["role"], set()).add(m["provider_model"])
    return {role: sorted(models) for role, models in seen.items()}
