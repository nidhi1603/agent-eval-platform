"""Build the blind H004 safety-audit set ($0), per experiments/H004_plan.json (safety_audit):
(a) every conversation with an executed write, both arms; (b) both conversations of every pair whose pass/fail differs.

Each conversation becomes convs/<id>.json with an id that does not reveal the arm, the benchmark trajectory only
(what the environment executed; search results shown as document ids and titles), and the official outcome.
The arm/attempt key goes to KEY_do_not_give_to_auditors.json. Known limit of the blinding: in the dependency-search
arm, the adapter may unlock tools that no search result in the trajectory names (they came from added documents).

    uv run --extra bench python research/h004/audit/make_convs.py
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RESULT = re.compile(r"^\d+\.\s+(.*)\n\s+ID:\s*(doc_\S+)", re.M)


def condense_kb(text: str) -> str:
    docs = "; ".join(f"{d} ({t.strip()})" for t, d in RESULT.findall(text or ""))
    return "KB_search results (open the document files for full text): " + docs


def main():
    diag = json.loads((ROOT / "research" / "h004" / "diagnostics.json").read_text())
    queue = {(q["task"], q["attempt"], q["arm"]) for q in diag["audit_queue"]}
    res = json.loads((ROOT / "experiments" / "H004_results.json").read_text())
    key, ids = {}, []
    for r in res["results"]:
        k = (r["task_id"], r["attempt"], r["arm"])
        if k not in queue:
            continue
        t = json.loads(Path(r["trace"]).read_text())
        calls = {c["id"]: c["name"] for m in t["messages"] for c in (m.get("tool_calls") or [])}
        msgs = []
        for i, m in enumerate(t["messages"]):
            d = {"i": i, "role": m["role"]}
            if m.get("content"):
                d["content"] = (condense_kb(m["content"]) if m["role"] == "tool" and calls.get(m.get("tool_call_id"))
                                == "KB_search" else m["content"])
            if m.get("tool_calls"):
                d["tool_calls"] = [{"id": c["id"], "name": c["name"], "arguments": c["arguments"]}
                                   for c in m["tool_calls"]]
            if m["role"] == "tool":
                d["tool_call_id"] = m.get("tool_call_id")
                if m.get("error"):
                    d["error"] = True
            msgs.append(d)
        cid = "c" + hashlib.sha256(f"H004-audit:{k}".encode()).hexdigest()[:6]
        outcome = ("passed" if (r.get("official_reward") or 0) >= 1 else "failed") if r["status"] == "finished" \
            else "interrupted (budget)"
        (OUT / "convs" / f"{cid}.json").write_text(json.dumps({"id": cid, "task_id": r["task_id"], "outcome": outcome,
                                                               "messages": msgs}, indent=1))
        key[cid] = {"task_id": r["task_id"], "arm": r["arm"], "attempt": r["attempt"], "status": r["status"],
                    "official_reward": r.get("official_reward")}
        ids.append(cid)
    ids.sort()
    batches = [ids[i::4] for i in range(4)]
    (OUT / "KEY_do_not_give_to_auditors.json").write_text(json.dumps(key, indent=1))
    (OUT / "batches.json").write_text(json.dumps(batches, indent=1))
    print(len(ids), [len(b) for b in batches])


if __name__ == "__main__":
    main()
