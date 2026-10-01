"""Build the blind H008 safety-audit set ($0), per experiments/H008_plan.json (outcomes.safety_audit) and the review
of the H008 results: every conversation with an executed write (both arms), both conversations of every
(task, attempt) pair whose outcome differs, and the 2 conversations interrupted by the provider credit outage.

Each conversation becomes convs/<id>.json: the benchmark trajectory (what the environment executed and what the
customer saw), with an id that does not reveal the arm.
Blinding steps:
- Every tool-call id is renamed to a neutral sequence (harness turns used telltale ids).
- Every retrieval QUERY is withheld in both arms (the harness's capability queries are worded recognisably). Results
  are kept: KB_search_* results as document ids and titles, shell output truncated to 1,500 characters.
Known limits: the harness adapter unlocks several tools in one message, and the harness's searches run in pairs
(BM25 then dense) right after verification; an attentive auditor may infer the arm. The key goes to
KEY_do_not_give_to_auditors.json.

    uv run --extra bench python research/h008/audit/make_convs.py
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RESULT = re.compile(r"^\d+\.\s+(.*)\n\s+ID:\s*(doc_\S+)", re.M)
SEARCH = {"KB_search", "KB_search_bm25", "KB_search_dense"}


def main():
    diag = json.loads((ROOT / "research" / "h008" / "diagnostics.json").read_text())
    queue = {(q["task"], q["attempt"], q["arm"]) for q in diag["audit_queue"]}
    journal = [json.loads(x) for x in (ROOT / "experiments" / "H008_journal.jsonl").read_text().splitlines() if x.strip()]
    key, ids = {}, []
    for r in journal:
        k = (r["task_id"], r.get("attempt", 0), r["arm"])
        if k not in queue or not r.get("trace") or not Path(r["trace"]).exists():
            continue
        t = json.loads(Path(r["trace"]).read_text())
        rename, names = {}, {}
        for m in t["messages"]:
            for c in m.get("tool_calls") or []:
                rename[c["id"]] = f"call_{len(rename) + 1}"
                names[c["id"]] = c["name"]
        msgs = []
        for i, m in enumerate(t["messages"]):
            d = {"i": i, "role": m["role"]}
            if m["role"] == "tool":
                name = names.get(m.get("tool_call_id"))
                text = m.get("content") or ""
                if name in SEARCH:
                    text = "Search results (open the document files for full text): " + "; ".join(
                        f"{doc} ({title.strip()})" for title, doc in RESULT.findall(text))
                elif name == "shell":
                    text = text[:1500] + (" [...truncated]" if len(text) > 1500 else "")
                d["content"] = text
                d["tool_call_id"] = rename.get(m.get("tool_call_id"), "call_?")
                if m.get("error"):
                    d["error"] = True
            else:
                if m.get("content"):
                    d["content"] = m["content"]
                if m.get("tool_calls"):
                    d["tool_calls"] = [{"id": rename[c["id"]], "name": c["name"],
                                        "arguments": ({"query": "[withheld for blinding]"} if c["name"] in SEARCH
                                                      else c["arguments"])} for c in m["tool_calls"]]
            msgs.append(d)
        cid = "c" + hashlib.sha256(f"H008-audit:{k}".encode()).hexdigest()[:6]
        outcome = ("passed" if (r.get("official_reward") or 0) >= 1 else "failed") if r["status"] == "finished" \
            else "interrupted (provider credit outage; not graded)"
        (OUT / "convs" / f"{cid}.json").write_text(json.dumps({"id": cid, "task_id": r["task_id"], "outcome": outcome,
                                                               "messages": msgs}, indent=1))
        key[cid] = {"task_id": r["task_id"], "arm": r["arm"], "attempt": r.get("attempt", 0), "status": r["status"],
                    "official_reward": r.get("official_reward")}
        ids.append(cid)
    ids.sort()
    batches = [ids[i::4] for i in range(4)]
    (OUT / "KEY_do_not_give_to_auditors.json").write_text(json.dumps(key, indent=1))
    (OUT / "batches.json").write_text(json.dumps(batches, indent=1))
    print(len(ids), [len(b) for b in batches])


if __name__ == "__main__":
    main()
