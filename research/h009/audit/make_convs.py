"""Build the blind H009 safety-audit set ($0), per experiments/H009_plan.json (outcomes.safety_audit).

Scope: EVERY conversation, in both arms and interrupted ones included, with at least one audited action. Audited
actions are fixed here, before labelling, and written to writes.json in H008's format: every agent call the
benchmark types as a write (bench/metrics.py kind(); log_verification included) and every give_discoverable_user_tool
handover. Conversations with none are listed in no_audited_action.json (no violating action by definition).

Each conversation becomes convs/<id>.json: the benchmark trajectory (what the environment executed and what the
customer saw), with an id that does not reveal the arm.
Blinding steps:
- Every tool-call id is renamed to a neutral sequence (harness turns used telltale ids).
- Every retrieval QUERY is withheld (the harness's capability queries are worded recognisably). Results are kept:
  KB_search_* results as document ids and titles, shell output truncated to 1,500 characters.
Known limit (plan): both arms run harness v3.1, but read_exposure shows more model-issued unlocks and fewer
adapter unlocks of write tools; an attentive auditor may infer the arm. The key goes to
KEY_do_not_give_to_auditors.json.

    uv run --extra bench python research/h009/audit/make_convs.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "h002"))
OUT = Path(__file__).resolve().parent
RESULT = re.compile(r"^\d+\.\s+(.*)\n\s+ID:\s*(doc_\S+)", re.M)
SEARCH = {"KB_search", "KB_search_bm25", "KB_search_dense"}
GIVE = "give_discoverable_user_tool"


def audited_actions(messages, tool_type):
    """The fixed action list for one conversation, in H008's writes.json format."""
    from bench import metrics

    results = {m.get("tool_call_id"): m for m in messages if m.get("role") == "tool"}
    out = []
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        for c in m.get("tool_calls") or []:
            if c["name"] != GIVE and metrics.kind(c["name"], c["arguments"], tool_type) != "write":
                continue
            res = results.get(c["id"]) or {}
            ok = not res.get("error") and not (res.get("content") or "").lstrip().startswith("Error")
            tool = (f"{GIVE}:{(c['arguments'] or {}).get('discoverable_tool_name') or (c['arguments'] or {}).get('tool_name')}"
                    if c["name"] == GIVE else metrics.underlying(c["name"], c["arguments"]))
            out.append({"i": i, "role": "assistant", "tool": tool, "executed_ok": ok})
    return out


def main():
    from loguru import logger
    from tool_retrieval_probe import registry

    logger.remove()
    tool_type = registry()[1]
    diag = json.loads((ROOT / "research" / "h009" / "diagnostics.json").read_text())
    queue = {(q["task"], q["attempt"], q["arm"]) for q in diag["audit_queue"]}
    journal = [json.loads(x) for x in (ROOT / "experiments" / "H009_journal.jsonl").read_text().splitlines() if x.strip()]
    key, ids, skipped, writes = {}, [], [], {}
    for r in journal:
        k = (r["task_id"], r.get("attempt", 0), r["arm"])
        if k not in queue or not r.get("trace") or not Path(r["trace"]).exists():
            continue
        t = json.loads(Path(r["trace"]).read_text())
        audited = audited_actions(t["messages"], tool_type)
        if not audited:
            skipped.append(k)
            continue
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
        cid = "c" + hashlib.sha256(f"H009-audit:{k}".encode()).hexdigest()[:6]
        outcome = ("passed" if (r.get("official_reward") or 0) >= 1 else "failed") if r["status"] == "finished" \
            else "interrupted (not graded)"
        (OUT / "convs" / f"{cid}.json").write_text(json.dumps({"id": cid, "task_id": r["task_id"], "outcome": outcome,
                                                               "messages": msgs}, indent=1))
        key[cid] = {"task_id": r["task_id"], "arm": r["arm"], "attempt": r.get("attempt", 0), "status": r["status"],
                    "official_reward": r.get("official_reward")}
        writes[cid] = audited
        ids.append(cid)
    ids.sort()
    batches = [ids[i::4] for i in range(4)]
    (OUT / "KEY_do_not_give_to_auditors.json").write_text(json.dumps(key, indent=1))
    (OUT / "writes.json").write_text(json.dumps(writes, indent=1))
    (OUT / "batches.json").write_text(json.dumps(batches, indent=1))
    (OUT / "no_audited_action.json").write_text(json.dumps([list(k) for k in skipped], indent=1))
    print(len(ids), [len(b) for b in batches], "conversations with no audited action:", len(skipped))


if __name__ == "__main__":
    main()
