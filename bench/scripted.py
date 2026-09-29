"""Scripted model responses for zero-cost runs through the real tau2 integration path.

The script replaces only the network call. tau2's own message parsing, orchestrator, environment
tools, user tools and official evaluator all run for real. A scripted run is a test of the
harness, never a benchmark result, and its trace is labelled MOCK.

Script format (JSON):
    {"description": "...",
     "agent": [{"say": "text"} | {"call": "tool_name", "args": {...}} | {"calls": [{"call", "args"}, ...]}, ...],
     "user":  [...same...]}
Steps are consumed in order per role. The simulated user ends the conversation by saying
"###STOP###", exactly as the real user simulator does.
"""

import hashlib
import json
import uuid
from pathlib import Path

import litellm
import numpy as np
from litellm import ModelResponse

from bench.budget import Price, current_role

AGENT_MODEL = "scripted/agent"
USER_MODEL = "scripted/user"
# Invented prices so the budget and ledger arithmetic is exercised. Not real prices.
FAKE_PRICES = {
    AGENT_MODEL: Price(1.0, 2.0, "FAKE price for scripted runs"),
    USER_MODEL: Price(1.0, 2.0, "FAKE price for scripted runs"),
    "text-embedding-3-large": Price(0.1, 0.0, "FAKE price for scripted runs"),
}


class ScriptExhausted(Exception):
    """The conversation asked for more responses than the script provides."""


class ScriptedLLM:
    def __init__(self, script: dict):
        self.steps = {"agent": list(script.get("agent", [])), "user_simulator": list(script.get("user", []))}
        self.used = {"agent": 0, "user_simulator": 0}

    @classmethod
    def from_file(cls, path: Path) -> "ScriptedLLM":
        return cls(json.loads(Path(path).read_text()))

    def __call__(self, model, messages, tools=None, tool_choice=None, **kwargs) -> ModelResponse:
        role = current_role.get()
        if role not in self.steps:
            raise ScriptExhausted(f"no script for role {role!r}")
        i = self.used[role]
        if i >= len(self.steps[role]):
            raise ScriptExhausted(f"{role} script has {i} steps; the conversation needed more")
        self.used[role] += 1
        step = self.steps[role][i]
        message: dict = {"role": "assistant", "content": step.get("say")}
        calls = step.get("calls") or ([{"call": step["call"], "args": step.get("args", {})}] if "call" in step else [])
        if calls:  # "calls": [{"call", "args"}, ...] puts several tool calls in one message
            message["tool_calls"] = [{
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": c["call"], "arguments": json.dumps(c.get("args", {}))},
            } for c in calls]
        try:
            prompt_tokens = litellm.token_counter(model="gpt-4o", messages=messages, tools=tools)
        except Exception:  # noqa: BLE001 - token counts here only feed fake prices
            prompt_tokens = len(json.dumps(messages, default=str)) // 4
        completion_tokens = max(1, len(json.dumps(message)) // 4)
        return ModelResponse(
            model=model,
            choices=[{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": message}],
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                   "total_tokens": prompt_tokens + completion_tokens},
        )


class FakeEmbedder:
    """Deterministic stand-in for OpenAI embeddings (hash-derived vectors). No network, no cost."""

    def __init__(self, model: str = "text-embedding-3-large", **_):
        self.model = model

    def embed(self, texts):
        return np.array([np.frombuffer(hashlib.sha512(t.encode()).digest(), dtype=np.uint8).astype(float)
                         for t in texts])

    def get_name(self) -> str:
        return f"fake_{self.model}"
