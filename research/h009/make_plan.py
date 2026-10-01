"""Write experiments/H009_plan.json ($0). Arm order as H007/H008, with its own hash seed.

    uv run --extra bench python research/h009/make_plan.py
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARMS = ("full_exposure", "read_exposure")


def main():
    h8 = json.loads((ROOT / "experiments" / "H008_plan.json").read_text())
    tasks = h8["tasks"]
    groups = sorted(((t, a) for t in tasks for a in (0, 1)),
                    key=lambda g: hashlib.sha256(f"H009-order:{g[0]}:{g[1]}".encode()).hexdigest())
    runs, first = [], {}
    for k, (t, a) in enumerate(groups):
        if t in first:                       # a task's two attempts use opposite orders
            lead = ARMS[1] if first[t] == ARMS[0] else ARMS[0]
        else:
            lead = ARMS[k % 2]
            first[t] = lead
        runs += [{"task_id": t, "arm": arm, "attempt": a} for arm in (lead, ARMS[1] if lead == ARMS[0] else ARMS[0])]
    plan = json.loads((ROOT / "research" / "h009" / "plan_text.json").read_text())
    plan.update(tasks=tasks, runs=runs, settings=h8["settings"], strata=h8["strata"],
                infrastructure=h8["infrastructure"], budget_accounting_note=h8["budget_accounting_note"],
                dense_retrieval=h8["dense_retrieval"])
    lead_counts = {a: sum(runs[i]["arm"] == a for i in range(0, len(runs), 2)) for a in ARMS}
    plan["arm_order_rule"] = ("each (task, attempt) group runs both arms back to back; groups sorted by "
                              "sha256('H009-order:' + task + ':' + attempt); the first arm alternates along that order "
                              f"and a task's two attempts use opposite orders. Times first: {lead_counts}.")
    (ROOT / "experiments" / "H009_plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(len(runs), lead_counts)


if __name__ == "__main__":
    main()
