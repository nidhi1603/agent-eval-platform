"""Estimated spend admission control for every paid call a run makes (agent, user simulator, LLM
grader, embeddings).

What it does:
- Before each request, reserve a conservative upper bound on that request's cost and refuse the
  request if usage-based spend + unresolved reservations + this bound would exceed the cap.
  Input bound: UTF-8 bytes of the serialized request plus fixed overhead. OpenAI's tokenizers are
  byte-level BPE, so each token covers at least one byte; the bound relies on that and is checked.
  Output bound: max_tokens, forced on every chat request.
- Retries: litellm's and the OpenAI SDK's hidden retries are disabled; retries happen here, and
  every physical request is reserved separately.
- Every reservation and settlement is appended to an fsync'd journal before/after the request, so
  a killed process still leaves the ledger on disk.
- A successful call settles at provider-reported usage x the recorded price table. A call whose
  usage is missing, malformed or unprocessable, or which failed, keeps its reservation as unresolved.
- After every call, usage is checked against the bounds the reservation assumed. A violation is
  recorded and stops the run (BoundViolation): the assumption behind admission control failed.

What it is not: a guarantee. It depends on the price table being right, on the provider honouring
max_tokens, and on the tokenizer assumption. Provider-reconciled charges are not available to the
code; compare the ledger with the provider's usage dashboard.
"""

import json
import math
import os
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

# Model arguments a run may set. Anything else (n, stream, logprobs, ...) could break the bounds.
ALLOWED_LLM_ARGS = frozenset({"temperature", "top_p", "seed", "reasoning_effort"})
# Arguments the harness itself adds to each request.
HARNESS_ARGS = frozenset({"num_retries", "max_retries", "max_tokens", "timeout"})


class BudgetExceeded(Exception):
    """The next request could push spend past the approved cap, so it was not sent."""


class PriceMissing(Exception):
    """No recorded price for this model: the run cannot bound its spend, so it must not start."""


class InvalidValue(ValueError):
    """A cap, price, estimate or limit is not a finite number in its allowed range."""


class RequestNotAllowed(Exception):
    """A request carries arguments outside the validated set."""


class BoundViolation(Exception):
    """Reported usage exceeded what the reservation assumed. Recorded, and the run is stopped."""


def finite(value, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidValue(f"{name} must be a finite number, got {value!r}")
    if value < 0 or (positive and value == 0):
        raise InvalidValue(f"{name} must be {'> 0' if positive else '>= 0'}, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    source: str

    def __post_init__(self):
        finite(self.input_per_mtok, "input price")
        finite(self.output_per_mtok, "output price")

    def cost(self, input_tokens: float, output_tokens: float) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1e6


def load_prices(path: Path = PRICES_FILE) -> dict[str, Price]:
    """Prices as recorded by a person, with source URL and date. The code checks their form, not their truth."""
    entries = json.loads(path.read_text())["models"]
    return {m: Price(e["input_per_mtok"], e["output_per_mtok"], f"{e['source']} (recorded {e['checked_on']})")
            for m, e in entries.items()}


@dataclass(frozen=True)
class Limits:
    max_output_tokens: int = 4096
    max_attempts: int = 3  # physical requests per logical call, including the first
    request_timeout_s: float = 120.0

    def __post_init__(self):
        if not isinstance(self.max_output_tokens, int) or not 1 <= self.max_output_tokens <= 128_000:
            raise InvalidValue(f"max_output_tokens must be an int in [1, 128000], got {self.max_output_tokens!r}")
        if not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 5:
            raise InvalidValue(f"max_attempts must be an int in [1, 5], got {self.max_attempts!r}")
        finite(self.request_timeout_s, "request_timeout_s", positive=True)


def input_token_bound(messages, tools=None) -> int:
    """Upper bound on prompt tokens for byte-level BPE tokenizers: bytes of the serialized request,
    plus per-message and fixed overhead for chat formatting. Roughly 3-4x the real count."""
    payload = json.dumps(messages, ensure_ascii=False, default=str) + json.dumps(tools or [], ensure_ascii=False)
    return len(payload.encode("utf-8")) + 16 * len(messages) + 1024


@dataclass
class Call:
    seq: int
    kind: str  # "chat" | "embedding"
    role: str
    model: str
    attempt: int
    reserved_usd: float
    input_token_bound: int
    output_token_bound: int
    request_params: dict
    status: str = "in_flight"  # -> ok | failed | usage_unresolved | bound_violation
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None  # usage x price when known; else None
    provider_model: str | None = None
    error: str | None = None
    duration_s: float | None = None


class Budget:
    def __init__(self, cap_usd: float, prices: dict[str, Price], journal: Path | None = None):
        self.cap_usd = finite(cap_usd, "cap_usd", positive=True)
        self._prices = prices
        self._lock = threading.Lock()
        self._journal = journal
        self.calls: list[Call] = []

    def price(self, model: str) -> Price:
        if model not in self._prices:
            raise PriceMissing(f"no recorded price for {model!r} in bench/prices.json")
        return self._prices[model]

    def _exposure(self) -> float:
        # Resolved calls count at usage cost; everything else at its reservation.
        return sum(c.cost_usd if c.status == "ok" else c.reserved_usd for c in self.calls)

    def _log(self, event: str, call: Call) -> None:
        if self._journal is None:
            return
        with open(self._journal, "a") as f:
            f.write(json.dumps({"event": event, "t": time.time(), **asdict(call)}, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def reserve(self, kind: str, model: str, attempt: int, in_bound: int, out_bound: int,
                request_params: dict | None = None) -> Call:
        price = self.price(model)
        estimate = finite(price.cost(in_bound, out_bound), "reservation")
        with self._lock:
            exposure = self._exposure()
            if exposure + estimate > self.cap_usd:
                raise BudgetExceeded(
                    f"{kind} call to {model} needs up to ${estimate:.4f}; ${exposure:.4f} of the "
                    f"${self.cap_usd:.2f} cap is already spent or reserved"
                )
            call = Call(len(self.calls) + 1, kind, current_role.get(), model, attempt, estimate,
                        in_bound, out_bound, dict(request_params or {}))
            self.calls.append(call)
            self._log("reserve", call)  # persisted before the request is sent
            return call

    def settle_ok(self, call: Call, usage, provider_model: str | None, started: float) -> None:
        """Settle from a response's usage. Missing or malformed usage leaves the reservation unresolved."""
        try:
            inp = int(usage.prompt_tokens if hasattr(usage, "prompt_tokens") else usage["prompt_tokens"])
            out_raw = usage.completion_tokens if hasattr(usage, "completion_tokens") else usage.get("completion_tokens", 0)
            out = int(out_raw or 0)
            if inp < 0 or out < 0:
                raise ValueError("negative token count")
        except Exception as e:  # noqa: BLE001 - any failure here must keep the reservation
            self.settle_unresolved(call, e, started, status="usage_unresolved")
            return
        with self._lock:
            call.input_tokens, call.output_tokens, call.provider_model = inp, out, provider_model
            call.cost_usd = self.price(call.model).cost(inp, out)
            call.duration_s = round(time.perf_counter() - started, 3)
            violated = inp > call.input_token_bound or out > call.output_token_bound
            call.status = "bound_violation" if violated else "ok"
            if violated:
                call.reserved_usd = max(call.reserved_usd, call.cost_usd)  # exposure uses the larger figure
            self._log("settle", call)
        if violated:
            raise BoundViolation(f"call {call.seq}: usage in={inp}/out={out} exceeded bounds "
                                 f"in<={call.input_token_bound}/out<={call.output_token_bound}")

    def settle_unresolved(self, call: Call, error: BaseException, started: float, status: str = "failed") -> None:
        with self._lock:
            call.status, call.error = status, f"{type(error).__name__}: {error}"[:500]
            call.duration_s = round(time.perf_counter() - started, 3)
            self._log("settle", call)

    def summary(self) -> dict:
        with self._lock:
            ok = [c for c in self.calls if c.status == "ok"]
            unresolved = [c for c in self.calls if c.status != "ok"]
            usage_based = sum(c.cost_usd for c in ok)
            held = sum(c.reserved_usd for c in unresolved)
            by_role: dict[str, float] = {}
            for c in self.calls:
                by_role[c.role] = round(by_role.get(c.role, 0.0) + (c.cost_usd if c.status == "ok" else c.reserved_usd), 6)
            return {
                "cap_usd": self.cap_usd,
                "usage_based_estimate_usd": round(usage_based, 6),
                "unresolved_reservations_usd": round(held, 6),
                "upper_bound_usd": round(usage_based + held, 6),
                "provider_reconciled_usd": None,  # not available to the code; compare with the provider dashboard
                "by_role_upper_bound_usd": by_role,
                "calls": len(self.calls),
                "unresolved_calls": len(unresolved),
                "statuses": {s: sum(c.status == s for c in self.calls) for s in {c.status for c in self.calls}},
            }

    def ledger(self) -> list[dict]:
        with self._lock:
            return [asdict(c) for c in self.calls]


def check_llm_args(args: dict, who: str) -> dict:
    extra = set(args) - ALLOWED_LLM_ARGS
    if extra:
        raise RequestNotAllowed(f"{who} llm_args {sorted(extra)} not allowed; allowed: {sorted(ALLOWED_LLM_ARGS)}")
    return args


def metered_completion(budget: Budget, limits: Limits, send):
    """Wrap a litellm-style completion function with validation, reservation, retries and settlement."""

    def completion(model, messages, tools=None, tool_choice=None, **kwargs):
        extra = set(kwargs) - ALLOWED_LLM_ARGS - HARNESS_ARGS
        if extra:
            raise RequestNotAllowed(f"request carries {sorted(extra)}")
        kwargs["num_retries"] = 0  # litellm maps this to the SDK's max_retries
        kwargs["max_retries"] = 0
        kwargs["max_tokens"] = limits.max_output_tokens
        kwargs["timeout"] = limits.request_timeout_s
        params = {k: v for k, v in kwargs.items() if k in ALLOWED_LLM_ARGS | {"max_tokens", "timeout"}}
        params["tools"] = len(tools or [])
        in_bound = input_token_bound(messages, tools)
        for attempt in range(1, limits.max_attempts + 1):
            call = budget.reserve("chat", model, attempt, in_bound, limits.max_output_tokens, params)
            started = time.perf_counter()
            try:
                response = send(model=model, messages=messages, tools=tools, tool_choice=tool_choice, **kwargs)
            except TRANSIENT_ERRORS as e:
                budget.settle_unresolved(call, e, started)
                if attempt == limits.max_attempts:
                    raise _with_role(e)
                time.sleep(min(2 ** attempt, 10))
                continue
            except BaseException as e:
                budget.settle_unresolved(call, e, started)
                raise _with_role(e)
            budget.settle_ok(call, getattr(response, "usage", None), getattr(response, "model", None), started)
            return response
        raise AssertionError("unreachable")

    return completion


def _with_role(error: BaseException) -> BaseException:
    """Remember which participant's call failed, for failure attribution."""
    try:
        if not hasattr(error, "aep_role"):
            error.aep_role = current_role.get()
    except Exception:  # noqa: BLE001 - some exception types reject attributes
        pass
    return error


def metered_embedder(budget: Budget, limits: Limits, base_cls):
    """Subclass of tau2's OpenAIEmbedder: SDK retries off, each physical request reserved and settled."""
    import numpy as np

    class MeteredEmbedder(base_cls):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.client = self.client.with_options(max_retries=0, timeout=limits.request_timeout_s)

        def embed(self, texts):
            if not texts:
                raise ValueError("No text to embed.")
            in_bound = sum(len(t.encode("utf-8")) for t in texts) + 8 * len(texts)
            for attempt in range(1, limits.max_attempts + 1):
                call = budget.reserve("embedding", self.model, attempt, in_bound, 0, {"texts": len(texts)})
                started = time.perf_counter()
                try:
                    response = self.client.embeddings.create(input=texts, model=self.model)
                except Exception as e:  # openai SDK errors: retry transient ones, here and reserved
                    budget.settle_unresolved(call, e, started)
                    transient = type(e).__name__ in {"RateLimitError", "APIConnectionError", "APITimeoutError",
                                                     "InternalServerError"}
                    if not transient or attempt == limits.max_attempts:
                        raise _with_role(e)
                    time.sleep(min(2 ** attempt, 10))
                    continue
                usage = getattr(response, "usage", None)
                budget.settle_ok(call, {"prompt_tokens": getattr(usage, "total_tokens", None), "completion_tokens": 0},
                                 self.model, started)
                return np.array([item.embedding for item in response.data])
            raise AssertionError("unreachable")

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
        for module_name, role_name in ROLE_CALLERS.items():
            module = importlib.import_module(module_name)
            stack.enter_context(mock.patch.object(module, "generate", _tagged(module.generate, role_name)))
        if embedder_cls is not None:
            for registry in (embedding_indexer.EMBEDDER_REGISTRY, embedding_encoder.EMBEDDER_REGISTRY):
                stack.enter_context(mock.patch.dict(registry, {"openai": embedder_cls}))
        yield budget


def _tagged(fn, role_name):
    def tagged(*args, **kwargs):
        token = current_role.set(role_name)
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
