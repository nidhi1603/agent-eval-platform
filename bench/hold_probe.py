"""Next-message probe of the transfer-hold feedback (development diagnostic; plan: experiments/D004_plan.json).

Question: after the harness holds a transfer, does the feedback text decide whether gpt-5-mini then tells the
customer a transfer is under way (none was made)? research/v3_1/held_transfers.json: with v1's text it did in 9 of 9
saved histories.

Each case is a saved H004 conversation in which v1's give-up check held a transfer_to_human_agents call and the
model's own history (trace["harness"]["model_view"]) was saved. The model is given exactly that history up to and
including its held transfer proposal, then the tool result for the held call:
  A_v1_text     the feedback it actually received (read from the saved history, byte for byte)
  B_v3_1_text   the feedback harness v3.1 would give at the same point (bench/harness.py, computed from the same
                evidence, with capability advice on as in H008)
Everything else is the original run's: system prompt (tau2's, unmodified policy), tool list (the benchmark's tools
plus the tools the adapter had offered by then), model and reasoning setting. One model call per run; the reply is
recorded and classified, never executed. No environment is changed and nothing is graded by tau2.

Reconstruction is checked before any call (`preflight`): v1's text recomputed from the saved history must equal the
text the model received, and the tools offered then must be a subset of those the run offered in the end.

Cases were chosen after observing the failure: a development diagnostic of one mechanism, not a pass-rate estimate.

    uv run --extra bench python -m bench.hold_probe experiments/D004_plan.json --approved-usd X
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bench import REPO_ROOT, pins

TRANSFER = "transfer_to_human_agents"
ARMS = ("A_v1_text", "B_v3_1_text")
# a reply telling the customer a transfer or escalation is happening or done (research/v3_1/held_transfers.py)
CLAIM = re.compile(r"transferr?(ed|ing)|connect(ing|ed)? you|handoff|hand(ing|ed)? (you|this) (off|over)|escalat(ed|ing)|"
                   r"transfer request submitted|\"transfer\": \"completed\"|I.ll transfer you", re.I)
LABELS = ("transfer_again", "retrieval", "other_tool", "claims_transfer", "other_text")


class PlanError(Exception):
    """The plan does not match what would run. Raised before any network call."""


def classify(message: dict) -> str:
    """The pre-registered automatic label of one reply (a dict with content and tool_calls)."""
    names = [c["name"] for c in message.get("tool_calls") or []]
    if TRANSFER in names:
        return "transfer_again"
    if any(n.startswith("KB_search") or n == "shell" for n in names):
        return "retrieval"
    if names:
        return "other_tool"
    return "claims_transfer" if CLAIM.search(message.get("content") or "") else "other_text"


def _tau2(messages: list[dict]):
    """Model-view dicts (bench.guard.messages_as_dicts form) -> tau2 messages, system notes included."""
    from tau2.data_model.message import AssistantMessage, SystemMessage, ToolCall, ToolMessage, UserMessage

    out = []
    for m in messages:
        if m["role"] == "assistant":
            calls = [ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"], requestor="assistant")
                     for c in m.get("tool_calls") or []] or None
            out.append(AssistantMessage(role="assistant", content=m.get("content"), tool_calls=calls))
        elif m["role"] == "tool":
            out.append(ToolMessage(id=m["tool_call_id"], role="tool", content=m.get("content"), requestor="assistant",
                                   error=bool(m.get("error"))))
        elif m["role"] == "system":
            out.append(SystemMessage(role="system", content=m.get("content")))
        else:
            out.append(UserMessage(role="user", content=m.get("content")))
    return out


class Case:
    """One saved conversation at its held transfer, with everything needed to rebuild the model's input."""

    def __init__(self, spec: dict):
        from loguru import logger
        from tau2.data_model.simulation import TextRunConfig
        from tau2.runner.helpers import get_tasks

        from bench.adapter import names_in_kb_results
        from bench.guard import toolkit_type_lookup
        from bench.independence import fresh_env

        logger.remove()
        self.spec = spec
        path = REPO_ROOT / spec["source_trace"]
        self.trace = json.loads(path.read_text())
        self.view = self.trace["harness"]["model_view"]
        i = spec["held_index"]
        self.proposal = self.view[i]
        if self.proposal["role"] != "assistant" or TRANSFER not in [c["name"] for c in self.proposal.get("tool_calls") or []]:
            raise PlanError(f"case {spec['id']}: message {i} is not the agent's transfer proposal")
        ids = [c["id"] for c in self.proposal["tool_calls"]]
        self.results = self.view[i + 1:i + 1 + len(ids)]
        if [m.get("tool_call_id") for m in self.results] != ids:
            raise PlanError(f"case {spec['id']}: the held proposal's tool results do not follow it")
        self.transfer_id = next(c["id"] for c in self.proposal["tool_calls"] if c["name"] == TRANSFER)
        self.task = get_tasks(pins.DOMAIN, task_ids=[spec["task_id"]])[0]
        self.env = fresh_env(TextRunConfig(domain=pins.DOMAIN, retrieval_config=spec["retrieval_config"]), self.task)
        self.tool_type = toolkit_type_lookup(self.env.tools)
        self.agent_tools = frozenset(self.env.tools.get_discoverable_tools())
        self.user_tools = frozenset(self.env.user_tools.get_discoverable_tools())
        self.before = self.view[:i]
        self.offered = sorted(names_in_kb_results(_tau2(self.before), self.agent_tools))

    def ctx(self, v3_1: bool) -> dict:
        return {"agent_tools": set(self.agent_tools), "user_tools": set(self.user_tools), "tool_type": self.tool_type,
                "events": [], "capability_advice": v3_1, "transfer_hold_once": v3_1, "transfer_holds": 0}

    def feedback(self, arm: str) -> str:
        """The tool result the model gets for its held transfer call, in this arm."""
        if arm == "A_v1_text":
            return next(m["content"] for m in self.results if m["tool_call_id"] == self.transfer_id)
        return self._computed(v3_1=True)

    def _computed(self, v3_1: bool) -> str:
        from bench import harness
        from bench.guard import Evidence

        found = harness.gate_search_before_giving_up(self.proposal, Evidence(messages=list(self.before),
                                                                            tool_type=self.tool_type), self.ctx(v3_1))
        if len(found) != 1:
            raise PlanError(f"case {self.spec['id']}: the check does not hold this transfer when recomputed")
        return found[0].message

    def checks(self) -> dict:
        """Reconstruction checks (all must be true before any call)."""
        final = set((self.trace.get("harness") or {}).get("offered") or [])
        return {"v1_text_recomputed_exactly": self._computed(v3_1=False) == self.feedback("A_v1_text"),
                "offered_then_subset_of_offered_at_end": set(self.offered) <= final,
                "held_call_marked_error": all(m.get("error") for m in self.results
                                              if m["tool_call_id"] == self.transfer_id)}

    def messages(self, arm: str) -> list[dict]:
        """The model's history for this arm: saved history through the held proposal, then the tool result(s)."""
        text = self.feedback(arm)
        return self.before + [self.proposal] + [dict(m, content=text) if m["tool_call_id"] == self.transfer_id else m
                                                for m in self.results]

    def agent(self, model: str, llm_args: dict):
        from tau2.environment.tool import as_tool

        from bench import agent as agent_mod

        a = agent_mod.factory(tools=self.env.get_tools(), domain_policy=self.env.get_policy(), variant="baseline",
                              harness=self.spec["source_harness"], llm=model, llm_args=dict(llm_args))
        a.adapter_toolkit = self.env.tools
        a.agent_tool_names = self.agent_tools
        a.user_tool_names = self.user_tools
        a.offered = {n: as_tool(self.env.tools.tools[n]) for n in self.offered}
        return a


def probe(case: Case, arm: str, model: str, llm_args: dict) -> dict:
    """One next-message sample. The caller installs spending control (bench.budget.install)."""
    from bench.guard import messages_as_dicts

    agent = case.agent(model, llm_args)
    state = agent.get_init_state()
    state.messages = _tau2(case.messages(arm))  # as in a live run, where harness notes enter the history mid-run
    reply = messages_as_dicts([agent._generate(state)])[0]
    return {"reply_text": reply.get("content"), "reply_tool_calls": reply.get("tool_calls") or [],
            "label": classify(reply)}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(plan: dict, approved_usd: float) -> tuple[dict, dict[str, Case]]:
    """Everything that must hold before any network call. Returns the manifest (saved first) and the cases."""
    if plan.get("budget_usd_total") is None or abs(approved_usd - plan["budget_usd_total"]) > 1e-9:
        raise PlanError(f"approved ${approved_usd} does not match the plan's ${plan.get('budget_usd_total')}")
    dev = set(pins.load_split()["dev"])
    cases: dict[str, Case] = {}
    for spec in plan["cases"]:
        if spec["task_id"] not in dev:
            raise PlanError(f"case {spec['id']}: {spec['task_id']} is not a development task")
        path = REPO_ROOT / spec["source_trace"]
        if not path.is_file() or _sha(path) != spec["trace_sha256"]:
            raise PlanError(f"case {spec['id']}: source trace missing or changed")
        c = Case(spec)
        bad = [k for k, ok in c.checks().items() if not ok]
        if bad:
            raise PlanError(f"case {spec['id']}: reconstruction check failed: {bad}")
        cases[spec["id"]] = c
    for r in plan["runs"]:
        if r["case"] not in cases or r["arm"] not in ARMS:
            raise PlanError(f"run {r} references an unknown case or arm")
    return ({"batch_id": plan["batch_id"], "created_at": datetime.now(timezone.utc).isoformat(),
             "approved_usd": approved_usd,
             "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
             "harness_sha256": _sha(REPO_ROOT / "bench" / "harness.py"),
             "feedback_texts": {cid: {arm: c.feedback(arm) for arm in ARMS} for cid, c in cases.items()},
             "benchmark": pins.verify_benchmark(), "provenance": pins.provenance()}, cases)


def summarize(rows: list[dict]) -> dict:
    out = {}
    for arm in ARMS:
        xs = [r for r in rows if r["arm"] == arm and r.get("label")]
        out[arm] = {"samples": len(xs), **{lab: sum(r["label"] == lab for r in xs) for lab in LABELS},
                    "claims_transfer_rate": round(sum(r["label"] == "claims_transfer" for r in xs) / len(xs), 3) if xs else None}
    return out


def main(argv=None, send=None, prices=None) -> int:
    from bench.budget import Budget, Limits, install, load_prices

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("plan", type=Path)
    p.add_argument("--approved-usd", type=float, required=True, help="must equal the plan's budget_usd_total")
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments")
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    try:
        manifest, cases = preflight(plan, a.approved_usd)
    except PlanError as e:
        raise SystemExit(f"preflight failed, nothing was sent: {e}") from e
    if send is None:
        import litellm
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
        litellm.suppress_debug_info = True
    s = plan["settings"]
    out_dir = a.out_dir / f"{plan['batch_id']}_runs"
    out_dir.mkdir(exist_ok=False)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")  # saved first
    budget = Budget(a.approved_usd, prices or load_prices(), out_dir / "ledger.jsonl",
                    accounting=s.get("budget_accounting", "upper_bound"))
    rows, stopped = [], False
    with install(budget, Limits(max_output_tokens=s["max_output_tokens"]), send=send):
        for k, item in enumerate(plan["runs"]):
            row = {"run": k, **item}
            if stopped:
                rows.append({**row, "status": "not_run", "reason": "allocation exhausted"})
                continue
            n0 = len(budget.calls)
            try:
                row.update(probe(cases[item["case"]], item["arm"], s["agent_model"], s["agent_args"]), status="done")
            except Exception as e:  # noqa: BLE001 - keep the record; stop on a budget error
                row.update(status="error", error=f"{type(e).__name__}: {e}"[:500])
                stopped = type(e).__name__ in ("BudgetExceeded", "BoundViolation")
            row["ledger_calls"] = [c.seq for c in budget.calls[n0:]]
            rows.append(row)
            (out_dir / "results.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
    summary = {"batch_id": plan["batch_id"], "finished_at": datetime.now(timezone.utc).isoformat(),
               "by_status": {st: sum(r["status"] == st for r in rows) for st in {r["status"] for r in rows}},
               "labels": summarize(rows), "spend": budget.summary(), "results": rows}
    (a.out_dir / f"{plan['batch_id']}_results.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("by_status", "labels", "spend")}, indent=2, default=str))
    return 3 if any(r["status"] != "done" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
