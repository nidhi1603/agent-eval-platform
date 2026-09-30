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
text the model received, and the tool list (names and schemas) must hash to the tools_sha256 the original run's
ledger recorded for the model call at that exact point. After the run, each A reply's input token count can be set
against that original call's (`original_input_tokens`).

Two outcomes per reply, scored separately (a reply can carry both text and a tool call):
  next_action   transfer_call | retrieval | other_tool | text_only                      (from the tool calls)
  claim         done_or_underway | intention_or_offer | unclear | none                   (from the text)
An UNSUPPORTED claim is done_or_underway in a reply with no transfer call. The automatic claim label is provisional;
every reply is read blind to arm (research/d004/blind.py) and the read label decides.

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
NEXT_ACTIONS = ("transfer_call", "retrieval", "other_tool", "text_only")
CLAIMS = ("done_or_underway", "intention_or_offer", "unclear", "none")
# says the transfer or escalation has happened or is happening now
DONE = re.compile(r"\b(?:have|has|'ve|’ve) (?:been )?(?:transferred|escalated|connected|handed)|(?<!try )\btransferring you|"
                  r"(?<!try )\bconnecting you|\byou(?:'re|’re| are) (?:now )?being (?:transferred|connected)|\bescalating (?:this|you|your)|"
                  r"\b(?:initiated|started|submitted|created) (?:a |the )?(?:handoff|transfer|escalation)|"
                  r"\b(?:handoff|transfer|escalation)(?: request)? (?:is |has been )?(?:initiated|submitted|completed|in progress)|"
                  r"\"transfer\": \"completed\"|\bI(?:'m|’m| am) (?:now )?(?:transferring|connecting|escalating|handing)|"
                  r"\bI(?:'ll|’ll| will) (?:now )?(?:transfer|connect|escalate)[^.?!]{0,60}\bnow\b|"  # "I'll transfer you ... now"
                  r"\byou(?:'ll|’ll| should| will) be (?:connected|transferred) (?:shortly|soon|in a moment)", re.I)
# a future or conditional transfer: "I'll transfer you", "would you like me to connect you"
INTENT = re.compile(r"\bI(?:'ll|’ll| will) (?:try (?:to )?|now )?(?:transfer|connect|escalate|hand)|\btry (?:transferring|connecting)|"
                    r"\bI can (?:transfer|connect|escalate)|\bwould you like (?:me to|to be) (?:transfer|connect)|"
                    r"\b(?:shall|should) I (?:transfer|connect|escalate)|\bdo you want me to (?:transfer|connect|escalate)", re.I)
MENTION = re.compile(r"transfer|escalat|human (?:agent|specialist)|specialist team|hand ?off", re.I)


class PlanError(Exception):
    """The plan does not match what would run. Raised before any network call."""


def next_action(message: dict) -> str:
    names = [c["name"] for c in message.get("tool_calls") or []]
    if TRANSFER in names:
        return "transfer_call"
    if any(n.startswith("KB_search") or n == "shell" for n in names):
        return "retrieval"
    return "other_tool" if names else "text_only"


def claim(text: str | None) -> str:
    """Provisional automatic claim label; the blind reading decides."""
    text = text or ""
    if DONE.search(text):
        return "done_or_underway"
    if INTENT.search(text):
        return "intention_or_offer"
    return "unclear" if MENTION.search(text) else "none"


def classify(message: dict) -> dict:
    """The pre-registered automatic outcomes of one reply (a dict with content and tool_calls)."""
    act, cl = next_action(message), claim(message.get("content"))
    return {"next_action": act, "claim_auto": cl,
            "unsupported_claim_auto": cl == "done_or_underway" and act != "transfer_call"}


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
        # the original run's ledger entry for the model call that answered the hold (tools, input tokens)
        from bench.harness import WITHHELD

        def by_model(msgs, start):  # tau2's opening greeting, fixed replies and harness turns are not model calls
            return [m for k, m in enumerate(msgs, start) if m["role"] == "assistant" and k > 0
                    and m.get("content") not in WITHHELD.values()
                    and not any(c["id"].startswith(("capability_", "adapter_unlock_")) for c in m.get("tool_calls") or [])]

        calls = [e for e in (self.trace.get("spend") or {}).get("ledger") or []
                 if e.get("role") == "agent" and e.get("kind") == "chat" and e.get("status") == "ok"]
        self.aligned = len(by_model(self.view, 0)) == len(calls)  # one completed model call per model message
        n = len(by_model(self.view[:i + 1], 0))                    # model messages through the held proposal
        self.held_call = calls[n - 1] if 0 < n <= len(calls) else None
        self.original_call = calls[n] if n < len(calls) else None   # the call that answered the hold

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

    def tools_sha256(self) -> str:
        """The tool list as the probe will send it, hashed as bench/budget.py hashes every request's tools."""
        a = self.agent("probe", {})
        tools = list(a.tools) + [t for n, t in sorted(a.offered.items()) if n not in {x.name for x in a.tools}]
        return hashlib.sha256(json.dumps([t.openai_schema for t in tools], sort_keys=True).encode()).hexdigest()

    def checks(self) -> dict:
        """Reconstruction checks (all must be true before any call)."""
        sha = self.tools_sha256()
        params = lambda e: (e or {}).get("request_params") or {}  # noqa: E731
        return {"v1_text_recomputed_exactly": self._computed(v3_1=False) == self.feedback("A_v1_text"),
                "model_messages_align_with_the_ledger": self.aligned,
                "tools_match_the_original_request_after_the_hold": params(self.original_call).get("tools_sha256") == sha,
                "tools_match_the_original_request_that_proposed_the_transfer": params(self.held_call).get("tools_sha256") == sha,
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
    return {"reply_text": reply.get("content"), "reply_tool_calls": reply.get("tool_calls") or [], **classify(reply)}


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
             "tools_sha256": {cid: c.tools_sha256() for cid, c in cases.items()},
             "original_input_tokens": {cid: (c.original_call or {}).get("input_tokens") for cid, c in cases.items()},
             "benchmark": pins.verify_benchmark(), "provenance": pins.provenance()}, cases)


def summarize(rows: list[dict]) -> dict:
    """Automatic outcomes, pooled and per case (the 27 samples per arm are repeated draws from 9 histories)."""
    done = [r for r in rows if r.get("status") == "done"]
    out = {"pooled": {}, "per_case": {}}
    for arm in ARMS:
        xs = [r for r in done if r["arm"] == arm]
        out["pooled"][arm] = {"samples": len(xs),
                              "next_action": {a: sum(r["next_action"] == a for r in xs) for a in NEXT_ACTIONS},
                              "claim_auto": {c: sum(r["claim_auto"] == c for r in xs) for c in CLAIMS},
                              "unsupported_claim_auto": sum(r["unsupported_claim_auto"] for r in xs)}
    for case in dict.fromkeys(r["case"] for r in done):
        out["per_case"][case] = {arm: f"{sum(r['unsupported_claim_auto'] for r in done if r['case'] == case and r['arm'] == arm)}"
                                      f"/{sum(r['case'] == case and r['arm'] == arm for r in done)}" for arm in ARMS}
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
            new = budget.calls[n0:]
            row["ledger_calls"] = [c.seq for c in new]
            row["input_tokens"] = next((c.input_tokens for c in new if c.status == "ok"), None)
            row["tools_sha256_sent"] = next((c.request_params.get("tools_sha256") for c in new), None)
            rows.append(row)
            (out_dir / "results.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
    fidelity = {"tools_sent_equal_original_request": all(r.get("tools_sha256_sent") == manifest["tools_sha256"][r["case"]]
                                                         for r in rows if r["status"] == "done"),
                "A_input_tokens_minus_original": {r["case"]: (r["input_tokens"] - manifest["original_input_tokens"][r["case"]])
                                                  if r.get("input_tokens") is not None else None
                                                  for r in rows if r["status"] == "done" and r["arm"] == "A_v1_text"}}
    summary = {"batch_id": plan["batch_id"], "finished_at": datetime.now(timezone.utc).isoformat(),
               "by_status": {st: sum(r["status"] == st for r in rows) for st in {r["status"] for r in rows}},
               "fidelity": fidelity,
               "labels": summarize(rows), "spend": budget.summary(), "results": rows}
    (a.out_dir / f"{plan['batch_id']}_results.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps({k: summary[k] for k in ("by_status", "fidelity", "labels", "spend")}, indent=2, default=str))
    return 3 if any(r["status"] != "done" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
