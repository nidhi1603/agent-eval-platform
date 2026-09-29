"""Task ledger for harness v2: the task state, kept by code (docs/PHASE2_RESEARCH.md §8-10).

The ledger is rebuilt from the agent's own conversation on every check, so it cannot drift from what actually
happened. It holds:
- who is verified, and the clock readings;
- every search, with the documents it returned;
- the tools discovered, used and handed to the customer;
- successful writes and their receipts;
- the agent's own plan: the customer's requests, and what it needs to find out for each.

The plan is the one part the model writes. It records it with the harness-local `task_plan` tool, which never
reaches the benchmark environment. Nothing in the ledger comes from task data or the database.
"""


import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from bench.guard import VERIFIED, Evidence, target

PLAN_TOOL = "task_plan"
DOC_ID = re.compile(r"ID:\s*(doc_\S+)")
KB = "KB_search"


class Need(BaseModel):
    need: str
    status: Literal["open", "found", "not_found"] = "open"
    source: str = ""


class Request(BaseModel):
    request: str
    needs: list[Need]


def task_plan(requests: list[Request]) -> str:
    """Record or update your plan for this conversation. Call it once you understand what the customer wants, and
    again whenever you learn something. Keeping it current lets the harness remind you of anything still open.

    List every separate thing the customer wants. For each, list what you must find out before you can act or
    answer, e.g. the procedure, eligibility rules, rates or fees, and the tool to use. Mark a need "found" with
    the document ID (doc_...) that answered it, "not_found" after searching for it with different wording, or
    "open" until then. This tool only records your plan: it does not search, act or reply to the customer.

    Args:
        requests: Every separate thing the customer wants, each with what you need to find out for it.
    """
    return ""


@dataclass
class Ledger:
    verified_user: str | None = None
    clock: list[str] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)       # {"query", "docs": [doc ids]}
    docs_seen: set[str] = field(default_factory=set)
    tools_used: set[str] = field(default_factory=set)         # discoverable tools called or handed over
    tools_given: set[str] = field(default_factory=set)        # customer tools handed over
    writes: list[dict] = field(default_factory=list)          # successful writes: {"tool", "args", "receipt"}
    plan: list[Request] | None = None
    transfer_mentioned_then_customer_replied: bool = False

    def open_needs(self) -> list[tuple[str, str]]:
        return [(r.request, n.need) for r in self.plan or [] for n in r.needs if n.status == "open"]

    def unsupported_found(self) -> list[tuple[str, str]]:
        """Needs marked found whose cited document was not in any search result the agent received."""
        return [(n.need, n.source) for r in self.plan or [] for n in r.needs
                if n.status == "found" and n.source not in self.docs_seen]


def parse_plan(arguments) -> tuple[list[Request] | None, str | None]:
    """(plan, None) or (None, error message)."""
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as e:
            return None, f"arguments are not valid JSON ({e})"
    try:
        return [Request.model_validate(r) for r in (args or {}).get("requests") or []], None
    except ValidationError as e:
        return None, f"invalid plan: {e.errors()[0].get('msg')} at {e.errors()[0].get('loc')}"


def build(messages: list[dict], tool_type) -> Ledger:
    """The ledger for a conversation (model-view dicts, as bench.guard.messages_as_dicts produces)."""
    from bench.continuation import receipt_ok

    led = Ledger()
    ev = Evidence(messages=messages, tool_type=tool_type)
    for c, r in ev.results():
        content = r.get("content") or ""
        ok = not r.get("error") and receipt_ok(c["name"], content)
        name, args = target(c)
        if c["name"] == PLAN_TOOL:
            if ok and content.startswith("Plan recorded"):
                led.plan, _ = parse_plan(c.get("arguments"))
            continue
        if not ok:
            continue
        if c["name"] == KB:
            docs = DOC_ID.findall(content)
            led.searches.append({"query": str((c.get("arguments") or {}).get("query", "")), "docs": docs})
            led.docs_seen |= set(docs)
        elif c["name"] == "get_current_time":
            led.clock.append(content)
        elif c["name"] == "log_verification" and VERIFIED in content:
            led.verified_user = (c.get("arguments") or {}).get("user_id") or led.verified_user
        elif c["name"] == "give_discoverable_user_tool":
            given = (c.get("arguments") or {}).get("discoverable_tool_name")
            led.tools_given.add(given)
            led.tools_used.add(given)
        elif c["name"] != "unlock_discoverable_agent_tool":
            led.tools_used.add(name)
            if tool_type(name) == "write":
                led.writes.append({"tool": name, "args": args, "receipt": content[:200]})
    asked_at = None
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("content") and TRANSFER_TALK.search(m["content"]):
            asked_at = i
        elif m.get("role") == "user" and asked_at is not None:
            led.transfer_mentioned_then_customer_replied = True
    return led


TRANSFER_TALK = re.compile(r"\b(transfer|human agent|specialist|representative)\b", re.I)
