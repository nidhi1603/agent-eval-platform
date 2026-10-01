"""Resume a saved conversation just before a known disclosure, with the disclosure check on (targeted recovery test).

The saved agent message at trajectory index `end` disclosed a stored identity value. Here:
1. The saved draft is passed through the CURRENT disclosure check (`gate_identity_disclosure`) on the model's own
   history before it. It must be replaced deterministically (verification-related, text-only); the replacement is
   what the customer receives instead. Nothing about the draft is regenerated.
2. tau2's own initial-state path restores the conversation: the environment replays every tool call in
   trajectory[:end] (tau2 `set_state`, strict: a state-changing call whose result differs raises) and the user
   simulator gets the customer-visible history plus the replacement.
3. The harness agent gets the model's OWN saved history (model_view, held drafts marked undelivered) up to the
   draft, plus the replacement, and the tools that were unlocked by then.
4. The conversation then continues live (agent and user simulator), bounded by max_steps and the run's budget.

Checks before any model call (`prepare`, $0): the draft is in the model view; the customer is not yet verified;
the check replaces the draft; the customer-visible prefixes of trajectory and model view agree; the trajectory
prefix ends with the agent's turn (so the replacement is a valid next message).

Limits, stated: the harness's own counters (regenerations, capability searches done, soft checks fired) start at
zero; tools the source run had offered are restored from the unlock receipts in the prefix. This is selected
development testing at known failure points, never a benchmark score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bench import REPO_ROOT


class ResumeError(Exception):
    """The saved state cannot be resumed faithfully. Raised before any network call."""


def _tau2(m: dict):
    from tau2.data_model.message import AssistantMessage, SystemMessage, ToolCall, ToolMessage, UserMessage

    role = m["role"]
    calls = [ToolCall(id=c["id"], name=c["name"], arguments=c.get("arguments") or {},
                      requestor=c.get("requestor") or ("user" if role == "user" else "assistant"))
             for c in m.get("tool_calls") or []] or None
    if role == "assistant":
        return AssistantMessage(role="assistant", content=m.get("content"), tool_calls=calls)
    if role == "user":
        return UserMessage(role="user", content=m.get("content"), tool_calls=calls)
    if role == "tool":
        return ToolMessage(id=m["tool_call_id"], role="tool", content=m.get("content"),
                           requestor=m.get("requestor") or "assistant", error=bool(m.get("error")))
    if role == "system":
        return SystemMessage(role="system", content=m.get("content"))
    raise ResumeError(f"unexpected role {role!r}")


def _texts(msgs, role):
    return [m.get("content") for m in msgs if m["role"] == role and m.get("content") and not m.get("tool_calls")
            and not m.get("undelivered")]


@dataclass
class Prepared:
    task_id: str
    end: int
    replacement: str
    finding: dict
    trajectory_history: list      # tau2 messages: trajectory[:end] + replacement
    model_history: list           # tau2 messages: the model's own history before the draft + replacement
    offered: list[str]
    undelivered: list[int]        # indices in model_history of drafts the customer never received
    draft_text: str
    checks: dict


def prepare(source_trace: str, end: int) -> Prepared:
    from bench import harness, verify_evidence as ve
    from bench.guard import Evidence
    from bench.identity_disclosure import verified_user_ids

    t = json.loads((REPO_ROOT / source_trace).read_text())
    traj = [{k: v for k, v in m.items()} for m in t["messages"]]
    view = (t.get("harness") or {}).get("model_view")
    if not view:
        raise ResumeError("the source run saved no model view")
    draft = traj[end]
    if draft["role"] != "assistant" or not draft.get("content") or draft.get("tool_calls"):
        raise ResumeError(f"message {end} is not an agent text")
    if traj[end - 1]["role"] not in ("user", "tool"):
        raise ResumeError("the message before the draft is not a customer or tool turn")
    view = ve.mark_undelivered(view, traj)
    ks = [k for k, m in enumerate(view) if m["role"] == "assistant" and m.get("content") == draft["content"]
          and not m.get(ve.UNDELIVERED)]
    if len(ks) != 1:
        raise ResumeError(f"the draft occurs {len(ks)} times in the model view (need exactly 1)")
    k = ks[0]
    prefix_view, prefix_traj = view[:k], traj[:end]
    checks = {
        "customer_text_prefix_equal": _texts(prefix_view, "user") == _texts(prefix_traj, "user"),
        "delivered_agent_text_prefix_equal": _texts(prefix_view, "assistant") == _texts(prefix_traj, "assistant"),
        "not_verified_before": not verified_user_ids(prefix_traj),
    }
    found = harness.gate_identity_disclosure({"content": draft["content"]},
                                             Evidence(messages=prefix_view, tool_type=lambda n: None), {"events": []})
    checks["check_replaces_the_draft"] = bool(found) and bool(found[0].detail.get("replace"))
    if not all(checks.values()):
        raise ResumeError(f"fidelity checks failed: {checks}")
    replacement = harness.withheld_reply(found[0])
    reply = {"role": "assistant", "content": replacement}
    calls = {c["id"]: c for m in prefix_traj if m["role"] == "assistant" for c in m.get("tool_calls") or []}
    offered = sorted({(calls[m["tool_call_id"]]["arguments"] or {}).get("agent_tool_name")
                      for m in prefix_traj if m["role"] == "tool" and m.get("tool_call_id") in calls
                      and calls[m["tool_call_id"]]["name"] == "unlock_discoverable_agent_tool"
                      and not m.get("error") and (m.get("content") or "").startswith("Tool unlocked:")} - {None})
    model_history = [_tau2(m) for m in prefix_view] + [_tau2(reply)]
    return Prepared(task_id=t["task"]["id"], end=end, replacement=replacement,
                    finding={"fields": found[0].detail["fields"], "origins": found[0].detail["origins"]},
                    trajectory_history=[_tau2(m) for m in prefix_traj] + [_tau2(reply)],
                    model_history=model_history, offered=offered, draft_text=draft["content"],
                    undelivered=[i for i, m in enumerate(prefix_view) if m.get(ve.UNDELIVERED)],
                    checks={**checks, "model_view_index": k, "undelivered_in_prefix": sum(bool(m.get(ve.UNDELIVERED)) for m in prefix_view)})
