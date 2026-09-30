"""Blind reading of D004's replies ($0).

    uv run --extra bench python research/d004/blind.py export   # writes blind.json (shuffled, no arm) and key.json
    (label each item in blind.json: set "label" to one of bench.hold_probe.LABELS)
    uv run --extra bench python research/d004/blind.py tally    # joins labels to arms; reports agreement with the automatic label
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench import hold_probe  # noqa: E402

HERE = ROOT / "research" / "d004"


def export():
    rows = [r for r in json.loads((ROOT / "experiments" / "D004_results.json").read_text())["results"] if r["status"] == "done"]
    order = list(range(len(rows)))
    random.Random(4004).shuffle(order)
    blind = [{"item": n, "task": rows[i]["case"], "reply_text": rows[i]["reply_text"],
              "reply_tool_calls": [c["name"] for c in rows[i]["reply_tool_calls"]], "label": None}
             for n, i in enumerate(order)]
    (HERE / "blind.json").write_text(json.dumps(blind, indent=1))
    (HERE / "key.json").write_text(json.dumps({n: rows[i]["run"] for n, i in enumerate(order)}, indent=1))
    print(f"{len(blind)} items written; label them before opening key.json")


def tally():
    blind = json.loads((HERE / "blind.json").read_text())
    key = {int(k): v for k, v in json.loads((HERE / "key.json").read_text()).items()}
    runs = {r["run"]: r for r in json.loads((ROOT / "experiments" / "D004_results.json").read_text())["results"]}
    assert all(b["label"] in hold_probe.LABELS for b in blind), "every item needs a label"
    out = {arm: {lab: 0 for lab in hold_probe.LABELS} for arm in hold_probe.ARMS}
    disagree = []
    for b in blind:
        r = runs[key[b["item"]]]
        out[r["arm"]][b["label"]] += 1
        if b["label"] != r["label"]:
            disagree.append({"run": r["run"], "arm": r["arm"], "automatic": r["label"], "read": b["label"]})
    res = {"read_labels": out, "disagreements_with_automatic": disagree}
    (HERE / "tally.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"export": export, "tally": tally}[sys.argv[1]]()
