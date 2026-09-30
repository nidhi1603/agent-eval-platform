"""Direct-tool adapter: presents discovered agent tools to the model as ordinary callable functions.

The benchmark's interface makes the model do two indirect steps for every discoverable tool:

    unlock_discoverable_agent_tool("get_all_user_accounts_by_user_id_3847")
    call_discoverable_agent_tool("get_all_user_accounts_by_user_id_3847", '{"user_id": "..."}')

In the saved failures the model saw the needed tool name and did not take those steps (T001). This adapter changes
only that interface, so the hypothesis can be tested:

    Does presenting retrieved tools as directly callable functions improve correct task execution compared with
    requiring the model to unlock and invoke them through wrappers?

What the adapter does, and the rules it keeps:
1. **Only names the agent has received.** It scans the output of successful retrieval calls in the agent's own
   conversation (KB_search, or under alltools KB_search_bm25 / KB_search_dense / shell; bench/kb_evidence.py) for
   discoverable AGENT-tool names from the benchmark's registry. A shell command's own text never counts. Customer tools (give_discoverable_user_tool) are
   never offered as agent functions; that path is unchanged.
2. **Schemas through the permitted interface.** For each newly seen name the adapter issues the benchmark's own
   unlock call (a harness turn, no model call). Only after a successful unlock receipt is the tool offered, with
   the benchmark's own definition; its parameters are identical to the unlock text (checked for all 44 tools).
   Unlocking is in-memory in tau2 (the database is written only when a tool is called), so it does not change
   grading; a scripted probe confirmed an unchanged reward.
3. **Original execution preserved.** When the model calls an offered tool directly, the adapter sends the
   benchmark's standard `call_discoverable_agent_tool` wrapper with the same arguments and the same call id. The
   environment, receipts and grading records see exactly the calls a model using the wrappers would make.
4. **Availability is not authorization.** Offering a tool makes it callable, nothing more: no policy is added or
   removed, and the instructions are unchanged.

Two views are kept. The model's own history (`state.messages`) holds its direct calls and their results and never
contains the harness unlock turns. The trajectory the benchmark records holds the unlock and wrapper calls.
Every harness action is logged in `adapter_events`.
"""

from __future__ import annotations

import json
import re

WORD = re.compile(r"\b[a-z][a-z0-9_]*_\d{4}\b")
UNLOCK, CALL, KB = "unlock_discoverable_agent_tool", "call_discoverable_agent_tool", "KB_search"
ADAPTER_NAME = "direct_tools"


def names_in_kb_results(messages, agent_tool_names) -> set[str]:
    """Discoverable agent-tool names in the output of successful retrieval calls in this conversation (model-view
    messages). KB_search behaves exactly as before; the alltools search tools and shell output count the same way."""
    from bench.kb_evidence import RETRIEVAL_TOOLS, SHELL, succeeded

    call_names = {tc.id: tc.name for m in messages if getattr(m, "role", None) == "assistant"
                  for tc in (getattr(m, "tool_calls", None) or [])}
    found: set[str] = set()
    for m in messages:
        name = call_names.get(getattr(m, "id", None)) if getattr(m, "role", None) == "tool" else None
        if name in RETRIEVAL_TOOLS and not m.error:
            text = m.content or ""
            if name == SHELL and not succeeded({"content": text}):
                continue
            if not text.lstrip().startswith("Error"):
                found |= set(WORD.findall(text)) & set(agent_tool_names)
    return found


def make_direct_tools_agent_class():
    import tau2.agent.llm_agent as llm_agent_module
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall
    from tau2.environment.tool import as_tool

    class DirectToolsAgent(LLMAgent):
        """tau2's LLMAgent with the direct-tool adapter (see the module docstring). The runner sets
        `adapter_toolkit` (the environment's toolkit: static tool definitions) and `agent_tool_names`."""

        adapter_toolkit = None
        agent_tool_names: frozenset = frozenset()

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.adapter_events: list[dict] = []
            self.offered: dict = {}          # name -> tau2 Tool, offered after a successful unlock receipt
            self._pending: dict = {}         # harness unlock call id -> tool name
            self._failed: set[str] = set()   # names whose unlock failed; never retried
            self._n = 0

        # ---- incoming messages ----------------------------------------------------------------------
        def _absorb(self, message, state) -> None:
            """Harness unlock receipts are consumed here; everything else enters the model's history."""
            incoming = message.tool_messages if isinstance(message, MultiToolMessage) else [message]
            for m in incoming:
                name = self._pending.pop(getattr(m, "id", None), None) if getattr(m, "role", None) == "tool" else None
                if name is None:
                    state.messages.append(m)
                    continue
                ok = not m.error and (m.content or "").startswith("Tool unlocked:")
                if ok:
                    self.offered[name] = as_tool(self.adapter_toolkit.tools[name])
                else:
                    self._failed.add(name)
                self.adapter_events.append({"event": "unlocked" if ok else "unlock_failed", "tool": name,
                                            "receipt": (m.content or "")[:200]})

        def _unlock_turn(self, state):
            """A harness turn that unlocks newly seen names; no model call. None if there is nothing new."""
            if self.adapter_toolkit is None:
                raise RuntimeError("DirectToolsAgent needs adapter_toolkit (the environment's toolkit)")
            seen = names_in_kb_results(state.messages, self.agent_tool_names)
            new = sorted(seen - set(self.offered) - set(self._pending.values()) - self._failed)
            if not new:
                return None
            calls = []
            for name in new:
                self._n += 1
                cid = f"adapter_unlock_{self._n}"
                self._pending[cid] = name
                calls.append(ToolCall(id=cid, name=UNLOCK, arguments={"agent_tool_name": name}, requestor="assistant"))
            self.adapter_events.append({"event": "unlock_turn", "tools": new})
            return AssistantMessage(role="assistant", content=None, tool_calls=calls)

        def _translate(self, proposal):
            """The model's direct calls to offered tools -> the benchmark's wrapper, same arguments and call id."""
            if not proposal.tool_calls:
                return proposal
            out, translated = [], []
            for tc in proposal.tool_calls:
                if tc.name in self.offered:
                    out.append(ToolCall(id=tc.id, name=CALL, requestor="assistant", arguments={
                        "agent_tool_name": tc.name, "arguments": json.dumps(tc.arguments or {})}))
                    translated.append(tc.name)
                else:
                    out.append(tc)
            if translated:
                self.adapter_events.append({"event": "direct_call_translated", "tools": translated})
            return proposal.model_copy(update={"tool_calls": out})

        # ---- tau2 agent interface -------------------------------------------------------------------
        def generate_next_message(self, message, state):
            self._absorb(message, state)
            harness = self._unlock_turn(state)
            if harness is not None:
                return harness, state  # not added to the model's history
            tools = list(self.tools) + [t for n, t in sorted(self.offered.items())
                                        if n not in {x.name for x in self.tools}]
            # llm_agent's own `generate`, looked up at call time, so the budget meters and tags it as "agent"
            proposal = llm_agent_module.generate(model=self.llm, tools=tools,
                                                 messages=state.system_messages + state.messages,
                                                 call_name="agent_response", **self.llm_args)
            state.messages.append(proposal)  # the model's view keeps its direct calls
            return self._translate(proposal), state

    return DirectToolsAgent
