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


def factory(tools, domain_policy, variant: str = "baseline", guard_rules: tuple = (), nudges: tuple = (),
            evidence_mode: str | None = None, tool_adapter: str | None = None, harness: dict | None = None, **kwargs):
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
        "evidence_mode": evidence_mode,
        "tool_adapter": tool_adapter,
        "harness": harness_record(harness),
    })
    if evidence_mode not in (None, "record", "enforce"):
        raise ValueError(f"evidence_mode must be None, 'record' or 'enforce', not {evidence_mode!r}")
    guarded = bool(guard_rules or nudges or evidence_mode)
    if tool_adapter not in (None, "direct_tools"):
        raise ValueError(f"tool_adapter must be None or 'direct_tools', not {tool_adapter!r}")
    if tool_adapter and guarded:
        raise ValueError("the direct-tool adapter is tested on its own: do not combine it with guards, nudges or "
                         "the evidence check, or a change in results could not be attributed")
    if harness is not None:
        if guarded or tool_adapter or variant != variants.BASELINE:
            raise ValueError("harness v1 is one system: it already contains the adapter and its checks; do not combine "
                             "it with guards, nudges, the evidence check, a separate adapter or an instruction variant")
        harness_record(harness)  # validates
    cls = LLMAgent
    if harness is not None:
        from bench import harness as harness_mod

        cls = harness_mod.make_harness_agent_class()
    elif tool_adapter:
        from bench import adapter

        cls = adapter.make_direct_tools_agent_class()
    elif guarded:
        from bench import guard

        cls = guard.make_guarded_agent_class()
    built = cls(tools=tools, domain_policy=variants.apply(domain_policy, variant), llm=kwargs["llm"],
                llm_args=deepcopy(kwargs.get("llm_args") or {}))
    if harness is not None:
        spec = harness_record(harness)
        built.gates, built.feedback, built.use_adapter = tuple(spec["gates"]), spec["feedback"], spec["adapter"]
        built.dep_search = bool(spec.get("dep_search"))
        built.capability_search = bool(spec.get("capability_search"))
        built.transfer_hold_once = bool(spec.get("transfer_hold_once"))
        built.auto_offer = spec.get("auto_offer", "all")
        built.expose_model_unlocks = bool(spec.get("expose_model_unlocks"))
    if guarded:
        built.guard_rules = tuple(guard_rules)
        built.harness_nudges = tuple(nudges)  # toolkit (and db, if needed) are attached once the environment exists
        built.evidence_mode = evidence_mode
    return built


def harness_record(harness: dict | None) -> dict | None:
    """The validated harness spec: {"gates": [...], "feedback": "structured"|"generic"|"block", "adapter": bool,
    "dep_search": bool (recorded only when true)}.
    Missing keys take the v1 defaults (all gates, structured feedback, adapter on)."""
    if harness is None:
        return None
    from bench import harness as harness_mod

    unknown = set(harness) - {"name", "version", "gates", "feedback", "adapter", "dep_search", "capability_search",
                              "transfer_hold_once", "auto_offer", "expose_model_unlocks"}
    if unknown:
        raise ValueError(f"unknown harness settings {sorted(unknown)}")
    version = harness.get("version", "v1")  # v1 is what H001 froze; v2 adds the ledger checks (bench/ledger.py)
    if version not in harness_mod.VERSIONS:
        raise ValueError(f"harness version must be one of {list(harness_mod.VERSIONS)}, not {version!r}")
    gates = list(harness.get("gates", harness_mod.VERSIONS[version]))
    if set(gates) - set(harness_mod.ALL_GATES):
        raise ValueError(f"unknown harness gates {sorted(set(gates) - set(harness_mod.ALL_GATES))}; "
                         f"available: {list(harness_mod.ALL_GATES)}")
    feedback = harness.get("feedback", "structured")
    if feedback not in harness_mod.FEEDBACK_MODES:
        raise ValueError(f"harness feedback must be one of {harness_mod.FEEDBACK_MODES}, not {feedback!r}")
    out = {"name": f"harness_{version}", "gates": [g for g in harness_mod.ALL_GATES if g in gates],
           "feedback": feedback, "adapter": bool(harness.get("adapter", True))}
    if version != "v1":  # v1 records keep their original shape
        out["version"] = version
    if version in ("v3", "v3.1"):  # v1's checks plus capability search (bench/capability.py)
        if not out["adapter"]:
            raise ValueError(f"{version} needs the adapter: the tools its searches find are offered through it")
        out["capability_search"] = True
    if version == "v3.1":  # and a transfer is held at most once, with explicit feedback (research/v3_1/README.md)
        out["transfer_hold_once"] = True
    if harness.get("auto_offer", "all") != "all":  # H009: the adapter offers only non-mutating tools
        if harness["auto_offer"] != "non_mutating":
            raise ValueError(f"auto_offer must be 'all' or 'non_mutating', not {harness['auto_offer']!r}")
        if not out["adapter"]:
            raise ValueError("auto_offer needs the adapter")
        out["auto_offer"] = "non_mutating"
    if harness.get("expose_model_unlocks"):  # H009: tools the model unlocks itself are offered directly too
        if not out["adapter"]:
            raise ValueError("expose_model_unlocks needs the adapter")
        out["expose_model_unlocks"] = True
    if harness.get("dep_search"):  # dependency-following tool search (bench/depsearch.py); absent = off
        if not out["adapter"]:
            raise ValueError("dep_search needs the adapter: the documents it adds are offered through it")
        out["dep_search"] = True
    return out


def register(variant: str = "baseline", guard_rules: tuple = (), nudges: tuple = (), tool_adapter: str | None = None,
             harness: dict | None = None) -> str:
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
    if tool_adapter:
        name += "_" + tool_adapter
    spec = harness_record(harness)
    if spec:
        from bench import harness as harness_mod

        name += "_" + spec["name"]
        if spec["feedback"] != "structured":
            name += "_fb-" + spec["feedback"]
        if not spec["adapter"]:
            name += "_no-adapter"
        if spec.get("dep_search"):
            name += "_dep-search"
        if spec.get("auto_offer") == "non_mutating":
            name += "_offer-nonmutating"
        if spec.get("expose_model_unlocks"):
            name += "_expose-unlocks"
        dropped = [g for g in harness_mod.VERSIONS[spec.get("version", "v1")] if g not in spec["gates"]]
        if dropped:
            name += "_without-" + "-".join(dropped)
    if name not in registry.get_agents():
        registry.register_agent_factory(partial(factory, variant=variant, guard_rules=tuple(sorted(guard_rules)),
                                                nudges=tuple(sorted(nudges)), tool_adapter=tool_adapter,
                                                harness=spec), name)
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
