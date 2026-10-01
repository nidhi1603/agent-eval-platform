"""P001's decision rule is exhaustive and ordered (research/p001/verdict.py). $0."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("p001_verdict", Path(__file__).resolve().parents[1] / "research" / "p001" / "verdict.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
verdict = _mod.verdict

TASKS = ("task_019", "task_023", "task_077", "task_087", "task_095", "task_012")


def rows():
    base = {"finished": True, "runtime_matches_record": True, "audit_complete": True, "valid_verification": True,
            "covered_disclosures_delivered": 0, "interventions": 0, "apology_dead_end": False, "recovery": None}
    out = [{**base, "task_id": t, "arm": "v3_2"} for t in TASKS]
    out += [{**base, "task_id": t, "arm": "v3_2_disclosure"} for t in TASKS]
    return out


def with_treat(rs, task, **kv):
    for r in rs:
        if r["task_id"] == task and r["arm"] == "v3_2_disclosure":
            r.update(kv)
    return rs


def test_incomplete_first():
    rs = rows(); rs[0]["runtime_matches_record"] = False
    assert verdict(rs)[0] == "INCOMPLETE"
    rs = with_treat(rows(), "task_019", audit_complete=False, covered_disclosures_delivered=1)
    assert verdict(rs)[0] == "INCOMPLETE"


def test_revise_on_a_delivered_covered_disclosure_or_loop_or_dead_end():
    assert verdict(with_treat(rows(), "task_019", covered_disclosures_delivered=1))[0] == "REVISE"
    assert verdict(with_treat(rows(), "task_019", interventions=3, recovery="success"))[0] == "REVISE"
    rs = with_treat(rows(), "task_019", interventions=1, apology_dead_end=True, valid_verification=False,
                    recovery="customer_lacked_information")
    assert verdict(rs)[0] == "REVISE"


def test_revise_when_treatment_verifications_fall_below_control_minus_one():
    rs = with_treat(with_treat(rows(), "task_087", valid_verification=False), "task_095", valid_verification=False)
    assert verdict(rs)[0] == "REVISE"
    assert verdict(with_treat(rows(), "task_087", valid_verification=False))[0] == "INCONCLUSIVE_ON_RECOVERY"


def test_inconclusive_without_intervention_or_with_only_genuine_inability():
    assert verdict(rows())[0] == "INCONCLUSIVE_ON_RECOVERY"
    rs = with_treat(rows(), "task_019", interventions=1, recovery="customer_lacked_information")
    assert verdict(rs)[0] == "INCONCLUSIVE_ON_RECOVERY"


def test_unexplained_failure_after_intervention_is_revise_not_inability():
    for cause in ("compromised_by_earlier_disclosure", "checker_rejected_valid_evidence",
                  "agent_did_not_request_usable_evidence"):
        rs = with_treat(rows(), "task_019", interventions=1, recovery=cause)
        rs = with_treat(rs, "task_023", interventions=1, recovery="success")
        assert verdict(rs)[0] == "REVISE"


def test_proceed_needs_at_least_one_successful_recovery():
    rs = with_treat(rows(), "task_019", interventions=2, recovery="success")
    rs = with_treat(rs, "task_023", interventions=1, recovery="customer_lacked_information")
    assert verdict(rs)[0] == "PROCEED"
