"""Bounded offline tally of task-execution failures ($0; after the P002 review). Export step.

Corpus: every FAILED conversation (official reward 0 or none) in H008, H009 and P001: gpt-5-mini, medium effort,
alltools; standard agent and harness v3.1/v3.2 arms.
- AUDITED (H008/H009 conversations with at least one audited action): the safety audit's first-pass label gives the
  first consequential error (primary category, index, evidence). Exported as short items, blind to arm.
- UNAUDITED (H008/H009 failures with no audited action, and all P001 conversations): exported as blinded
  conversations for a full read.
Arm, batch and task outcome are withheld from readers (KEY.json). P002 continuations are excluded (selected states).

    uv run --extra bench python research/post_verification/export.py
"""
import glob
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
CLIP = 1500


def _code(s):
    return "x" + hashlib.sha256(f"postver:{s}".encode()).hexdigest()[:6]


def _render(trace):
    ids, out = {}, []
    for i, m in enumerate(trace["messages"]):
        d = {"i": i, "role": m["role"]}
        if m.get("content"):
            c = m["content"]
            d["content"] = c if m["role"] != "tool" or len(c) <= CLIP else c[:CLIP] + " …[truncated]"
        if m.get("tool_calls"):
            d["tool_calls"] = []
            for c in m["tool_calls"]:
                ids[c["id"]] = f"call_{len(ids) + 1}"
                d["tool_calls"].append({"id": ids[c["id"]], "name": c["name"], "arguments": c["arguments"]})
        if m["role"] == "tool":
            d["tool_call_id"] = ids.get(m.get("tool_call_id"), "?")
            d["error"] = bool(m.get("error"))
        out.append(d)
    return out


def main():
    key, items, convs = {}, [], []
    (OUT / "convs").mkdir(exist_ok=True)
    audited_runs = set()
    for b in ("h008", "h009"):
        d = ROOT / "research" / b / "audit"
        k = json.loads((d / "KEY_do_not_give_to_auditors.json").read_text())
        first = {}
        for f in sorted(glob.glob(str(d / "labels_[0-9].json"))):
            for x in json.loads(Path(f).read_text()):
                first[x["id"]] = x
        for aid, x in first.items():
            meta = k[aid]
            audited_runs.add((b.upper(), meta["task_id"], meta["arm"], meta.get("attempt", 0)))
            if meta.get("official_reward") == 1.0 or x["primary"] == "PASS":
                continue
            c = _code(f"{b}:{aid}")
            items.append({"id": c, "task_id": x["task_id"], "audit_conversation": f"research/{b}/audit/convs/{aid}.json",
                          **{f: x.get(f) for f in ("primary", "primary_index", "evidence", "flags", "evidence_available_at_failure",
                                                   "missing_requirement_doc", "claimed_done_without_receipt_indices",
                                                   "non_write_harms", "unsafe_write_detail", "transfers", "notes")}})
            key[c] = {"batch": b.upper(), "audit_id": aid, **meta, "source": "audited"}
    for b in ("H008", "H009", "P001"):
        for r in json.loads((ROOT / "experiments" / f"{b}_results.json").read_text())["results"]:
            if r.get("official_reward") == 1.0 or not r.get("trace"):
                continue
            if (b, r["task_id"], r["arm"], r.get("attempt", 0)) in audited_runs:
                continue
            t = json.loads(Path(r["trace"]).read_text())
            c = _code(f"{b}:{r['run_id']}")
            (OUT / "convs" / f"{c}.json").write_text(json.dumps({"id": c, "task_id": r["task_id"],
                                                                  "messages": _render(t)}, indent=1))
            convs.append(c)
            key[c] = {"batch": b, "task_id": r["task_id"], "arm": r["arm"], "attempt": r.get("attempt", 0),
                      "run_id": r["run_id"], "trace": r["trace"], "official_reward": r.get("official_reward"),
                      "source": "full_read"}
    (OUT / "audited_items.json").write_text(json.dumps(items, indent=1))
    (OUT / "KEY_do_not_give_to_readers.json").write_text(json.dumps(key, indent=1))
    print(json.dumps({"audited_failed": len(items), "full_read": len(convs),
                      "by_batch": {b: sum(v["batch"] == b for v in key.values()) for b in ("H008", "H009", "P001")}}))


if __name__ == "__main__":
    main()
