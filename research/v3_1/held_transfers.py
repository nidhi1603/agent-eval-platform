"""What did gpt-5-mini do after the v1 give-up check held a transfer? ($0, saved H002-H004 conversations.)

For every finished harness conversation in which search_before_giving_up held a transfer_to_human_agents call:
whether a transfer was executed later, and (where the model's own history was saved: H004) what the agent's next
action was and whether it told the customer a transfer was under way.

    uv run --extra bench python research/v3_1/held_transfers.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSFER = "transfer_to_human_agents"
CLAIM = re.compile(r"transferr?(ed|ing)|connect(ing|ed)? you|handoff|hand(ing|ed)? (you|this) (off|over)|escalat(ed|ing)|"
                   r"transfer request submitted|\"transfer\": \"completed\"|I.ll transfer you", re.I)


def main():
    rows = []
    for batch in ("H002", "H003", "H004"):
        for r in json.loads((ROOT / "experiments" / f"{batch}_results.json").read_text())["results"]:
            if r["status"] != "finished" or not Path(r.get("trace") or "").exists():
                continue
            t = json.loads(Path(r["trace"]).read_text())
            h = t.get("harness") or {}
            if not any(e.get("event") == "held" and e.get("gate") == "search_before_giving_up"
                       and any(c["name"] == TRANSFER for c in e.get("tool_calls") or []) for e in h.get("events") or []):
                continue
            view = h.get("model_view")
            row = {"batch": batch, "arm": r["arm"], "task": r["task_id"], "model_view_saved": bool(view),
                   "transfer_executed_later": any(c["name"] == TRANSFER for c in t.get("tool_calls") or [])}
            if view:
                i = next(i for i, m in enumerate(view) if m.get("role") == "assistant"
                         and any(c["name"] == TRANSFER for c in m.get("tool_calls") or []))
                after = [m for m in view[i + 2:] if m.get("role") == "assistant"]
                nxt = after[0] if after else {}
                row.update(next_action="tool call" if nxt.get("tool_calls") else "text to customer" if nxt.get("content") else "none",
                           next_text=(nxt.get("content") or "")[:400],
                           told_customer_a_transfer_is_under_way=bool(CLAIM.search(nxt.get("content") or "")),
                           tool_calls_after_the_hold=sum(len(m.get("tool_calls") or []) for m in after))
            rows.append(row)
    v = [x for x in rows if x["model_view_saved"]]
    out = {"conversations_with_a_held_transfer": len(rows),
           "transfer_executed_later": sum(x["transfer_executed_later"] for x in rows),
           "with_model_view_saved": len(v),
           "next_action_text_to_customer": sum(x["next_action"] == "text to customer" for x in v),
           "told_customer_a_transfer_is_under_way": sum(x["told_customer_a_transfer_is_under_way"] for x in v),
           "any_tool_call_after_the_hold": sum(x["tool_calls_after_the_hold"] > 0 for x in v)}
    (ROOT / "research" / "v3_1" / "held_transfers.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
