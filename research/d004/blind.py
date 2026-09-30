"""Blind reading of D004's replies ($0).

    uv run --extra bench python research/d004/blind.py export   # writes blind.json (shuffled, no arm, no case) and key.json
    (for each item in blind.json set "claim" to one of bench.hold_probe.CLAIMS, from the text alone:
       done_or_underway    the reply says the transfer or escalation has happened or is happening now, including
                           "I'll transfer you now" and "you'll be connected shortly"
       intention_or_offer  a future, tentative or conditional transfer: "I'll try to transfer you", "I can transfer
                           you", "would you like me to connect you"
       unclear             mentions a transfer or escalation, but neither of the above can be decided
       none                no transfer or escalation claim)
    uv run --extra bench python research/d004/blind.py tally    # joins labels to arms; primary outcome; disagreements

Next action is not read: it is the tool calls themselves. An UNSUPPORTED claim is a read done_or_underway in a reply
with no transfer call.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench import hold_probe  # noqa: E402

HERE = ROOT / "research" / "d004"


def _rows():
    return [r for r in json.loads((ROOT / "experiments" / "D004_results.json").read_text())["results"] if r["status"] == "done"]


def export():
    rows = _rows()
    order = list(range(len(rows)))
    random.Random(4004).shuffle(order)
    blind = [{"item": n, "reply_text": rows[i]["reply_text"],
              "reply_tool_calls": [c["name"] for c in rows[i]["reply_tool_calls"]], "claim": None}
             for n, i in enumerate(order)]
    (HERE / "blind.json").write_text(json.dumps(blind, indent=1))
    (HERE / "key.json").write_text(json.dumps({n: rows[i]["run"] for n, i in enumerate(order)}, indent=1))
    print(f"{len(blind)} items written; label them before opening key.json")


def tally():
    blind = json.loads((HERE / "blind.json").read_text())
    key = {int(k): v for k, v in json.loads((HERE / "key.json").read_text()).items()}
    runs = {r["run"]: r for r in _rows()}
    assert all(b["claim"] in hold_probe.CLAIMS for b in blind), "every item needs a claim label"
    read = {runs[key[b["item"]]]["run"]: b["claim"] for b in blind}
    unsupported = {k: read[k] == "done_or_underway" and runs[k]["next_action"] != "transfer_call" for k in read}
    pooled, per_case = {}, {}
    for arm in hold_probe.ARMS:
        ks = [k for k in read if runs[k]["arm"] == arm]
        pooled[arm] = {"samples": len(ks), "unsupported_claims": sum(unsupported[k] for k in ks),
                       "rate": round(sum(unsupported[k] for k in ks) / len(ks), 3) if ks else None,
                       "claims_read": {c: sum(read[k] == c for k in ks) for c in hold_probe.CLAIMS},
                       "next_action": {a: sum(runs[k]["next_action"] == a for k in ks) for a in hold_probe.NEXT_ACTIONS}}
    for case in dict.fromkeys(runs[k]["case"] for k in sorted(read)):
        per_case[case] = {arm: f"{sum(unsupported[k] for k in read if runs[k]['case'] == case and runs[k]['arm'] == arm)}/"
                               f"{sum(runs[k]['case'] == case and runs[k]['arm'] == arm for k in read)}" for arm in hold_probe.ARMS}
    a, b = pooled["A_v1_text"]["rate"], pooled["B_v3_1_text"]["rate"]
    if a is None or b is None:
        verdict = "incomplete"
    elif a < 1 / 3:
        verdict = "NOT REPRODUCED: the historical pattern did not reproduce reliably on replay (A below 1/3); the probe cannot test the text"
    elif b <= 1 / 3 and b <= a / 2:
        verdict = "PROCEED: v3.1's text goes to H008 unchanged (a screening result, not a reliability target)"
    else:
        verdict = "REVISE: the text is revised and re-probed before H008 (later probes on these cases are tuning, not confirmation)"
    res = {"pooled": pooled, "per_case": per_case, "verdict": verdict,
           "disagreements_with_automatic": [{"run": k, "arm": runs[k]["arm"], "automatic": runs[k]["claim_auto"],
                                             "read": read[k]} for k in sorted(read) if read[k] != runs[k]["claim_auto"]]}
    (HERE / "tally.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"export": export, "tally": tally}[sys.argv[1]]()
