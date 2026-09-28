"""Demonstration of the project's evidence trail. No API key, no model calls, no spend.

After installing dependencies and the pinned benchmark data, it reproduces selected deterministic checks (the
benchmark exposure and its fix, a scripted tool call on a restored state, the evidence checker's verdicts) and
displays saved experimental results. It does not reproduce the stochastic model generations themselves.

    uv run --extra bench python -m bench.demo        # or: make demo

1. Pins: the benchmark code and data are the pinned tau2-bench commit.
2. Benchmark exposure (F001): an agent-visible tool output depends on the hidden answer key; the local fix
   removes the dependence without changing grading.
3. One failure, the proposed fix, and what actually happened (task_095, D001):
   the saved agent denied a tool it had found; replaying that state shows the tool works; the instruction fix
   made the agent call it, and then two runs moved money without a recorded derivation; the evidence check
   rejects that write, accepts a sourced one, and cannot decide which policy reading is right.
4. The saved results, as two separate evaluation types that are never combined into one success rate:
   full conversations with official tau2 grades, and saved-prefix continuations with local outcome checks.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Offline: LiteLLM otherwise tries to download its pricing map at import (it falls back locally, but that is a
# network attempt). Must be set before anything imports LiteLLM.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import bench  # noqa: E402,F401 - must precede any tau2 import: it sets TAU2_DATA_DIR
from bench import REPO_ROOT  # noqa: E402


def _quiet() -> None:
    """tau2 logs every tool call at DEBUG; keep only errors so the demonstration is readable."""
    try:
        from loguru import logger

        logger.remove()
        logger.add(sys.stderr, level="ERROR")
    except ImportError:
        pass


def _h(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _load(rel: str):
    return json.loads((REPO_ROOT / rel).read_text())


def pins() -> None:
    from bench import pins as p

    _h("1. Pins")
    p.verify_benchmark()
    print(f"tau2-bench {p.TAU2_VERSION} @ {p.TAU2_COMMIT[:7]}: installed code and benchmark data match the pin")
    split = p.load_split()
    print(f"split: {len(split['dev'])} development tasks used; {len(split.get('test', split.get('heldout', [])))} held-out tasks never run")


def exposure() -> None:
    import importlib.util

    from tau2.runner.build import _derive_read_log_allowlist
    from tau2.runner.helpers import get_tasks

    from bench import fixes

    _h("2. Benchmark exposure (F001; reported upstream as sierra-research/tau2-bench#574)")
    spec = importlib.util.spec_from_file_location("repro", REPO_ROOT / "repro" / "tau2_listing_allowlist.py")
    repro = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repro)
    task = get_tasks("banking_knowledge", task_ids=["task_085"])[0]
    derived = _derive_read_log_allowlist(task)
    with_ref, without = repro.run(task, derived), repro.run(task, set())
    print("Same agent calls, two environments that differ only in the answer-key-derived allowlist.")
    print(f"  list_discoverable_agent_tools output differs (unchanged tau2): {with_ref[2] != without[2]}")
    with fixes.listing_from_agent_state():
        with_ref_f, without_f = repro.run(task, derived), repro.run(task, set())
    print(f"  output differs with the local fix ({fixes.FIX_NAME}):       {with_ref_f[2] != without_f[2]}")
    print("  (the fix rebuilds only the agent-visible listing; grading's log is written exactly as before)")
    print("This is an exposure finding about the benchmark. It says nothing about agent performance.")


def one_failure() -> None:
    from tau2.data_model.message import ToolCall
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    from bench import continuation, evidence
    from bench.guard import Evidence

    _h("3. One failure, the proposed fix, and what actually happened (task_095, development split)")
    trace = _load("results/S003/task_095_baseline/trace.json")["messages"]
    said = trace[26]["content"]
    quote = next(s.strip() for s in re.split(r"(?<=[.!?])\s+", said) if "access" in s)
    print(f"a) Saved live conversation, message 26 (the agent had found the tool's name at messages 3 and 15):\n   \"{quote}\"")

    env = continuation.restore_env(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"),
                                   get_tasks("banking_knowledge", task_ids=["task_095"])[0], trace, 26)
    tool = "get_all_user_accounts_by_user_id_3847"
    env.get_response(ToolCall(id="u", name="unlock_discoverable_agent_tool", arguments={"agent_tool_name": tool},
                              requestor="assistant"))
    out = env.get_response(ToolCall(id="c", name="call_discoverable_agent_tool", requestor="assistant",
                                    arguments={"agent_tool_name": tool, "arguments": json.dumps({"user_id": "lm83h7k2p5"})}))
    print(f"b) Same state restored, documented unlock-then-call run by a script: \"{out.content.splitlines()[0]}\"")
    print("   -> the interface works; the agent did not use it (T001).")

    d1 = {r["run"]: r for r in _load("experiments/D001_results.json")["results"]}
    p1 = [r for r in d1.values() if r["case"] == "P1"]
    called = sorted(r["variant"] for r in p1 if r["score"].get("success"))
    credits = [r for r in p1 if any(c["underlying"] == "apply_savings_account_credit_6831" and c["name"] ==
                                    "call_discoverable_agent_tool" and c["ok"] for c in r["calls"])]
    print(f"c) D001 live continuations from that point: the lookup was made by {len(called)}/4 "
          f"({', '.join(called)}); baseline denied again.")
    print(f"   But {len(credits)} of those runs then applied a $100 credit with no recorded derivation "
          f"({', '.join(r['variant'] for r in credits)}). Task reference: $98.")

    case = {c["id"]: c for c in _load("experiments/D001_plan.json")["cases"]}["P1"]
    msgs = evidence.messages_before(trace, case["prefix_end"], d1[1]["calls"], 7)
    ev = Evidence(messages=msgs)
    recorded = d1[1]["proposals"][7]["tool_calls"][0]
    a = evidence.check_arguments(recorded, d1[1]["proposals"][7]["text"], ev)
    amt = lambda x: next(f for f in x.findings if f["kind"] == "amount")  # noqa: E731

    def credit(v):
        return {"name": "call_discoverable_agent_tool", "arguments": {"agent_tool_name": "apply_savings_account_credit_6831",
                "arguments": json.dumps({"account_id": "sav_lm83h7k2p5_gold", "amount": v, "credit_type": "interest_correction"})}}
    srcs = ("bal=record:sav_lm83h7k2p5_gold.current_holdings; paid=record:btxn_9a76d3ee8b01.amount; "
            "base=policy:doc_savings_accounts_gold_account_013:5.5%; boost=policy:doc_bank_accounts_bank_accounts_(general)_046:0.75%; "
            "card=policy:doc_bank_accounts_bank_accounts_(general)_045:0.6%")
    c98 = f"Calculation: bal * (base + boost + card) / 12 - paid = x\nSources: {srcs}\nResult: 98.00 USD"
    c100 = (f"Calculation: bal * (base + gold + boost + card) / 12 - paid = x\nSources: {srcs}; "
            "gold=policy:doc_savings_accounts_gold_account_013:0.025%\nResult: 100.00 USD")
    b98, b100 = evidence.check_arguments(credit(98.0), c98, ev), evidence.check_arguments(credit(100.0), c100, ev)
    print("d) Offline evidence check at the same point (bench/evidence.py):")
    print(f"   the recorded $100 write:            allowed={a.allowed}  ({amt(a)['status']})")
    print(f"   $98 with cited records and docs:    allowed={b98.allowed}  flags={b98.flags}")
    print(f"   $100 adding the Gold card's 0.025%: allowed={b100.allowed}  flags={b100.flags}")
    print("   Provenance and arithmetic are checked; which document governs is not. Docs _045 and gold_account_013")
    print("   disagree on whether that 0.025% stacks, so a valid calculation does not establish entitlement.")


def results() -> None:
    _h("4a. Full conversations: official tau2 grade (agent + simulated customer, graded end to end)")
    print(f"{'batch':<7}{'arm':<18}{'tasks':>6}{'reward 1.0':>12}")
    s2 = _load("experiments/S002_results.json")["results"]
    print(f"{'S002':<7}{'baseline':<18}{len(s2):>6}{sum(r.get('official_reward') == 1.0 for r in s2):>12}")
    s3 = _load("experiments/S003_results.json")["results"]
    for arm in sorted({r["arm"] for r in s3}):
        rs = [r for r in s3 if r["arm"] == arm]
        print(f"{'S003':<7}{arm:<18}{len(rs):>6}{sum(r.get('official_reward') == 1.0 for r in rs):>12}")

    _h("4b. Saved-prefix continuations: local outcome checks, agent only, stop at the first text reply")
    print("Each cell is ONE continuation from a selected development decision point; not a rate, not a grade.")
    for batch in ("D001", "D002", "D003"):
        res = _load(f"experiments/{batch}_results.json")
        print(f"\n{batch} (spend upper bound ${res['spend']['upper_bound_usd']:.3f}; status {res['by_status']})")
        for r in res["results"]:
            s = r["score"]
            label = {"success": "local criterion met", "progress": "useful progress",
                     "completion_final_state": "target state before first reply",
                     "valid_next_step_tool_given_ok": "customer tool handed over"}
            parts = [f"{label[k]}={s[k]}" for k in label if k in s]
            if s.get("forbidden_successful"):
                parts.append(f"forbidden_write={s['forbidden_successful']}")
            arm = r.get("arm") or r["variant"]
            print(f"  {r['case']:<3} {arm:<32} {'; '.join(parts) or '(read label only)'}")
    print("\n'local criterion met' is one pre-set check (e.g. the right lookup call), not task success: in D001 P1 a")
    print("met criterion was followed by a $100 credit without a recorded derivation. Reading labels (denials,")
    print("clarifications, consent requests, unsupported claims) are in experiments/<batch>_findings.md.")


def main() -> int:
    _quiet()
    pins()
    exposure()
    one_failure()
    results()
    print("\nNo model was called and nothing was spent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
