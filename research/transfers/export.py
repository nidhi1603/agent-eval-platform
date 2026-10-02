"""Transfer decision table, offline ($0; after the failure-tally review). Export step.

Decision points, from EVERY conversation in H008, H009 and P001 (successful ones included):
- T: every transfer_to_human_agents call (any outcome);
- ASK: a customer message asking for a human/escalation with no transfer anywhere after it;
- EXPECTED: a conversation on a task whose reference actions contain a transfer, with no transfer call at all
  (decision point: the conversation's last agent text).
Readers get the conversation up to the decision point plus the next 3 messages, blind
to arm, batch, task outcome and the task file: their judgment is policy-based, from what the agent could see.
Record, transaction and action results are complete; retrieval outputs (KB search, shell) are clipped to 1,500
characters plus every document id they named, and readers open the full documents on disk. The
answer-key comparison (expected reason code; official reward) is computed separately and kept in KEY.json.

    uv run --extra bench python research/transfers/export.py
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TASKS = Path(os.environ.get("TAU2_DATA_DIR", Path.home() / "Desktop/tau2-bench/data")) / "tau2/domains/banking_knowledge/tasks"
TIER_DOC = "doc_bank_accounts_bank_accounts_(general)_042"
HUMAN = re.compile(r"\b(human|real person|representative|specialist|supervisor|manager|transfer me|escalat)", re.I)
AFTER = 3


def _code(s):
    return "d" + hashlib.sha256(f"transfers:{s}".encode()).hexdigest()[:6]


CLIPPED = {"KB_search", "KB_search_bm25", "KB_search_dense", "shell", "list_discoverable_agent_tools",
           "unlock_discoverable_agent_tool"}
CLIP = 1500
DOC_ID = re.compile(r"doc_[A-Za-z0-9_()\-]+")


def _render(msgs, upto):
    names = {c["id"]: c["name"] for m in msgs for c in m.get("tool_calls") or []}
    ids, out = {}, []
    for i, m in enumerate(msgs[:upto]):
        d = {"i": i, "role": m["role"]}
        if m.get("content"):
            d["content"] = m["content"]
            name = names.get(m.get("tool_call_id")) if m["role"] == "tool" else None
            if name in CLIPPED and len(m["content"]) > CLIP:   # retrieval output: excerpt + every document id it names
                docs = sorted(set(DOC_ID.findall(m["content"])))
                d["content"] = m["content"][:CLIP] + f" …[clipped; full documents on disk; ids in this output: {docs}]"
        if m.get("tool_calls"):
            d["tool_calls"] = []
            for c in m["tool_calls"]:
                ids[c["id"]] = f"call_{len(ids) + 1}"
                d["tool_calls"].append({"id": ids[c["id"]], "name": c["name"], "arguments": c["arguments"]})
        if m["role"] == "tool":
            d["tool_call_id"] = ids.get(m.get("tool_call_id"), "?")
            d["error"] = bool(m.get("error"))
        d["customer_saw_it"] = m["role"] == "assistant" and bool(m.get("content")) and not m.get("tool_calls")
        out.append(d)
    return out


def _tier_doc_seen(msgs, i):
    """Upper bound: the document id or a code appears in any earlier tool result (directory listings included)."""
    return any(m["role"] == "tool" and (TIER_DOC in (m.get("content") or "") or "account_ownership_dispute" in (m.get("content") or ""))
               for m in msgs[:i])


TIER_CONTENT = ("highest tier that applies", "TIER 1 (HIGHEST PRIORITY)", "Human Agent Transfer Reason Codes")


def _tier_content_seen(msgs, i):
    """Stricter: the tier document's TITLE or TEXT appears in an earlier tool result (a search hit or a file read)."""
    return any(m["role"] == "tool" and any(t in (m.get("content") or "") for t in TIER_CONTENT) for m in msgs[:i])


def main():
    (OUT / "points").mkdir(exist_ok=True)
    key, n = {}, 0
    for b in ("H008", "H009", "P001"):
        for r in json.loads((ROOT / "experiments" / f"{b}_results.json").read_text())["results"]:
            if not r.get("trace"):
                continue
            msgs = json.loads(Path(r["trace"]).read_text())["messages"]
            task = json.loads((TASKS / f"{r['task_id']}.json").read_text())
            # a reference transfer whose compare_args excludes "reason" (task_035: []) accepts any code
            expected = [(a.get("arguments") or {}).get("reason") for a in task["evaluation_criteria"].get("actions") or []
                        if a["name"] == "transfer_to_human_agents" and (a.get("compare_args") is None or "reason" in a["compare_args"])]
            points = []
            results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
            tcalls = [(i, c) for i, m in enumerate(msgs) if m["role"] == "assistant"
                      for c in m.get("tool_calls") or [] if c["name"] == "transfer_to_human_agents"]
            for i, c in tcalls:
                res = results.get(c["id"]) or {}
                points.append({"kind": "T", "i": i, "reason_code": (c["arguments"] or {}).get("reason"),
                               "call_ok": bool(res) and not res.get("error") and not (res.get("content") or "").startswith("Error")})
            last_t = max((i for i, _ in tcalls), default=-1)
            asks = [i for i, m in enumerate(msgs) if m["role"] == "user" and m.get("content") and HUMAN.search(m["content"]) and i > last_t]
            if asks:
                points.append({"kind": "ASK", "i": asks[0] + 1})
            transfer_expected = any(a["name"] == "transfer_to_human_agents" for a in task["evaluation_criteria"].get("actions") or [])
            if transfer_expected and not tcalls:
                last = max((i for i, m in enumerate(msgs) if m["role"] == "assistant" and m.get("content")), default=len(msgs) - 1)
                points.append({"kind": "EXPECTED", "i": last})
            for p in points:
                n += 1
                c = _code(f"{b}:{r['run_id']}:{p['kind']}:{p['i']}")
                upto = min(len(msgs), p["i"] + 1 + AFTER)
                (OUT / "points" / f"{c}.json").write_text(json.dumps(
                    {"id": c, "decision_kind": p["kind"], "decision_index": p["i"], "messages": _render(msgs, upto)}, indent=1))
                key[c] = {"batch": b, "task_id": r["task_id"], "arm": r["arm"], "attempt": r.get("attempt", 0),
                          "run_id": r["run_id"], "official_reward": r.get("official_reward"), **p,
                          "expected_codes": expected, "code_matches_answer_key": (p.get("reason_code") in expected) if expected and p["kind"] == "T" else None,
                          "tier_doc_seen_before": _tier_doc_seen(msgs, p["i"]),
                          "tier_doc_content_seen_before": _tier_content_seen(msgs, p["i"])}
    (OUT / "KEY_do_not_give_to_readers.json").write_text(json.dumps(key, indent=1))
    ids = sorted(key)
    (OUT / "parts.json").write_text(json.dumps({"part1": ids[: len(ids) // 2], "part2": ids[len(ids) // 2:]}, indent=1))
    from collections import Counter
    print(json.dumps({"points": len(key), "by_kind": Counter(v["kind"] for v in key.values()),
                      "in_successful_convs": sum(v["official_reward"] == 1.0 for v in key.values()),
                      "tier_doc_seen_before_T": sum(v["tier_doc_seen_before"] for v in key.values() if v["kind"] == "T")}, default=str))


if __name__ == "__main__":
    main()
