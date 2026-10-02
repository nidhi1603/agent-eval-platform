"""Group each failed conversation's first mistake into a recurring PATTERN ($0). Writes patterns.json.

A conversation belongs to a pattern only by its first-mistake class (both readers, or the TRANSFER/RETRIEVAL
convention split, which is the same act read as act vs root cause) and its task. The pattern definitions below were
written after reading the agreed descriptions; they are a summary of the labels, not new labels. Reported with
conversation counts AND distinct tasks, because each task appears several times (arms and attempts).

    uv run --extra bench python research/post_verification/patterns.py
"""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (pattern, accepted first-mistake families, tasks)
PATTERNS = [
    ("cash-back discrepancy: agent rewrote rewards itself or transferred, instead of handing over submit_cash_back_dispute",
     {"POLICY_STEP", "TRANSFER/RETRIEVAL", "RETRIEVAL", "TRANSFER"}, {"task_017", "task_019"}),
    ("credit-limit increase: submitted, then stopped ('decision by email') without the remaining checks and approval",
     {"POLICY_STEP", "TOOL_ACCESS"}, {"task_050"}),
    ("account closure: retention protocol skipped",
     {"POLICY_STEP", "RETRIEVAL", "TRANSFER/RETRIEVAL", "TRANSFER"}, {"task_047"}),
    ("expired referral program: gave the referral tool after the program's end date",
     {"TIMING", "RETRIEVAL"}, {"task_015"}),
    ("no documented procedure: invented one ('according to our docs') instead of saying so and transferring",
     {"OTHER", "OTHER|POLICY_STEP", "TRANSFER"}, {"task_012"}),
    ("transfer reason code / transfer instead of acting, on transfer or verification-failure tasks",
     {"TRANSFER", "TRANSFER/RETRIEVAL", "TRANSFER|VERIFICATION"}, {"task_004", "task_023", "task_058", "task_089"}),
    ("required emergency or customer-side tool not used (credit-bureau incident tool; last-4 lookup handover)",
     {"TOOL_ACCESS"}, {"task_035", "task_031"}),
    ("wrong computed amount (ATM temporary maximum; rebate spend windows; APY stacking)",
     {"CALC", "TIMING|CALC", "RETRIEVAL|CALC"}, {"task_089", "task_023", "task_095", "task_019"}),
    ("fraud alert cleared after the customer reported an unauthorized charge",
     {"FRAUD"}, {"task_087"}),
]


def main():
    P = HERE
    A, B = {}, {}
    for part in ("audited", "part1", "part2"):
        A.update({x["id"]: x for x in json.loads((P / f"labels_{part}_A.json").read_text())})
        B.update({x["id"]: x for x in json.loads((P / f"labels_{part}_B.json").read_text())})
    key = json.loads((P / "KEY_do_not_give_to_readers.json").read_text())
    fam = {}
    for c in A:
        a, b = A[c]["first_mistake"]["class"], B[c]["first_mistake"]["class"]
        fam[c] = a if a == b else ("TRANSFER/RETRIEVAL" if {a, b} == {"TRANSFER", "RETRIEVAL"} else f"{a}|{b}")
    out, used = [], set()
    for name, fams, tasks in PATTERNS:
        members = [c for c in A if c not in used and key[c]["task_id"] in tasks and fam[c] in fams]
        used |= set(members)
        out.append({"pattern": name, "conversations": len(members),
                    "tasks": sorted({key[c]["task_id"] for c in members}),
                    "batches": sorted({key[c]["batch"] for c in members}),
                    "members": [{"id": c, "task": key[c]["task_id"], "batch": key[c]["batch"], "family": fam[c]} for c in members]})
    rest = [c for c in A if c not in used]
    out.append({"pattern": "unassigned", "conversations": len(rest),
                "members": [{"id": c, "task": key[c]["task_id"], "batch": key[c]["batch"], "family": fam[c]} for c in rest]})
    (P / "patterns.json").write_text(json.dumps(out, indent=1))
    for p in out:
        print(p["conversations"], p.get("tasks"), p["pattern"][:90])
    print("unassigned:", [(m["task"], m["family"]) for m in out[-1]["members"]])


if __name__ == "__main__":
    main()
