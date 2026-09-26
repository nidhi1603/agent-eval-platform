"""Differential check: did anything the agent saw depend on hidden reference data?

Replays a trajectory's tool calls, in order and with identical arguments, against three fresh
environments built through tau2's official path (`_build_env_kwargs`):
  real     from the real task
  control  from the real task again (measures nondeterminism)
  blind    from a copy whose grading-only fields (reference actions, NL assertions, communicate
           info, required documents) are emptied
Legitimate inputs (initial state, retrieval config, tool arguments) are identical in all three.
An agent-visible output that is stable (real == control) but differs from blind depends on the
answer key. Outputs that differ between real and control are reported as nondeterministic.

Known volatile content is normalized before comparing, and the list is recorded in the result:
KB search results end with a wall-clock "[Timing: ...]" line.

Scope: only the calls this trajectory made. It cannot show that other calls are answer-independent.
"""

import re

from bench import pins

NORMALIZERS = {"kb_search_timing": (re.compile(r"\[Timing:[^\]]*\]"), "[Timing: <normalized>]")}


def normalize(text: str | None) -> str:
    text = text or ""
    for pattern, repl in NORMALIZERS.values():
        text = pattern.sub(repl, text)
    return text


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
            out = {name: normalize(env.get_response(tc).content) for name, env in envs.items()}
            replayed += 1
            if out["real"] != out["control"]:
                nondeterministic.append({"message_i": i, "tool": tc.name})
            elif m.role == "assistant" and out["real"] != out["blind"]:
                dependent.append({"message_i": i, "tool": tc.name, "arguments": tc.arguments,
                                  "real": out["real"][:300], "blind": out["blind"][:300]})
            if tc.id in recorded and out["real"] != normalize(recorded[tc.id]):
                mismatched.append({"message_i": i, "tool": tc.name})
    return {
        "method": "replay tool calls against real, control (real again) and answer-key-emptied environments",
        "normalized": sorted(NORMALIZERS),
        "calls_replayed": replayed,
        "agent_visible_outputs_depending_on_hidden_reference": dependent,
        "nondeterministic_outputs": nondeterministic,
        "replay_matches_recorded": not mismatched,
        "replay_mismatches": mismatched[:10],
    }
