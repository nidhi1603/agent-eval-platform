"""Turn a tau2 simulation (complete or partial) into one self-describing JSON trace."""

import re

import litellm

from bench.budget import TRANSIENT_ERRORS, BudgetExceeded, PriceMissing

SCHEMA_VERSION = 1
RETRIEVAL_TOOLS = {"KB_search", "KB_search_bm25", "KB_search_dense", "grep", "shell"}
DOC_ID = re.compile(r"doc_[A-Za-z0-9_()\-]+")

# Outcome classes. Only agent_success / agent_failure are agent results; everything else means the
# run did not produce a valid measurement of the agent and must be reported separately.
AGENT_SUCCESS = "agent_success"
AGENT_FAILURE = "agent_failure"
CONFIGURATION_FAILURE = "configuration_failure"
PROVIDER_FAILURE = "provider_failure"
SIMULATOR_FAILURE = "simulator_failure"
INTERRUPTED = "interrupted"
HARNESS_ERROR = "harness_error"


class ConfigError(Exception):
    """The run was refused before it started (bad task, missing credential, integrity check, ...)."""


def classify(termination_reason: str | None, reward: float | None, error: BaseException | None) -> dict:
    if error is not None:
        name = f"{type(error).__name__}: {error}"[:500]
        if isinstance(error, (BudgetExceeded, KeyboardInterrupt, SystemExit)):
            return {"class": INTERRUPTED, "detail": name}
        if isinstance(error, litellm.ContextWindowExceededError):
            return {"class": AGENT_FAILURE, "detail": f"context window exceeded: {name}"}
        if isinstance(error, (ConfigError, PriceMissing, litellm.AuthenticationError, litellm.NotFoundError,
                              litellm.PermissionDeniedError, litellm.BadRequestError)):
            return {"class": CONFIGURATION_FAILURE, "detail": name}
        if isinstance(error, (*TRANSIENT_ERRORS, litellm.APIError)):
            return {"class": PROVIDER_FAILURE, "detail": name}
        if type(error).__name__ == "PinMismatch":
            return {"class": CONFIGURATION_FAILURE, "detail": name}
        return {"class": HARNESS_ERROR, "detail": name}
    if termination_reason == "user_error":
        return {"class": SIMULATOR_FAILURE, "detail": "user simulator broke the conversation protocol"}
    if termination_reason == "infrastructure_error":
        return {"class": PROVIDER_FAILURE, "detail": termination_reason}
    if termination_reason == "unexpected_error":
        return {"class": HARNESS_ERROR, "detail": termination_reason}
    if termination_reason in ("agent_stop", "user_stop"):
        ok = reward is not None and reward >= 1.0 - 1e-6
        return {"class": AGENT_SUCCESS if ok else AGENT_FAILURE, "detail": f"{termination_reason}, reward={reward}"}
    return {"class": AGENT_FAILURE, "detail": f"terminated: {termination_reason}"}


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
    return missing


def models_observed(messages: list[dict]) -> dict:
    seen: dict[str, set] = {}
    for m in messages:
        if m.get("provider_model"):
            seen.setdefault(m["role"], set()).add(m["provider_model"])
    return {role: sorted(models) for role, models in seen.items()}
