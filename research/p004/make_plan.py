"""Write experiments/P004_plan.json: standard agent vs standard agent + transfer_code_recheck, full conversations
on all 30 development tasks, one conversation per task per arm ($0 to write; NOT run).

The component is the one P003 screened (bench/nudge.py transfer_code_recheck): at the first proposed transfer, the
transfer is held once and the agent gets P003's treatment text (the re-check request plus doc 042). Everything else
is tau2's standard LLMAgent with H008's settings.

    uv run --extra bench python research/p004/make_plan.py
"""
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
ARM = "recheck"
SIMS = 100_000


def noise(p: dict[str, float], lift: dict[str, float], seed=4004) -> dict:
    """Net passes (treatment - control), one conversation per task per arm, conversations independent given each
    task's pass probability. Returns P(net >= +1) and P(|net| >= 2)."""
    rng = random.Random(seed)
    tasks = sorted(p)
    ge1 = abs2 = 0
    for _ in range(SIMS):
        d = sum((rng.random() < min(1.0, p[t] + lift.get(t, 0.0))) - (rng.random() < p[t]) for t in tasks)
        ge1 += d >= 1
        abs2 += abs(d) >= 2
    return {"P(net >= +1)": round(ge1 / SIMS, 3), "P(|net| >= 2)": round(abs2 / SIMS, 3)}


def main():
    import bench  # noqa: F401
    from loguru import logger
    from tau2.runner.helpers import get_tasks

    from bench import agent, batch, code_probe, nudge, pins

    logger.remove()
    dev = sorted(pins.load_split()["dev"])
    tasks = {t.id: t for t in get_tasks(pins.DOMAIN, task_ids=dev)}
    basis = {t: [b.value for b in tasks[t].evaluation_criteria.reward_basis] for t in dev}
    wants = sorted(t for t in dev if any(a.name == nudge.TRANSFER for a in tasks[t].evaluation_criteria.actions or []))
    graded = {t: code_probe.graded_reason(t) for t in dev if code_probe.graded_reason(t)}

    # order: one pair per task; pairs sorted by sha256, the first arm alternates along that order (15 / 15)
    order = sorted(dev, key=lambda t: hashlib.sha256(f"P004-order:{t}".encode()).hexdigest())
    runs = []
    for k, t in enumerate(order):
        arms = ["baseline", ARM] if k % 2 == 0 else [ARM, "baseline"]
        runs += [{"task_id": t, "arm": a, "attempt": 0} for a in arms]

    # noise floor from the standard agent's earlier passes (H008, H009 baseline arms, same settings); tasks without a
    # standard-agent run get 0.03 (the hard dev tasks: public top agents pass them almost never, research/literature)
    seen = {}
    for b in ("H008", "H009"):
        for r in json.loads((ROOT / "experiments" / f"{b}_results.json").read_text())["results"]:
            if r["arm"] == "baseline" and r.get("official_reward") is not None:
                seen.setdefault(r["task_id"], []).append(r["official_reward"])
    p = {t: (sum(seen[t]) + 0.5) / (len(seen[t]) + 1) if t in seen else 0.03 for t in dev}
    floor = {"basis": "per-task pass probability = (standard-agent passes + 0.5) / (runs + 1) from H008/H009 baseline arms "
                      f"({len(seen)} tasks); 0.03 for the other {len(dev) - len(seen)}; {SIMS:,} simulations",
             "no effect (same agent twice)": noise(p, {}),
             "+0.5 on task_004 and task_012 only": noise(p, {"task_004": 0.5, "task_012": 0.5}),
             "+1.0 on task_004 and task_012 only (both always pass)": noise(p, {"task_004": 1.0, "task_012": 1.0})}

    plan = {
        "batch_id": "P004",
        "kind": "full conversations, two paired arms (official tau2 grade); alltools; billed budget accounting",
        "status": "FROZEN DRAFT, NOT RUN. Needs review and Nidhi's explicit approval with the amount.",
        "question": ("Does adding the transfer reason-code re-check that passed P003 to tau2's standard agent change "
                     "official task completion on the development tasks, and at what cost and harm?"),
        "arms_note": ("'baseline' is tau2's standard LLMAgent, unmodified. 'recheck' is the same agent with ONE proposal-time "
                      "check, bench/nudge.py transfer_code_recheck (in bench/guard.py's checked agent, with no permission "
                      "rules and no other check): at the conversation's first proposed transfer_to_human_agents, the transfer "
                      "is held once and the agent gets P003's treatment text exactly (code_probe.feedback('treatment'); doc 042 "
                      "sha256 as frozen in P003). The reissued transfer, and any later one, is never held. No task, target "
                      "code or grading information is used at runtime."),
        "arms": {"baseline": {"agent_variant": "baseline"},
                 ARM: {"agent_variant": "baseline", "nudges": [nudge.TRANSFER_RECHECK]}},
        "registered_agents": {"baseline": agent.register("baseline"),
                              ARM: agent.register("baseline", (), (nudge.TRANSFER_RECHECK,))},
        "component_text_sha256": hashlib.sha256(code_probe.feedback("treatment").encode()).hexdigest(),
        "tier_document_sha256": hashlib.sha256(code_probe.tier_document().encode()).hexdigest(),
        "tasks": dev,
        "selection_rule": "all 30 development tasks (review); the held-out split is not touched",
        "strata": {"rule": "from each task's tau2 grade, fixed before any run",
                   "code_graded": sorted(graded), "graded_reason": graded,
                   "transfer_required": wants,
                   "reward_basis": basis,
                   "use": "descriptive; the gate is on all 30 tasks"},
        "trials_per_arm": 1,
        "runs": runs,
        "arm_order_rule": "one (task, attempt 0) pair per task, both arms back to back; pairs sorted by sha256('P004-order:' + task); the first arm alternates along that order (15 / 15)",
        "settings": {"agent_model": "gpt-5-mini", "agent_args": {"reasoning_effort": "medium"}, "user_model": "gpt-5.2",
                     "user_args": {"reasoning_effort": "low"}, "retrieval_config": "alltools", "seed": 300, "max_steps": 200,
                     "max_output_tokens": 16384, "budget_accounting": "billed"},
        "settings_note": "H008's settings unchanged and identical in both arms; the same shared infrastructure (sandbox policy, budget, trace) in both",
        "outcomes": {
            "primary": "official tau2 reward per conversation: passes per arm over complete pairs (of 30), net passes (recheck - baseline), and the paired table (both / recheck only / baseline only / neither) with the tasks named",
            "transfer_behaviour": ["executed transfers per arm; on code-graded tasks, executed transfers with the graded code",
                                   "transfer-required tasks: transfer made; other tasks: transfers made (unwanted)",
                                   "component firings; the held code and the reply: same code reissued / code changed (from -> to) / no transfer (text) / other tool call",
                                   "repeated holds (must be 0) and firings on proposals without a transfer (must be 0)",
                                   "unsupported transfer statements (H008's definition, bench/claims.py): automatic label on every agent text message; every FLAG-matched message read blind to arm (research/p004/claims_blind.py), the read label decides"],
            "policy_and_cost": ["executed writes per arm; every write executed AFTER a hold, listed and reviewed blind against the bank's policy (research/p004/verdict.py export_writes)",
                                "billed and upper-bound cost per arm, per conversation and per pass; agent calls; latency",
                                "interrupted conversations by cause"],
        },
        "decision_rule": {
            "note": ("an engineering screen fixed before the run (not a significance test). One conversation per task per arm is "
                     "noisy: see noise_floor. CONTINUE justifies a separately planned validation, never a benchmark claim."),
            "INVALID": ("an implementation defect: the check fired more than once in a conversation, fired on a proposal without a "
                        "transfer, fired in the baseline arm, or a recheck conversation's recorded nudges are not exactly "
                        "[transfer_code_recheck]; or a crash traced to the component. Reported; the defect is fixed and the "
                        "affected conversations are rerun once, disclosed."),
            "CONTINUE": "all of C1-C6 on complete pairs",
            "C1": "net passes (recheck - baseline) >= +1",
            "C2": "the mechanism is seen live: at least 1 recheck conversation on a code-graded task where the hold changed the transfer's code TO the graded code and that transfer executed",
            "C3": ("no component harm: 0 recheck conversations where (a) the held draft's code was the graded code and the executed "
                   "code is not, or (b) the task requires a transfer and none was executed after the hold"),
            "C4": "unsupported transfer statements (blind read, primary definition): recheck not higher than baseline, in statements and in conversations",
            "C5": "0 confirmed policy-violating writes executed after a hold (blind review)",
            "C6": "recheck billed cost <= 1.5 x baseline billed cost (totals over complete pairs)",
            "STOP": "any of C1-C6 fails: the candidate ends; no tuning cycle (a tie or a regression is a no-go)",
            "censoring": "a conversation interrupted by its per-run cap counts as a failure and its pair is kept; interruptions per arm are reported",
            "scoring": "every conversation counts once; nothing is retried",
        },
        "noise_floor": floor,
        "not_evidence": ("30 development tasks x 1 conversation per arm, one model: a development screen. Not an estimate of the "
                         "benchmark score, not held-out, not leaderboard-comparable (the protocol is all 97 tasks x 4 trials). "
                         "Only 2 tasks' rewards depend on the reason code (task_004, task_012), so the component can directly add at most 2 passes."),
        "forecast_usd": {"basis": "standard-agent conversations in H008: billed mean $0.079, max $0.24 (upper bound mean $0.24, max $0.74); the check adds about one agent call per conversation that proposes a transfer",
                         "expected": "an estimate awaiting evidence: about $4.00-7.00 billed for 60 conversations (the upper bound reads roughly 3x higher)"},
        "budget_usd_total": 9.0,
        "per_run_cap_usd": 0.75,
        "execution": {"workers": 2,
                      "budget_handling": "enforced on the BILLED figure; per_run_cap_usd is each conversation's reservation and its own enforced budget; $9.00 is the enforced total",
                      "incomplete": "interrupted runs keep their outcome and are not rerun; unfunded runs are not_run, never failures; incomplete pairs are excluded from the gate, with the count stated",
                      "resume": "experiments/P004_journal.jsonl",
                      "approval": "runs only after Nidhi approves in chat with the amount: 'run P004 with $9.00'"},
    }
    assert not batch.cap_headroom(plan, lambda it: {**plan["settings"], **plan["arms"][it["arm"]]})
    (ROOT / "experiments" / "P004_plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(len(runs), "runs;", json.dumps(plan["strata"]["code_graded"]), "transfer required", wants)
    print(json.dumps(floor, indent=1))


if __name__ == "__main__":
    main()
