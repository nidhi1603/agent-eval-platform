"""The baseline agent and the boundary that controls what it may see.

tau2's build_agent() passes `task=` (which contains the reference actions) to every agent
factory, and the banking environment receives the task too. This module makes the agent's inputs
an explicit allowlist and provides checks that no task-only information reached them.
"""

import json
import re
from copy import deepcopy

AGENT_NAME = "aep_baseline"

# Everything the agent may be constructed from. tools and domain_policy are positional.
ALLOWED_AGENT_INPUTS = ("tools", "domain_policy", "llm", "llm_args")

# Retrieval configs whose policy is independent of the task. golden_retrieval inlines each task's
# required documents into the prompt: an oracle condition, never usable for a result.
FORBIDDEN_RETRIEVAL_CONFIGS = {"golden_retrieval"}

# Filled by the factory on each build, read by the runner for the trace.
last_build: dict = {}


def factory(tools, domain_policy, variant: str = "baseline", guard_rules: tuple = (), nudges: tuple = (), **kwargs):
    """Registered with tau2. Builds the standard tau2 LLMAgent from allowlisted inputs only. A non-baseline
    variant appends its frozen instruction text (bench/variants/) to the domain policy; nothing else changes."""
    from tau2.agent.llm_agent import LLMAgent

    from bench import variants

    received = sorted(["tools", "domain_policy", *kwargs])
    last_build.clear()
    last_build.update({
        "allowlist": list(ALLOWED_AGENT_INPUTS),
        "received": received,
        "withheld": [k for k in received if k not in ALLOWED_AGENT_INPUTS],
        "variant": variants.record(variant),
        "guard_rules": list(guard_rules),
        "nudges": list(nudges),
    })
    cls = LLMAgent
    if guard_rules or nudges:
        from bench import guard

        cls = guard.make_guarded_agent_class()
    built = cls(tools=tools, domain_policy=variants.apply(domain_policy, variant), llm=kwargs["llm"],
                llm_args=deepcopy(kwargs.get("llm_args") or {}))
    if guard_rules or nudges:
        built.guard_rules = tuple(guard_rules)
        built.harness_nudges = tuple(nudges)  # toolkit (and db, if needed) are attached once the environment exists
    return built


def register(variant: str = "baseline", guard_rules: tuple = (), nudges: tuple = ()) -> str:
    """Register the factory for one variant (and optional proposal-time guard) with tau2; return its name."""
    from functools import partial

    from tau2.registry import registry

    from bench import variants

    from bench import guard, nudge

    variants.text(variant)  # unknown variants fail here, before anything is built
    unknown = set(guard_rules) - set(guard.RULES)
    if unknown:
        raise ValueError(f"unknown guard rules {sorted(unknown)}; available: {list(guard.RULES)}")
    if set(nudges) - set(nudge.NUDGES):
        raise ValueError(f"unknown nudges {sorted(set(nudges) - set(nudge.NUDGES))}; available: {list(nudge.NUDGES)}")
    name = AGENT_NAME if variant == variants.BASELINE else f"aep_{variant}"
    if guard_rules:
        name += "_guarded_" + "_".join(sorted(guard_rules))
    if nudges:
        name += "_nudged_" + "_".join(sorted(nudges))
    if name not in registry.get_agents():
        registry.register_agent_factory(partial(factory, variant=variant, guard_rules=tuple(sorted(guard_rules)),
                                                nudges=tuple(sorted(nudges))), name)
    return name


def forbidden_strings(task) -> dict[str, set[str]]:
    """Task fields the agent must never receive as input, as strings to search for."""
    out: dict[str, set[str]] = {"task_id": {task.id}, "required_documents": set(task.required_documents or [])}
    ec = task.evaluation_criteria
    refs: set[str] = set()
    for action in (ec.actions or []) if ec else []:
        refs.add(action.action_id)
        for value in _leaf_strings(action.arguments or {}):
            if len(value) >= 6:
                refs.add(value)
    out["reference_actions"] = refs
    out["nl_assertions"] = set(ec.nl_assertions or []) if ec else set()
    return out


def _leaf_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaf_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaf_strings(v)
    elif isinstance(obj, str):
        try:
            parsed = json.loads(obj)  # some reference arguments are JSON-encoded strings
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from _leaf_strings(parsed)
        else:
            yield obj


def _shingles(text: str, n: int = 8) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def leakage_check(task, agent_visible_text: str) -> dict:
    """Search everything the agent receives before the conversation for hidden task content.

    Exact strings: task id, required document ids, reference action ids and argument values,
    NL assertions. Fuzzy: any 8-word run shared with the hidden user instructions or task notes.
    """
    findings = []
    for field, values in forbidden_strings(task).items():
        for v in sorted(values):
            if v and v in agent_visible_text:
                findings.append({"field": field, "match": v})
    hidden_text = str(task.user_scenario) + " " + str(task.description.notes if task.description else "")
    for s in sorted(_shingles(hidden_text) & _shingles(agent_visible_text)):
        findings.append({"field": "user_instructions_or_notes", "match": s})
    return {"passed": not findings, "findings": findings[:20]}


TASK_SEARCH_DEPTH = 4


def task_references(obj, task_cls, depth: int = 0, seen=None) -> list[str]:
    """Paths to Task objects found by a bounded search (depth 4) of the agent's attributes, lists
    and dicts. It does not inspect closures, globals or C-level state, so an empty result means
    "none found by this search", not "none reachable". The factory allowlist is the real safeguard."""
    seen = seen if seen is not None else set()
    if depth > TASK_SEARCH_DEPTH or id(obj) in seen:
        return []
    seen.add(id(obj))
    if isinstance(obj, task_cls):
        return ["<task>"]
    children = {}
    if isinstance(obj, dict):
        children = {str(k): v for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        children = {str(i): v for i, v in enumerate(obj)}
    elif hasattr(obj, "__dict__") and not isinstance(obj, type):
        children = vars(obj)
    found = []
    for name, child in children.items():
        found += [f"{name}.{p}" for p in task_references(child, task_cls, depth + 1, seen)]
    return found
