"""Just-in-time procedure compiler for harness v2: retrieved document -> procedure card.

When the agent retrieves a document that names a discoverable tool, the harness compiles it into a card:
- the tools it names;
- the **requirements** listed for using them;
- the **steps** around the tool;
- any point where the customer must be asked, informed or must confirm.

Before the agent first calls one of those tools, the card is shown to it (`procedure_checklist` in bench/harness.py).
This is the "compile" step of retrieve -> compile -> track -> recover (docs/PHASE2_RESEARCH.md). The prior work
that compiles policy into checklists or graphs (PolicyGuide 2608.19861, STAGE 2608.22538) does it offline, from a
policy it is handed. Here only documents the agent itself retrieved in this conversation are compiled.

This is the deterministic ($0) compiler. It relies on the knowledge base's own structure: markdown sections such
as "## Freezing Requirements" and "## Freezing Steps", with numbered or bulleted items. Every item on a card is a
verbatim line of the document, so nothing is paraphrased or invented. Of the 698 documents, 46 name a
discoverable tool and 22 of those have a requirements-style section.
"""

import re
from dataclasses import dataclass, field

RESULT = re.compile(r"^\d+\.\s+(?P<title>.*)\n\s+ID:\s*(?P<id>doc_\S+)\n(?:\s+Score:.*\n)?\s+Content:\s?", re.M)
HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$", re.M)
ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+?)\s*$", re.M)
REQUIREMENT_HEADING = re.compile(r"requirement|eligib|prerequisite|condition|before|rule|restriction|must|only", re.I)
CUSTOMER_TOUCH = re.compile(r"\b(ask|confirm with|confirmation|agree|consent|inform|explain to|tell) (the )?customer\b|"
                            r"\bcustomer (must|should) (confirm|agree|approve|provide)\b", re.I)
MAX_ITEMS = 8


@dataclass
class Card:
    doc_id: str
    title: str
    tools: list[str]
    requirements: list[str] = field(default_factory=list)  # verbatim items
    steps: list[str] = field(default_factory=list)          # verbatim items of the section that uses the tool
    customer_points: list[str] = field(default_factory=list)  # items where the customer is asked, told or confirms

    def text(self, tool: str) -> str:
        parts = [f'The procedure you retrieved for {tool} ("{self.title}", {self.doc_id}):']
        if self.requirements:
            parts.append("Requirements: " + " | ".join(self.requirements[:MAX_ITEMS]))
        if self.steps:
            parts.append("Steps: " + " | ".join(self.steps[:MAX_ITEMS]))
        if self.customer_points:
            parts.append("Customer must be asked/told: " + " | ".join(self.customer_points[:MAX_ITEMS]))
        return "\n".join(parts)


def split_results(kb_text: str) -> list[tuple[str, str, str]]:
    """(doc_id, title, content) for each document in a KB_search result."""
    ms = list(RESULT.finditer(kb_text or ""))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(kb_text)
        out.append((m.group("id"), m.group("title").strip(), kb_text[m.end():end].strip()))
    return out


def _sections(content: str) -> list[tuple[str, str]]:
    """(heading, body) pairs; text before the first heading has heading ''."""
    hs = list(HEADING.finditer(content))
    if not hs:
        return [("", content)]
    out = [("", content[:hs[0].start()])] if hs[0].start() else []
    for i, h in enumerate(hs):
        end = hs[i + 1].start() if i + 1 < len(hs) else len(content)
        out.append((h.group(2), content[h.end():end]))
    return out


def _stem(heading: str) -> str:
    """The action word of a heading ("Freezing Steps" -> "freez"), for pairing steps with their requirements."""
    words = [w for w in re.findall(r"[a-z]+", heading.lower()) if w not in
             {"steps", "step", "requirements", "requirement", "procedure", "process", "the", "a", "for", "of", "and",
              "to", "eligibility", "prerequisites", "conditions", "rules", "before", "how", "agent", "internal"}]
    return words[0][:5] if words else ""


def compile_doc(doc_id: str, title: str, content: str, tool_names: set[str]) -> dict[str, Card]:
    """One card per tool the document names (a document often covers a pair, e.g. freeze and unfreeze, whose
    requirements differ). Empty if it names none of `tool_names`."""
    names = [n for n in sorted(tool_names) if re.search(rf"\b{re.escape(n)}\b", content)]
    sections = _sections(content)
    out = {}
    for tool in names:
        card = Card(doc_id=doc_id, title=title, tools=[tool])
        tool_sections = [(h, b) for h, b in sections if re.search(rf"\b{re.escape(tool)}\b", b)]
        stems = {_stem(h) for h, _ in tool_sections} - {""}
        for h, b in sections:
            items = [m.group(1) for m in ITEM.finditer(b)]
            if REQUIREMENT_HEADING.search(h) and (not stems or _stem(h) in stems or not _stem(h)):
                card.requirements += items
                card.customer_points += [x for x in items if CUSTOMER_TOUCH.search(x)]
        for h, b in tool_sections:
            items = [m.group(1) for m in ITEM.finditer(b)]
            card.steps += items
            card.customer_points += [x for x in items if CUSTOMER_TOUCH.search(x)]
        if not card.requirements:  # no requirements section: fall back to "must"/"only" sentences near the tool
            text = "\n".join(b for _, b in tool_sections) or content
            card.requirements = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n", text)
                                 if re.search(r"\b(must|only if|only when|cannot|required|not eligible)\b", x, re.I)
                                 and 10 < len(x.strip()) < 220][:MAX_ITEMS]
        card.requirements = list(dict.fromkeys(card.requirements))
        card.steps = [x for x in dict.fromkeys(card.steps) if x not in card.requirements]
        card.customer_points = list(dict.fromkeys(card.customer_points))
        out[tool] = card
    return out


def cards_from_results(kb_texts: list[str], tool_names: set[str]) -> dict[str, list[Card]]:
    """tool name -> cards from every retrieved document that names it (first retrieval of a document wins)."""
    out: dict[str, list[Card]] = {}
    seen: set[str] = set()
    for text in kb_texts:
        for doc_id, title, content in split_results(text):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            for tool, card in compile_doc(doc_id, title, content, tool_names).items():
                out.setdefault(tool, []).append(card)
    return out
