"""Retrospective count of unsupported transfer statements in every saved conversation, both arms, H002-H005 ($0).

Definitions are H008's (bench/claims.py):
  statement     an agent text message in the trajectory (customer-facing)
  UNSUPPORTED   (primary) the READ label is done_or_underway and no successful transfer appears earlier in the
                trajectory; a later transfer does not make it true
  announce-then-act (secondary) an unsupported statement followed later in the same conversation by a successful
                transfer
Selection for blind reading: every statement with no earlier successful transfer whose automatic label is
done_or_underway, or that matches claims.FLAG. Read blind to arm, batch and task (shuffled; text only).
Reading happened in two rounds: round 1 (blind.json) used an earlier selection rule (automatic label
done_or_underway or unclear); round 2 (blind2.json) holds every statement the rule above adds. Nothing is inferred
from held transfers.

    uv run --extra bench python research/claims/retro.py export2   # round-2 items not yet read
    uv run --extra bench python research/claims/retro.py tally
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bench import claims  # noqa: E402

HERE = ROOT / "research" / "claims"
BATCHES = ("H002", "H003", "H004", "H005")


def records():
    for b in BATCHES:
        res = ROOT / "experiments" / f"{b}_results.json"
        rows = (json.loads(res.read_text())["results"] if res.exists() else
                [json.loads(x) for x in (ROOT / "experiments" / f"{b}_journal.jsonl").read_text().splitlines() if x.strip()])
        for r in rows:
            if r.get("kind") == "operator_stopped" or not r.get("trace") or not Path(r["trace"]).exists():
                continue
            yield b, r, f"{b}:{r['arm']}:{r['task_id']}:{r.get('attempt', 0)}:{Path(r['trace']).parent.name}"


def selected():
    """(conversation id, message index) -> statement, for every statement the selection rule picks."""
    out, convs = {}, {}
    for b, r, cid in records():
        msgs = json.loads(Path(r["trace"]).read_text())["messages"]
        ss = claims.statements(msgs)
        later = {s["index"]: any(m["role"] == "tool" and (m.get("content") or "").startswith("Transfer successful")
                                 for m in msgs[s["index"] + 1:]) for s in ss}
        convs[cid] = {"batch": b, "arm": r["arm"], "task": r["task_id"], "status": r["status"],
                      "statements": len(ss), "transfer_succeeded": claims.transfer_succeeded(msgs)}
        for s in ss:
            if not s["transfer_succeeded_before"] and (s["claim_auto"] == "done_or_underway" or s["flagged"]):
                out[(cid, s["index"])] = {**s, "transfer_later": later[s["index"]]}
    return out, convs


def _read_labels() -> dict:
    labels = {}
    for name in ("blind", "blind2"):
        if not (HERE / f"{name}.json").exists():
            continue
        key = {int(k): v for k, v in json.loads((HERE / f"key{'' if name == 'blind' else '2'}.json").read_text()).items()}
        for b in json.loads((HERE / f"{name}.json").read_text()):
            k = key[b["item"]]
            labels[(k["conversation"], k["index"])] = b["claim"]
    return labels


def export2():
    sel, _ = selected()
    have = _read_labels()
    missing = [k for k in sel if k not in have]
    random.Random(2003).shuffle(missing)
    (HERE / "blind2.json").write_text(json.dumps([{"item": n, "text": sel[k]["text"], "claim": None}
                                                  for n, k in enumerate(missing)], indent=1))
    (HERE / "key2.json").write_text(json.dumps({n: {"conversation": k[0], "index": k[1]} for n, k in enumerate(missing)},
                                               indent=1))
    print(f"{len(sel)} selected; {len(sel) - len(missing)} already read; {len(missing)} to read in round 2")


def tally():
    sel, convs = selected()
    labels = _read_labels()
    unread = [k for k in sel if k not in labels or labels[k] is None]
    assert not unread, f"{len(unread)} selected statements are not read yet"
    unsup = {k: claims.unsupported(sel[k], labels[k]) for k in sel}
    groups = {}
    for cid, c in convs.items():
        groups.setdefault((c["batch"], c["arm"]), []).append(cid)
    by = {}
    for (b, arm), cids in sorted(groups.items()):
        ks = [k for k in sel if k[0] in cids]
        by[f"{b} {arm}"] = {
            "conversations": len(cids),
            "unsupported_statements": sum(unsup[k] for k in ks),
            "conversations_with_unsupported": sum(any(unsup[k] for k in ks if k[0] == c) for c in cids),
            "announce_then_act_statements": sum(unsup[k] and sel[k]["transfer_later"] for k in ks),
            "unsupported_never_followed_by_a_transfer": sum(unsup[k] and not sel[k]["transfer_later"] for k in ks),
            "conversations_with_unsupported_never_followed_by_a_transfer":
                sum(any(unsup[k] and not sel[k]["transfer_later"] for k in ks if k[0] == c) for c in cids),
            "unsupported_statements_automatic_label": sum(claims.unsupported(sel[k]) for k in ks),
            "conversations_with_a_successful_transfer": sum(convs[c]["transfer_succeeded"] for c in cids)}
    dis = sum((labels[k] == "done_or_underway") != (sel[k]["claim_auto"] == "done_or_underway") for k in sel)
    traces = {cid: r["trace"] for _, r, cid in records()}

    def held(cid):  # a harness check held a transfer in this conversation
        t = json.loads(Path(traces[cid]).read_text())
        return any(e.get("event") == "held" and any(c["name"] == claims.TRANSFER for c in e.get("tool_calls") or [])
                   for e in (t.get("harness") or {}).get("events") or [])

    harness = [c for c in convs if not convs[c]["arm"].startswith("baseline")]
    bad = {k[0] for k in sel if unsup[k]}
    with_hold = [c for c in harness if held(c)]
    mechanism = {"harness_conversations": len(harness), "with_a_held_transfer": len(with_hold),
                 "held_and_unsupported": sum(c in bad for c in with_hold),
                 "unsupported_conversations": sum(c in bad for c in harness),
                 "unsupported_with_a_held_transfer": sum(c in bad for c in with_hold)}
    res = {"selected_statements": len(sel), "harness_mechanism": mechanism, "read_labels": {v: list(labels[k] for k in sel).count(v)
                                                             for v in ("done_or_underway", "intention_or_offer", "unclear", "none")},
           "disagreements_on_done_or_underway_vs_automatic": dis, "by_batch_and_arm": by}
    (HERE / "tally.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"export2": export2, "tally": tally}[sys.argv[1]]()
