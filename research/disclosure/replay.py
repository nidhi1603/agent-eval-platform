"""Offline replay of the identity-disclosure check over every saved agent message ($0; after the D005 review).

For every customer-facing agent text in every live trace (runs/local/*_live_*/trace.json), the check runs on the
conversation BEFORE that message (bench.identity_disclosure.prohibited), exactly as the harness would before delivery.
Also listed: ALLOWED messages that contain a stored identity value (read-backs of independently supplied values, or a
verified customer's own data) so that a reviewer can check them for missed leaks.

The 10 D005 source histories were used to develop the check (development data); their messages are reported
separately and excluded from the validation sample (review/).

This measures which messages WOULD be held or replaced. It cannot show what the conversation would do next.

    uv run --extra bench python research/disclosure/replay.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent


def main():
    from bench import identity_disclosure as idd, verify_evidence as ve

    dev = {c["source_trace"] for c in json.loads((ROOT / "experiments" / "D005_plan.json").read_text())["cases"]}
    rows = []
    for tp in sorted((ROOT / "runs" / "local").glob("*_live_*/trace.json")):
        try:
            msgs = json.loads(tp.read_text())["messages"]
        except (ValueError, KeyError):
            continue
        rel = str(tp.relative_to(ROOT))
        for i, m in enumerate(msgs):
            if m["role"] != "assistant" or i == 0 or not m.get("content"):
                continue
            prefix = msgs[:i]
            found = idd.prohibited(m["content"], prefix)
            # any stored identity value of any retrieved record in the text (to sample allowed messages)
            values = [(uid, f) for uid, rec in ve.records(prefix).items() for f in ve.FIELDS
                      if (w := ve.record_value(f, rec.get(f, ""))) and any(ve.matches(f, v, w) for v in ve.stated(f, m["content"]))]
            if found or values:
                rows.append({"trace": rel, "i": i, "development": rel in dev, "flagged": bool(found),
                             "fields": sorted({x["field"] for x in found}), "origins": sorted({x["origin"] for x in found}),
                             "verification_related": idd.verification_related(m["content"]),
                             "identity_values_in_text": sorted({f for _, f in values})})
    texts = sum(1 for tp in (ROOT / "runs" / "local").glob("*_live_*/trace.json")
                for m in json.loads(tp.read_text())["messages"][1:] if m["role"] == "assistant" and m.get("content"))
    flagged = [r for r in rows if r["flagged"]]
    out = {"agent_texts": texts, "messages_with_a_stored_identity_value": len(rows),
           "flagged": len(flagged), "flagged_development": sum(r["development"] for r in flagged),
           "flagged_by_origin": {o: sum(o in r["origins"] for r in flagged) for o in ("new", "agent", "unchecked")},
           "flagged_verification_related": sum(r["verification_related"] for r in flagged),
           "allowed_with_identity_values": sum(not r["flagged"] for r in rows),
           "conversations_with_a_flag": len({r["trace"] for r in flagged}), "rows": rows}
    (OUT / "replay.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
