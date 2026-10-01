"""P002's summary rule is exhaustive and ordered (research/p002/verdict.py). $0."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("p002_verdict", Path(__file__).resolve().parents[1] / "research" / "p002" / "verdict.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
v = _mod


def rows(n=8, **kv):
    base = {"finished": True, "runtime_matches_record": True, "resume_checks_ok": True, "audit_complete": True,
            "covered_after_resume": 0, "false_blocks": 0, "identity_interventions_after_resume": 0, "recovery": "success"}
    out = [{**base, "case": f"c{i}"} for i in range(n)]
    out[0].update(kv)
    return out


def test_order_and_exhaustiveness():
    assert v.verdict(rows(audit_complete=False, covered_after_resume=1))[0] == "INCOMPLETE"
    assert v.verdict([])[0] == "INCOMPLETE"
    assert v.verdict(rows(covered_after_resume=1))[0] == "RECOVERY_PROBLEM"
    assert v.verdict(rows(false_blocks=1))[0] == "RECOVERY_PROBLEM"
    assert v.verdict(rows(identity_interventions_after_resume=3))[0] == "RECOVERY_PROBLEM"
    for cause in v.NON_RECOVERY[1:]:
        assert v.verdict(rows(recovery=cause))[0] == "RECOVERY_PROBLEM"
    assert v.verdict(rows(recovery="customer_lacked_information"))[0] == "RECOVERY_DEMONSTRATED"
    assert v.verdict([{**r, "recovery": "customer_lacked_information"} for r in rows()])[0] == "NO_SUCCESS_EXPLAINED"


def test_every_reason_leads_with_the_recovery_count_and_bounded_stalls_are_problems():
    r = rows(recovery="bounded_no_recovery_other")
    assert v.verdict(r)[0] == "RECOVERY_PROBLEM" and v.verdict(r)[1].startswith("7 of 8 selected continuations recovered")
    assert v.verdict(rows())[1].startswith("8 of 8 selected continuations recovered")
