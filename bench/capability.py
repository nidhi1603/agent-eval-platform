"""Capability search: harness v3's one change to v1.

**Why** (research/public_trajectories/FINDINGS.md: public trajectories of GPT-5.5 and Qwen 3.8 Max, dev tasks only).
The top standard agents reach about 0.84 of the documents a task requires; gpt-5-mini reaches about 0.4. They reach
them by searching for the *capability* they need ("tool to look up accounts by user id"): 35% of their queries use
such wording, against 3% of gpt-5-mini's. And once verified, they read the customer's records with lookup tools
instead of asking the customer for identifiers. With BM25, a capability query finds the account-lookup document at
rank 1-2; a query about the customer's situation does not find it.

**What the harness does.** Two triggers, each at most once per conversation per kind:
  after_verification   A successful log_verification has just arrived, and no tool result has yet shown an
                       account id. The harness searches for the tool that retrieves the customer's accounts.
  before_asking        The agent is about to ASK THE CUSTOMER for an account, card or transaction identifier that
                       no tool result has shown. The harness holds that message (it is not sent) and searches for
                       the tool that provides the identifier.
The search runs through the benchmark's own retrieval tools: KB_search, or under alltools both KB_search_bm25 and
KB_search_dense. It runs as a harness turn: no model call, and visible in the recorded trajectory. Its call and
results enter the model's history, with one line saying why the harness searched. The adapter then offers any tool
the results name, as for any search. The harness never calls a lookup tool itself and never writes anything.

**Queries.** One fixed template per kind, written before any test of v3, nothing per task or document. They are in
capability wording because that is what finds tool documents (FINDINGS.md section 3).

Also in v3: the v1 advisory before a transfer or a denial gains one line advising a capability-worded search.
"""

import re
from dataclasses import dataclass

K = 5  # documents per capability search (alltools' search tools take k; KB_search does not)
KNOWN_ID = re.compile(r"\b([a-z_]+_id):")
VERIFIED = "Verification logged successfully"
SEARCH_TOOLS = ("KB_search_bm25", "KB_search_dense", "KB_search")

QUERIES = {
    "accounts": "tool to retrieve all of the customer's accounts by user id",
    "cards": "tool to retrieve the customer's debit cards or credit cards for an account",
    "transactions": "tool to retrieve the transaction history of a customer's account",
}
# the identifier an agent is about to ask the customer for -> the kind of lookup that provides it
ASK = (
    ("transactions", "transaction_id", re.compile(r"\btransaction (?:id|number|reference)\b", re.I)),
    ("cards", "card_id", re.compile(r"\bcard (?:number|id)\b|\blast[\s-]*(?:4|four)\b|\bwhich card\b", re.I)),
    ("accounts", "account_id", re.compile(r"\baccount (?:number|id)\b|\bwhich account\b|\bchecking account id\b", re.I)),
)
NOTES = {
    "after_verification": ("Harness note (not shown to the customer): the customer is verified. The search above was run "
                           "by the harness for the tool that retrieves their accounts. If it names one, use it to look up "
                           "their records before asking them for account details."),
    "before_asking": ("Harness note (not shown to the customer): your message asking the customer for {what} was not sent. "
                      "The search above was run by the harness for a tool that provides it. If a lookup tool is available, "
                      "use it. Ask the customer only for what no tool can give you."),
}
ADVICE = ("- Search for the tool that does what the customer asked, in those words: for example \"tool to <action> "
          "<product>\". Agent procedures in the knowledge base are written around tools.")


@dataclass(frozen=True)
class Search:
    trigger: str      # "after_verification" | "before_asking"
    kind: str         # key of QUERIES
    query: str
    note: str


NOT_RECORDS = SEARCH_TOOLS + ("shell", "grep", "unlock_discoverable_agent_tool", "give_discoverable_user_tool")


def known_ids(messages: list[dict]) -> set[str]:
    """Identifier fields that a RECORD lookup has shown the agent (e.g. account_id, card_id). Documents and unlock
    receipts describe tool parameters ("card_id: string"), so they do not count: only results of other tools do."""
    calls = {c["id"]: c["name"] for m in messages if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])}
    return {k for m in messages if m.get("role") == "tool" and not m.get("error")
            and calls.get(m.get("tool_call_id")) not in NOT_RECORDS
            for k in KNOWN_ID.findall(m.get("content") or "")}


def just_verified(messages: list[dict]) -> bool:
    """A successful log_verification result is in the conversation."""
    calls = {c["id"]: c["name"] for m in messages if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])}
    return any(m.get("role") == "tool" and calls.get(m.get("tool_call_id")) == "log_verification"
               and not m.get("error") and VERIFIED in (m.get("content") or "") for m in messages)


def after_verification(messages: list[dict], done: set[str]) -> Search | None:
    if "accounts" in done or not just_verified(messages) or "account_id" in known_ids(messages):
        return None
    return Search("after_verification", "accounts", QUERIES["accounts"], NOTES["after_verification"])


def before_asking(draft: dict, messages: list[dict], done: set[str]) -> Search | None:
    """`draft` is the agent's proposed message. Only a text reply with no tool call can be a question to the customer."""
    text = draft.get("content") or ""
    if draft.get("tool_calls") or not text:
        return None
    known = known_ids(messages)
    for kind, identifier, pattern in ASK:
        m = pattern.search(text)
        if m and kind not in done and identifier not in known:
            return Search("before_asking", kind, QUERIES[kind], NOTES["before_asking"].format(what=f'"{m.group(0)}"'))
    return None


def search_calls(search: Search, available: set[str], n: int) -> list[dict]:
    """Tool calls for one capability search: both alltools search tools when present, else KB_search."""
    tools = [t for t in ("KB_search_bm25", "KB_search_dense") if t in available] or \
            [t for t in ("KB_search",) if t in available]
    return [{"id": f"capability_{n}_{i}", "name": t,
             "arguments": {"query": search.query, **({"k": K} if t != "KB_search" else {})}}
            for i, t in enumerate(tools)]
