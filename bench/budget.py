"""One spending guard for every paid call a run makes: agent, user simulator, LLM grader, embeddings.

How it bounds spend:
- Before each request, reserve an upper-bound estimate (input tokens x 1.2 at the input price, plus
  the enforced max_tokens at the output price). A request is refused if confirmed spend + held
  upper bounds + in-flight reservations + this estimate would exceed the cap.
- max_tokens is forced on every chat request, so the output side of the estimate is a real bound.
- litellm's hidden retries are disabled (num_retries=0); retries happen here, and each one is a
  separate reservation, so retries count against the cap.
- A successful call is settled at usage x our price table (not litellm's price map, which silently
  reports 0.0 for models it does not know). A failed call keeps its reservation as an upper bound,
  because a provider may bill a request whose response we never received.

What it cannot bound: a provider ignoring max_tokens, or prices in bench/prices.json being wrong.
Both show up as confirmed cost above the reserved estimate, which is recorded per call.
"""

import json
import threading
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest import mock

import litellm

PRICES_FILE = Path(__file__).resolve().parent / "prices.json"

# Which participant is making the current call. Set by tagging each tau2 caller's generate().
current_role: ContextVar[str] = ContextVar("current_role", default="unattributed")

TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.InternalServerError,
    litellm.ServiceUnavailableError,
)


class BudgetExceeded(Exception):
    """The next request could push spend past the approved cap, so it was not sent."""


class PriceMissing(Exception):
    """No verified price for this model: the run cannot bound its spend, so it must not start."""


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    source: str

    def cost(self, input_tokens: float, output_tokens: float) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1e6


def load_prices(path: Path = PRICES_FILE) -> dict[str, Price]:
    entries = json.loads(path.read_text())["models"]
    return {m: Price(e["input_per_mtok"], e["output_per_mtok"], f"{e['source']} (checked {e['checked_on']})")
            for m, e in entries.items()}


@dataclass(frozen=True)
class Limits:
    max_output_tokens: int = 4096
    max_attempts: int = 3  # per request, including the first
    request_timeout_s: float = 120.0
    input_margin: float = 1.2  # token estimates are approximate; reserve for 20% more


@dataclass
class Call:
    seq: int
    kind: str  # "chat" | "embedding"
    role: str
    model: str
    attempt: int
    reserved_usd: float
    status: str = "in_flight"  # -> "ok" | "failed"
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    cost_basis: str | None = None
    provider_model: str | None = None
    error: str | None = None
    duration_s: float | None = None


class Budget:
    def __init__(self, cap_usd: float, prices: dict[str, Price]):
        self.cap_usd = cap_usd
        self._prices = prices
        self._lock = threading.Lock()
        self.calls: list[Call] = []

    def price(self, model: str) -> Price:
        if model not in self._prices:
            raise PriceMissing(f"no verified price for {model!r} in bench/prices.json")
        return self._prices[model]

    def _committed(self) -> float:
        return sum(c.reserved_usd if c.status == "in_flight" else c.cost_usd for c in self.calls)

    def reserve(self, kind: str, model: str, attempt: int, estimate_usd: float) -> Call:
        with self._lock:
            committed = self._committed()
            if committed + estimate_usd > self.cap_usd:
                raise BudgetExceeded(
                    f"{kind} call to {model} needs up to ${estimate_usd:.4f}; ${committed:.4f} of the "
                    f"${self.cap_usd:.2f} cap is already spent or reserved"
                )
            call = Call(len(self.calls) + 1, kind, current_role.get(), model, attempt, estimate_usd)
            self.calls.append(call)
            return call

    def settle_ok(self, call: Call, input_tokens: int, output_tokens: int, provider_model: str | None,
                  started: float) -> None:
        with self._lock:
            call.status, call.input_tokens, call.output_tokens = "ok", input_tokens, output_tokens
            call.cost_usd = self.price(call.model).cost(input_tokens, output_tokens)
            call.cost_basis = "provider usage x bench/prices.json"
            call.provider_model = provider_model
            call.duration_s = round(time.perf_counter() - started, 3)

    def settle_failed(self, call: Call, error: BaseException, started: float) -> None:
        with self._lock:
            call.status, call.error = "failed", f"{type(error).__name__}: {error}"[:500]
            call.cost_usd = call.reserved_usd
            call.cost_basis = "reservation held: no usage returned, provider may still bill"
            call.duration_s = round(time.perf_counter() - started, 3)

    def summary(self) -> dict:
        with self._lock:
            ok = [c for c in self.calls if c.status == "ok"]
            failed = [c for c in self.calls if c.status == "failed"]
            by_role: dict[str, float] = {}
            for c in ok + failed:
                by_role[c.role] = round(by_role.get(c.role, 0.0) + c.cost_usd, 6)
            confirmed = sum(c.cost_usd for c in ok)
            unconfirmed = sum(c.cost_usd for c in failed)
            return {
                "cap_usd": self.cap_usd,
                "confirmed_usd": round(confirmed, 6),
                "unconfirmed_upper_bound_usd": round(unconfirmed, 6),
                "complete_incurred_upper_bound_usd": round(confirmed + unconfirmed, 6),
                "by_role_usd": by_role,
                "calls": len(self.calls),
                "failed_calls": len(failed),
                "calls_over_reservation": sum(1 for c in ok if c.cost_usd > c.reserved_usd),
            }

    def ledger(self) -> list[dict]:
        with self._lock:
            return [asdict(c) for c in self.calls]


def estimate_input_tokens(model: str, messages: list, tools: list | None) -> int:
    try:
        return litellm.token_counter(model=model, messages=messages, tools=tools)
    except Exception:
        return len(json.dumps(messages)) // 3 + len(json.dumps(tools or [])) // 3


def metered_completion(budget: Budget, limits: Limits, send):
    """Wrap a litellm-style completion function with reservation, retries and settlement."""

    def completion(model, messages, tools=None, tool_choice=None, **kwargs):
        price = budget.price(model)
        kwargs["num_retries"] = 0  # retries happen below, each one reserved
        kwargs["max_tokens"] = min(kwargs.get("max_tokens") or limits.max_output_tokens, limits.max_output_tokens)
        kwargs.setdefault("timeout", limits.request_timeout_s)
        est_in = estimate_input_tokens(model, messages, tools) * limits.input_margin
        estimate = price.cost(est_in, kwargs["max_tokens"])
        for attempt in range(1, limits.max_attempts + 1):
            call = budget.reserve("chat", model, attempt, estimate)
            started = time.perf_counter()
            try:
                response = send(model=model, messages=messages, tools=tools, tool_choice=tool_choice, **kwargs)
            except TRANSIENT_ERRORS as e:
                budget.settle_failed(call, e, started)
                if attempt == limits.max_attempts:
                    raise
                time.sleep(min(2 ** attempt, 10))
                continue
            except BaseException as e:
                budget.settle_failed(call, e, started)
                raise
            usage = response.usage
            budget.settle_ok(call, usage.prompt_tokens, usage.completion_tokens, getattr(response, "model", None), started)
            return response
        raise AssertionError("unreachable")

    return completion


def metered_embedder(budget: Budget, base_cls):
    """Subclass of tau2's OpenAIEmbedder whose calls are reserved and settled like chat calls."""
    import numpy as np
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    class MeteredEmbedder(base_cls):
        def embed(self, texts):
            if not texts:
                raise ValueError("No text to embed.")
            tokens = sum(len(enc.encode(t)) for t in texts)
            call = budget.reserve("embedding", self.model, 1, budget.price(self.model).cost(tokens * 1.05, 0))
            started = time.perf_counter()
            try:
                response = self.client.embeddings.create(input=texts, model=self.model)
            except BaseException as e:
                budget.settle_failed(call, e, started)
                raise
            budget.settle_ok(call, response.usage.total_tokens, 0, self.model, started)
            return np.array([item.embedding for item in response.data])

    return MeteredEmbedder


# tau2 modules whose generate() calls we attribute to a role. Every paid chat call goes through
# tau2.utils.llm_utils.completion, so an unlisted caller is still metered, just "unattributed".
ROLE_CALLERS = {
    "tau2.agent.llm_agent": "agent",
    "tau2.user.user_simulator": "user_simulator",
    "tau2.evaluator.evaluator_nl_assertions": "grader",
}


@contextmanager
def install(budget: Budget, limits: Limits, send=None, embedder_cls=None):
    """Route every tau2 paid call through the budget for the duration of the block.

    send: the underlying completion function (litellm.completion when live, a script when mocked).
    embedder_cls: replacement for the "openai" embedder (metered when live, fake when mocked).
    """
    import importlib

    import tau2.utils.llm_utils as llm_utils
    from tau2.knowledge.document_preprocessors import embedding_indexer
    from tau2.knowledge.input_preprocessors import embedding_encoder

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(
            llm_utils, "completion", metered_completion(budget, limits, send or litellm.completion)))
        for module_name, role in ROLE_CALLERS.items():
            module = importlib.import_module(module_name)
            stack.enter_context(mock.patch.object(module, "generate", _tagged(module.generate, role)))
        if embedder_cls is not None:
            for registry in (embedding_indexer.EMBEDDER_REGISTRY, embedding_encoder.EMBEDDER_REGISTRY):
                stack.enter_context(mock.patch.dict(registry, {"openai": embedder_cls}))
        yield budget


def _tagged(fn, role):
    def tagged(*args, **kwargs):
        token = current_role.set(role)
        try:
            return fn(*args, **kwargs)
        finally:
            current_role.reset(token)

    return tagged


@contextmanager
def role(name: str):
    token = current_role.set(name)
    try:
        yield
    finally:
        current_role.reset(token)
