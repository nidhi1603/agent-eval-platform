"""Differential check: did anything the agent saw depend on hidden reference data?

Replays a trajectory's tool calls, in order and with identical arguments, against three fresh
environments built through tau2's official path (`_build_env_kwargs`):
  real     from the real task
  control  from the real task again (measures nondeterminism)
  blind    from a copy whose grading-only fields (reference actions, NL assertions, communicate
           info, required documents) are emptied
Legitimate inputs (initial state, retrieval config, tool arguments) are identical in all three.
An agent-visible output that is stable (real == control) but differs from blind depends on the
answer key. If any output differs between real and control, the check is inconclusive: random
variation could hide answer dependence.

Known volatile content is normalized before comparing, and the list is recorded in the result: the
KB search tools end their output with a wall-clock "[Timing: ...]" footer. Only that trailing footer,
and only for those tools, is normalized.

Scope: only the calls this trajectory made. It cannot show that other calls are answer-independent.
"""

import re

from bench import pins

SEARCH_TOOLS = {"KB_search", "KB_search_bm25", "KB_search_dense"}
# Exact footer format from tau2 domains/banking_knowledge/retrieval_mixins.py:_format_kb_search_result
TIMING_FOOTER = re.compile(r"\[Timing: retrieval=\d+ms(?:, reranking=\d+ms)?, total=\d+ms\]\s*\Z")
NORMALIZERS = ["kb_search_timing_footer"]


def normalize(tool: str, text: str | None) -> str:
    text = text or ""
    return TIMING_FOOTER.sub("[Timing: <normalized>]", text) if tool in SEARCH_TOOLS else text


def blind_copy(task):
    blind = task.model_copy(deep=True)
    if blind.evaluation_criteria is not None:
        blind.evaluation_criteria = blind.evaluation_criteria.model_copy(
            update={"actions": [], "nl_assertions": None, "communicate_info": []})
    blind.required_documents = []
    return blind


def fresh_env(config, task):
    from tau2.runner.build import _build_env_kwargs, build_environment

    env = build_environment(pins.DOMAIN, env_kwargs=_build_env_kwargs(config, task))
    init = task.initial_state
    env.set_state(
        initialization_data=init.initialization_data if init else None,
        initialization_actions=init.initialization_actions if init else None,
        message_history=[],
    )
    return env


def check(config, task, messages) -> dict:
    envs = {"real": fresh_env(config, task), "control": fresh_env(config, task),
            "blind": fresh_env(config, blind_copy(task))}
    recorded = {m.id: m.content for m in messages if m.role == "tool"}
    dependent, nondeterministic, mismatched, replayed = [], [], [], 0
    for i, m in enumerate(messages):
        if m.role not in ("assistant", "user"):
            continue
        for tc in m.tool_calls or []:
            out = {name: normalize(tc.name, env.get_response(tc).content) for name, env in envs.items()}
            replayed += 1
            if out["real"] != out["control"]:
                nondeterministic.append({"message_i": i, "tool": tc.name})
            elif m.role == "assistant" and out["real"] != out["blind"]:
                dependent.append({"message_i": i, "tool": tc.name, "arguments": tc.arguments,
                                  "real": out["real"][:300], "blind": out["blind"][:300]})
            if tc.id in recorded and out["real"] != normalize(tc.name, recorded[tc.id]):
                mismatched.append({"message_i": i, "tool": tc.name})
    return {
        "method": "replay tool calls against real, control (real again) and answer-key-emptied environments",
        "normalized": NORMALIZERS,
        "conclusive": not nondeterministic,
        "calls_replayed": replayed,
        "agent_visible_outputs_depending_on_hidden_reference": dependent,
        "nondeterministic_outputs": nondeterministic,
        "replay_matches_recorded": not mismatched,
        "replay_mismatches": mismatched[:10],
    }


def check_sequence(config, task, steps: list[dict]) -> dict:
    """The same differential check for an explicit sequence of tool calls, e.g. a saved prefix followed by a
    continuation. Each step is {"requestor", "name", "arguments", "checked"}; every step is replayed (to reach
    the same states) and only steps with checked=True are compared for answer dependence."""
    from tau2.data_model.message import ToolCall

    envs = {"real": fresh_env(config, task), "control": fresh_env(config, task),
            "blind": fresh_env(config, blind_copy(task))}
    dependent, nondeterministic = [], []
    for k, st in enumerate(steps):
        tc = ToolCall(id=f"seq_{k}", name=st["name"], arguments=st["arguments"], requestor=st["requestor"])
        out = {name: normalize(tc.name, env.get_response(tc).content) for name, env in envs.items()}
        if not st.get("checked"):
            continue
        if out["real"] != out["control"]:
            nondeterministic.append({"step": k, "tool": tc.name})
        elif st["requestor"] == "assistant" and out["real"] != out["blind"]:
            dependent.append({"step": k, "tool": tc.name, "real": out["real"][:300], "blind": out["blind"][:300]})
    return {"method": "replay the full sequence against real, control and answer-key-emptied environments",
            "normalized": NORMALIZERS, "steps_checked": sum(bool(s.get("checked")) for s in steps),
            "conclusive": not nondeterministic,
            "agent_visible_outputs_depending_on_hidden_reference": dependent,
            "nondeterministic_outputs": nondeterministic}


def recheck(run_dir) -> dict:
    """Rerun the check from a saved run (simulation.json + trace.json), without a new conversation."""
    import json
    from pathlib import Path

    from tau2.data_model.simulation import SimulationRun, TextRunConfig
    from tau2.runner.helpers import get_tasks

    run_dir = Path(run_dir)
    trace = json.loads((run_dir / "trace.json").read_text())
    sim = SimulationRun.model_validate_json((run_dir / "simulation.json").read_text())
    cfg = trace["config"]
    config = TextRunConfig(domain=pins.DOMAIN, retrieval_config=cfg["retrieval_config"])
    task = get_tasks(pins.DOMAIN, task_ids=[cfg["task_id"]])[0]
    return check(config, task, sim.messages)


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(recheck(sys.argv[1]), indent=2))
