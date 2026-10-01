"""Deterministic check of the verifications canonicalize.py set to ok ($0; review of the H008 audit).

canonicalize.py set to ok the 30 matched `log_verification` calls the first pass had not listed (its instructions said
to list only unmatched ones). This checks each one directly: for at least 2 of date of birth, email, phone and
address, the logged value was stated by the customer AND appears in a tool result retrieved before the log.
Formatting is ignored (lower-cased, alphanumerics only).

    uv run --extra bench python research/h008/audit/verification_check.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIELDS = ("date_of_birth", "email", "phone_number", "address")


def norm(v):
    return re.sub(r"[^a-z0-9]", "", str(v).lower())


def main():
    writes = json.loads((HERE / "writes.json").read_text())
    first = json.loads((HERE / "first_canonical.json").read_text())
    auto = {(x["id"], w["i"]) for x in first for w in x["executed_writes"] if "treated as matched" in (w.get("reason") or "")}
    rows = []
    for cid, ws in writes.items():
        msgs = json.loads((HERE / "convs" / f"{cid}.json").read_text())["messages"]
        for w in ws:
            if w["tool"] != "log_verification" or not w["executed_ok"]:
                continue
            i = w["i"]
            args = next(c for c in msgs[i]["tool_calls"] if c["name"] == "log_verification")["arguments"]
            records = " ".join(norm(m.get("content", "")) for m in msgs[:i] if m["role"] == "tool")
            said = " ".join(norm(m.get("content", "")) for m in msgs[:i] if m["role"] == "user")
            confirmed = [f for f in FIELDS if args.get(f) and norm(args[f]) in records and norm(args[f]) in said]
            rows.append({"id": cid, "i": i, "confirmed_fields": confirmed, "set_ok_by_normalization": (cid, i) in auto})
    out = {"verifications": len(rows), "set_ok_by_normalization": sum(r["set_ok_by_normalization"] for r in rows),
           "of_those_with_2_or_more_confirmed_fields": sum(1 for r in rows if r["set_ok_by_normalization"]
                                                          and len(r["confirmed_fields"]) >= 2),
           "fewer_than_2_confirmed": [r for r in rows if len(r["confirmed_fields"]) < 2], "rows": rows}
    (HERE / "verification_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
