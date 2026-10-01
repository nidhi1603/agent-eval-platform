"""H009 violations by channel, from the same action-level tally as V and C ($0; post-hoc, not pre-registered).

Every audited action in audit/tally.json ("final", the verdicts that produce V and C) is joined to its tool
(audit/writes.json) and to how that tool reached the agent (adapter events in the trace):
  adapter_offered   an agent write tool the adapter unlocked and offered automatically
  model_unlocked    an agent write tool the model unlocked itself (read_exposure exposes it after the unlock)
  handover          give_discoverable_user_tool
  verification      log_verification
  other             anything else (none expected)
For each arm and channel: audited actions, violations under the adjudicated reading, the reading-dependent ones, and
violations under the alternative reading. The per-arm sums are checked against tally.json's V and V_alternative, so the
channel table and the overall table cannot disagree.

    uv run --extra bench python research/h009/channels.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHANNELS = ("adapter_offered", "model_unlocked", "handover", "verification", "other")


def main():
    tally = json.loads((HERE / "audit" / "tally.json").read_text())
    key = json.loads((HERE / "audit" / "KEY_do_not_give_to_auditors.json").read_text())
    writes = json.loads((HERE / "audit" / "writes.json").read_text())
    journal = {(r["task_id"], r.get("attempt", 0), r["arm"]): r
               for r in map(json.loads, (ROOT / "experiments" / "H009_journal.jsonl").read_text().splitlines())}
    table = defaultdict(lambda: {c: {"actions": 0, "violations": 0, "reading_dependent": 0, "violations_alternative": 0,
                                     "which": []} for c in CHANNELS})
    for cid, rows in tally["final"].items():
        k = key[cid]
        trace = json.loads(Path(journal[(k["task_id"], k["attempt"], k["arm"])]["trace"]).read_text())
        events = trace["harness"].get("adapter_events") or []
        adapter = {t for e in events if e.get("event") == "unlock_turn" for t in e.get("tools") or []}
        model = {e.get("tool") for e in events if e.get("event") == "model_unlock_exposed"}
        listed = [w for w in writes[cid] if w["executed_ok"]]
        assert len(listed) == len(rows), cid
        for w, r in zip(listed, rows):
            tool = w["tool"]
            ch = ("handover" if tool.startswith("give_discoverable_user_tool") else "verification" if tool == "log_verification"
                  else "adapter_offered" if tool in adapter else "model_unlocked" if tool in model else "other")
            c = table[k["arm"]][ch]
            c["actions"] += 1
            if r["verdict"] == "unsafe_confirmed":
                c["violations"] += 1
                c["reading_dependent"] += bool(r["reading_dependent"])
                c["violations_alternative"] += not r["reading_dependent"]
                c["which"].append(f"{k['task_id']}#{k['attempt']} i={w['i']} {tool}"
                                  + (" (reading-dependent)" if r["reading_dependent"] else ""))
    scope = tally["per_scope"]["all_conversations"]
    for arm, chans in table.items():
        assert sum(c["violations"] for c in chans.values()) == scope[arm]["V"], arm
        assert sum(c["violations_alternative"] for c in chans.values()) == scope[arm]["V_alternative"], arm
    out = {"note": "post-hoc; from audit/tally.json final verdicts; sums equal tally V and V_alternative (asserted)",
           "per_arm": {arm: table[arm] for arm in sorted(table)}}
    (HERE / "channels.json").write_text(json.dumps(out, indent=1))
    for arm in sorted(table):
        print(arm)
        for ch, c in table[arm].items():
            if c["actions"]:
                print(f"  {ch:16s} actions {c['actions']:2d}  V {c['violations']}  reading-dep {c['reading_dependent']}  "
                      f"V_alt {c['violations_alternative']}")


if __name__ == "__main__":
    main()
