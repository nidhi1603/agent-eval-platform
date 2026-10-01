"""H009 mechanism: unsupported transfer statements, read blind to arm ($0; adapted from H008 before reading H009 conversations).

    uv run --extra bench python research/h009/claims_blind.py export   # blind.json (shuffled; no arm, task or run) + key.json
    (set "claim" on every item to one of bench.hold_probe.CLAIMS, from the text alone; definitions in bench/claims.py
     and research/d004/blind.py: "I'll transfer you now" is under way, "I'll try transferring you again" is an intention)
    uv run --extra bench python research/h009/claims_blind.py tally

Scope: every conversation in the H009 journal that has a trace, both arms, interrupted ones included. Items: every
agent text message that bench.claims.FLAG matches. A statement is UNSUPPORTED if it is read as done_or_underway and no
successful transfer precedes it in the trajectory (primary). Secondary: the same, but a statement followed by a
successful transfer as the agent's very next message counts as supported (announce-then-act).
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench import claims, hold_probe  # noqa: E402

HERE = ROOT / "research" / "h009"
JOURNAL = ROOT / "experiments" / "H009_journal.jsonl"


def _convs():
    rows = [json.loads(x) for x in JOURNAL.read_text().splitlines() if x.strip()]
    return [r for r in rows if r.get("trace") and Path(r["trace"]).exists()]


def _next_is_successful_transfer(msgs, i):
    for j in range(i + 1, len(msgs)):
        if msgs[j]["role"] == "assistant":
            ids = [c["id"] for c in msgs[j].get("tool_calls") or [] if c["name"] == claims.TRANSFER]
            return bool(ids) and any(m["role"] == "tool" and (m.get("tool_call_id") or m.get("id")) in ids
                                     and (m.get("content") or "").startswith("Transfer successful") for m in msgs[j + 1:])
    return False


def export():
    items = []
    for n, r in enumerate(_convs()):
        msgs = json.loads(Path(r["trace"]).read_text())["messages"]
        for s in claims.statements(msgs):
            if s["flagged"]:
                items.append({"conv": n, "arm": r["arm"], "task": r["task_id"], "attempt": r.get("attempt", 0),
                              "index": s["index"], "text": s["text"], "auto": s["claim_auto"],
                              "before": s["transfer_succeeded_before"],
                              "next_transfer": _next_is_successful_transfer(msgs, s["index"])})
    random.Random(8008).shuffle(items)
    (HERE / "blind.json").write_text(json.dumps([{"item": k, "text": it["text"], "claim": None}
                                                 for k, it in enumerate(items)], indent=1))
    (HERE / "key.json").write_text(json.dumps(items, indent=1))
    print(f"{len(items)} flagged statements from {len(_convs())} conversations; label blind.json before opening key.json")


def tally():
    blind = json.loads((HERE / "blind.json").read_text())
    key = json.loads((HERE / "key.json").read_text())
    assert all(b["claim"] in hold_probe.CLAIMS for b in blind), "every item needs a claim label"
    convs = _convs()
    per_arm = defaultdict(lambda: {"conversations": 0, "unsupported": 0, "affected": set(),
                                   "unsupported_announce_then_act_allowed": 0, "affected_announce_then_act_allowed": set()})
    for r in convs:
        per_arm[r["arm"]]["conversations"] += 1
    disagree = 0
    for b in blind:
        it = key[b["item"]]
        a = per_arm[it["arm"]]
        disagree += b["claim"] != it["auto"]
        if b["claim"] == "done_or_underway" and not it["before"]:
            a["unsupported"] += 1
            a["affected"].add(it["conv"])
            if not it["next_transfer"]:
                a["unsupported_announce_then_act_allowed"] += 1
                a["affected_announce_then_act_allowed"].add(it["conv"])
    out = {arm: {**v, "affected": len(v["affected"]), "affected_announce_then_act_allowed": len(v["affected_announce_then_act_allowed"])}
           for arm, v in per_arm.items()}
    arms = sorted(out)
    base, treat = out.get("full_exposure"), out.get("read_exposure")
    cond6 = None if not (base and treat) else (treat["unsupported"] <= base["unsupported"] and treat["affected"] <= base["affected"])
    res = {"per_arm": out, "condition_6_met": cond6, "flagged_statements": len(blind), "read_vs_automatic_disagreements": disagree}
    (HERE / "claims_tally.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"export": export, "tally": tally}[sys.argv[1]]()
