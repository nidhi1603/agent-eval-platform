"""Compare the blind reviewer (labels.json) with the disclosure check: as built (key.json, written by make.py before
the review) and with the current code (after the day-first date fix). Writes tally.json.

    uv run --extra bench python research/disclosure/readback/tally.py
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

COVERED = {"date_of_birth", "email", "phone_number", "address_street"}


def main():
    import bench  # noqa: F401
    import make
    from bench import harness
    from bench.guard import Evidence

    key = json.loads((HERE / "key.json").read_text())
    labels = {x["item"]: x for x in json.loads((HERE / "labels.json").read_text())}
    cases = make._real() + make._synthetic()
    random.Random(20261001).shuffle(cases)
    rows = []
    for n, c in enumerate(cases, 1):
        k, lab = key[str(n)], labels[n]
        assert k["source"] == c["source"], "case order changed since make.py"
        now = bool(harness.gate_identity_disclosure({"content": c["text"]}, Evidence(messages=c["messages"], tool_type=lambda x: None),
                                                    {"events": []}))
        covered = sorted(set(lab["leaked"]) & COVERED)
        rows.append({"item": n, "source": k["source"], "reviewer_leak": lab["leak"], "reviewer_leaked": lab["leaked"],
                     "reviewer_covered_leak": bool(covered), "check_as_built": k["check_blocks"], "check_now": now})

    def score(col, subset):
        rs = [r for r in rows if subset(r)]
        return {"n": len(rs),
                "agree_on_covered_fields": sum(r[col] == r["reviewer_covered_leak"] for r in rs),
                "false_blocks": [r["item"] for r in rs if r[col] and not r["reviewer_leak"]],
                "missed_covered": [r["item"] for r in rs if not r[col] and r["reviewer_covered_leak"]],
                "out_of_coverage_only": [r["item"] for r in rs if r["reviewer_leak"] and not r["reviewer_covered_leak"]]}

    out = {"items": len(rows),
           "as_built": {"all": score("check_as_built", lambda r: True),
                        "real": score("check_as_built", lambda r: r["source"].startswith("real")),
                        "synthetic": score("check_as_built", lambda r: r["source"].startswith("synthetic"))},
           "now": {"all": score("check_now", lambda r: True),
                   "real": score("check_now", lambda r: r["source"].startswith("real")),
                   "synthetic": score("check_now", lambda r: r["source"].startswith("synthetic"))},
           "rows": rows}
    (HERE / "tally.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    for r in rows:
        print(r["item"], r["source"][:60], "rev", r["reviewer_leak"], r["reviewer_leaked"], "built", r["check_as_built"], "now", r["check_now"])


if __name__ == "__main__":
    main()
