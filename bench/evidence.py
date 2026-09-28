"""Argument-evidence check for write proposals (offline; not wired into any run yet).

Question it answers for one proposed call: is every identifier and amount in the arguments backed by evidence the
agent actually received? It does NOT decide whether the action is permitted or the amount is what policy intends:
a correctly derived amount from conflicting documents passes, flagged `policy_applicability_not_checked`.

Three kinds of value, three kinds of evidence (tech-lead review of 6d42140):
- **Identifier** (`*_id`): an exact field value in a record from a successful tool result, owned by the verified
  customer (directly, or through an owned account/card). Seen only in an error message, or nowhere, is not
  evidence; a valid identifier of another customer is not evidence for this customer.
- **Directly supplied amount:** exact numeric equality (not substring) with a money/points field of an owned
  record. Recorded as `record_field`; the field's purpose is not verified.
- **Calculated amount:** a `Calculation: <expression> = <result>` line in the same draft. The expression must
  evaluate to the result and to the argument, and every operand must appear as a number in received evidence
  (tool results or the customer's words), apart from unit constants.

Only numbers are compared as numbers, so "100.0" no longer matches inside "2100.00" (D001 run 01).
"""

from __future__ import annotations

import ast
import json
import operator
import re
from pathlib import Path
from dataclasses import dataclass, field

from bench.continuation import receipt_ok
from bench.guard import VERIFIED, Evidence, target

ID_KEY = re.compile(r"(^|_)id$")
MONEY_FIELD = re.compile(r"amount|balance|holdings|fee|credit|points|rewards|limit|interest", re.I)
NUMBER = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?")
AMOUNT_VALUE = re.compile(r"^\s*\$?(-?\d[\d,]*(?:\.\d+)?)\s*(?:points?|pts|usd|dollars)?\s*$", re.I)
CALCULATION = re.compile(r"Calculation:\s*(?P<expr>[^=\n]+?)\s*=\s*\$?(?P<result>-?\d[\d,]*(?:\.\d+)?)", re.I)
RECORD_SPLIT = re.compile(r"\n\s*\d+\.\s+Record ID:")
FIELD_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.+?)\s*$")
UNIT_CONSTANTS = {1.0, 12.0, 100.0, 365.0}
OWNER_LINKS = ("account_id", "credit_card_account_id", "card_id")
CENT = 0.005


@dataclass
class Assessment:
    allowed: bool
    findings: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _num(text) -> float | None:
    try:
        return float(str(text).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def numbers_in(text: str) -> set[float]:
    return {n for n in (_num(t) for t in NUMBER.findall(text or "")) if n is not None}


def records(content: str) -> list[dict]:
    """Structured records in a tool result: JSON objects, or tau2's 'N. Record ID:' blocks of `key: value` lines."""
    text = (content or "").strip()
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else [data]
        return [{k: str(v) for k, v in i.items() if not isinstance(v, (dict, list))} for i in items
                if isinstance(i, dict)]
    except (json.JSONDecodeError, TypeError):
        pass
    out = []
    for block in RECORD_SPLIT.split("\n" + text)[1:]:
        rec = {}
        for line in block.splitlines():
            m = FIELD_LINE.match(line)
            if m:
                rec.setdefault(m.group(1), m.group(2))
        if rec:
            out.append(rec)
    return out


def verified_customer(ev: Evidence) -> str | None:
    """user_id of the latest successful log_verification (the log prerequisite's own limits apply)."""
    who = None
    for c, r in ev.results():
        if c["name"] == "log_verification" and not r.get("error") and VERIFIED in (r.get("content") or ""):
            who = (c.get("arguments") or {}).get("user_id") or who
    return who


def _successful_records(ev: Evidence) -> list[dict]:
    out = []
    for c, r in ev.results():
        if not r.get("error") and receipt_ok(c["name"], r.get("content")):
            out.extend(records(r.get("content")))
    return out


def ownership(recs: list[dict], customer: str | None) -> tuple[set[str], dict[str, str]]:
    """(identifiers owned by `customer`, identifier -> owning user_id for every attributable record)."""
    owner_of: dict[str, str] = {}
    for _ in range(3):  # user -> account -> card/transaction
        for rec in recs:
            owner = rec.get("user_id") or next((owner_of[rec[k]] for k in OWNER_LINKS if rec.get(k) in owner_of), None)
            if owner:
                for k, v in rec.items():
                    if ID_KEY.search(k) or k == "Record ID":
                        owner_of.setdefault(v, owner)
    return {i for i, o in owner_of.items() if customer and o == customer}, owner_of


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError("unsupported expression")


def evaluate(expr: str) -> tuple[float, list[float]]:
    """Value of an arithmetic expression written by the agent, and its literal operands (before % scaling)."""
    s = (expr.replace("×", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
         .replace("$", "").replace(",", ""))
    s = re.sub(r"(?<=[\d)\s])x(?=[\s\d(])", "*", s)
    operands = [float(t) for t in re.findall(r"\d+(?:\.\d+)?", s)]
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    return _eval(ast.parse(s, mode="eval")), operands


def _derivation(value: float, draft_text: str, evidence_numbers: set[float]) -> dict:
    lines = list(CALCULATION.finditer(draft_text or ""))
    if not lines:
        return {"basis": None, "problem": "no Calculation line in the draft"}
    for m in lines:
        stated = _num(m.group("result"))
        if stated is None or abs(stated - value) > CENT:
            continue
        try:
            computed, operands = evaluate(m.group("expr"))
        except (ValueError, SyntaxError, ZeroDivisionError):
            return {"basis": None, "problem": f"calculation not parseable: {m.group(0)!r}"}
        if abs(computed - stated) > CENT:
            return {"basis": None, "problem": f"calculation evaluates to {computed:.2f}, not {stated:.2f}"}
        missing = [o for o in operands if o not in UNIT_CONSTANTS and o not in evidence_numbers]
        if missing:
            return {"basis": None, "problem": f"operands not in received evidence: {missing}"}
        return {"basis": "derivation", "expression": m.group(0)}
    return {"basis": None, "problem": "no Calculation line whose result equals the argument"}


def _leaves(args: dict, prefix=""):
    for k, v in (args or {}).items():
        if isinstance(v, dict):
            yield from _leaves(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", k, v


def check_arguments(tool_call, draft_text: str | None, ev: Evidence) -> Assessment:
    """Evidence for every identifier and amount in one proposed call (see the module docstring)."""
    name, args = target(tool_call)
    customer = verified_customer(ev)
    recs = _successful_records(ev)
    owned, owner_of = ownership(recs, customer)
    error_text = " ".join(r.get("content") or "" for c, r in ev.results()
                          if r.get("error") or not receipt_ok(c["name"], r.get("content")))
    received = " ".join([r.get("content") or "" for c, r in ev.results() if not r.get("error")] +
                        [m.get("content") or "" for m in ev.messages if m.get("role") == "user"])
    evidence_numbers = numbers_in(received)
    out = Assessment(True)
    for path, key, value in _leaves(args):
        if key == "agent_tool_name":
            continue
        if ID_KEY.search(key):
            v = str(value)
            if key == "user_id" and customer and v == customer:
                f = {"basis": "verified_customer"}
            elif v in owned:
                f = {"basis": "record", "owner": customer}
            elif v in owner_of:
                f = {"basis": None, "problem": f"identifier belongs to another customer ({owner_of[v]})"}
            elif v in error_text:
                f = {"basis": None, "problem": "identifier appears only in an error result"}
            elif customer is None:
                f = {"basis": None, "problem": "no verified customer to attribute the identifier to"}
            else:
                f = {"basis": None, "problem": "identifier not in any successful record"}
            out.findings.append({"arg": path, "kind": "id", "value": v, **f})
            continue
        m = AMOUNT_VALUE.match(str(value)) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None
        if not m:
            continue
        amount = _num(m.group(1))
        direct = [(i, k) for i, rec in enumerate(recs) for k, fv in rec.items()
                  if MONEY_FIELD.search(k) and _num(fv) is not None and abs(_num(fv) - amount) <= CENT
                  and any(rec.get(x) in owned for x in ("Record ID", "account_id", "transaction_id", "user_id"))]
        derived = _derivation(amount, draft_text, evidence_numbers)
        if derived["basis"]:
            f = derived
            out.flags.append("policy_applicability_not_checked")
        elif direct:
            i, k = direct[0]
            f = {"basis": "record_field", "field": k, "note": "exact value of an owned record's field; purpose not verified"}
        else:
            f = {"basis": None, "problem": derived["problem"] + "; no owned record field has this value"}
        out.findings.append({"arg": path, "kind": "amount", "value": amount, **f})
    out.allowed = all(f.get("basis") for f in out.findings)
    out.flags = sorted(set(out.flags))
    return out


# ---- offline replay over saved continuations ---------------------------------------------------------

def messages_before(trace_messages: list[dict], prefix_end: int, calls: list[dict], upto_round: int) -> list[dict]:
    """The agent's view just before proposal `upto_round` of a saved continuation: the frozen prefix plus every
    executed call (with its full result) from earlier rounds."""
    from bench.continuation import agent_visible

    msgs = list(agent_visible(trace_messages, prefix_end))
    for k, c in enumerate(x for x in calls if x["round"] <= upto_round):  # the call of proposal n has round n + 1
        cid = f"cont_{k}"
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": cid, "name": c["name"], "arguments": c["arguments"]}]})
        msgs.append({"role": "tool", "tool_call_id": cid, "content": c.get("result"), "error": bool(c.get("error_flag"))})
    return msgs


def audit_continuations(plan: dict, results: dict, tool_type) -> list[dict]:
    """Every write proposal in a batch of saved continuations, assessed as if proposed at that point."""
    from bench import REPO_ROOT

    cases = {c["id"]: c for c in plan["cases"]}
    rows = []
    for run in results["results"]:
        case = cases[run["case"]]
        trace = json.loads((REPO_ROOT / case["source_trace"]).read_text())["messages"]
        for p in run["proposals"]:
            for tc in p.get("tool_calls") or []:
                name, _ = target(tc)
                if tc["name"] == "unlock_discoverable_agent_tool" or tool_type(name) != "write":
                    continue
                ev = Evidence(messages=messages_before(trace, case["prefix_end"], run["calls"], p["n"]))
                a = check_arguments(tc, p.get("text"), ev)
                rows.append({"run": run["run"], "case": run["case"], "variant": run["variant"], "proposal": p["n"],
                             "tool": name, "executed": p.get("executed"), "would_allow": a.allowed,
                             "findings": a.findings, "flags": a.flags})
    return rows


def main(argv=None) -> int:
    """Offline: assess every write proposal in a saved batch. Writes <batch>_evidence_audit.json. No model calls."""
    import argparse

    from bench import REPO_ROOT
    from bench.guard import toolkit_type_lookup
    from bench.independence import fresh_env

    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("plan", type=Path)
    p.add_argument("results", type=Path)
    a = p.parse_args(argv)
    plan, results = json.loads(a.plan.read_text()), json.loads(a.results.read_text())
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.helpers import get_tasks

    env = fresh_env(TextRunConfig(domain="banking_knowledge", retrieval_config="bm25"),
                    get_tasks("banking_knowledge", task_ids=[plan["cases"][0]["task_id"]])[0])
    rows = audit_continuations(plan, results, toolkit_type_lookup(env.tools))
    out = REPO_ROOT / "experiments" / f"{plan['batch_id']}_evidence_audit.json"
    out.write_text(json.dumps({"method": "bench/evidence.check_arguments replayed at each write proposal; offline, "
                                         "post-run, not part of the frozen scores", "rows": rows}, indent=2) + "\n")
    print(f"{len(rows)} write proposals; would allow {sum(r['would_allow'] for r in rows)}; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
