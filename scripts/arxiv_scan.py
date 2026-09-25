"""Weekly arXiv triage: new papers relevant to each research cycle, as a markdown digest.

    uv run python scripts/arxiv_scan.py

How it works (built to stay under arXiv's rate limits):
  1. Fetch the "past week" listing for each category (one request per category).
  2. Match titles against per-cycle keyword patterns locally.
  3. Fetch abstracts for the matches only, in batches via the API's id_list.
Title matching is a triage filter: it can miss papers whose titles don't use these words,
which DAIR.AI Academy's curated issues help cover. Papers listed in research/arxiv_seen.json
are skipped, so each digest shows only what's new since the previous run.
"""

import json
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent / "research"
SEEN = ROOT / "arxiv_seen.json"
CATEGORIES = ["cs.AI", "cs.CL", "cs.LG"]
AGENTIC = r"agent|agentic|LLM|language model|tool|assistant"

# Cycle -> (title pattern, whether the title must also look agent/LLM-related)
CYCLES: dict[str, tuple[str, bool]] = {
    "0 · Benchmarks, eval & reliability": (r"tau|τ|customer (service|support)|pass\^?k|reliab|leaderboard|benchmark", True),
    "1 · Retrieval & reading over knowledge bases": (r"knowledge base|retriev|\bRAG\b|agentic search|search agent", True),
    "2–3 · Policy, dependencies & ordering": (r"polic(y|ies) (compliance|adherence|violation)|compliance|constraint|guardrail|contract|plan verif", True),
    "4 · Trust, verification & false success": (r"false success|verif|trust|claim|self-report|sycophan", True),
    "5 · State, memory & context": (r"memory|context (compaction|management|engineering|window)|long-horizon|belief state", True),
    "Harness engineering": (r"harness|scaffold|tool[- ]?(use|call|using)|\bMCP\b|agent loop", False),
    "8 · Training agents & distillation": (r"reinforcement learning|\bRL\b|GRPO|distill|on-policy", True),
}

HEADERS = {"User-Agent": "Mozilla/5.0 (agent-eval-platform arxiv triage; +https://github.com/nidhi1603)"}


def fetch_listing(client: httpx.Client, category: str) -> dict[str, str]:
    html = client.get(f"https://arxiv.org/list/{category}/pastweek?show=2000").raise_for_status().text
    ids = re.findall(r'href\s*=\s*"/abs/(\d{4}\.\d{4,5})"', html)
    titles = re.findall(r"<div class='list-title mathjax'><span class='descriptor'>Title:</span>\s*(.*?)\s*</div>", html, re.S)
    total = re.search(r"Total of (\d+) entries", html)
    if total and int(total.group(1)) > len(ids):
        print(f"warning: {category} listing truncated ({len(ids)} of {total.group(1)} shown)")
    return {i: " ".join(unescape(t).split()) for i, t in zip(ids, titles)}


def fetch_abstracts(client: httpx.Client, ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for k in range(0, len(ids), 50):
        chunk = ids[k:k + 50]
        resp = client.get(f"https://export.arxiv.org/api/query?id_list={','.join(chunk)}&max_results=50")
        if resp.status_code != 200:
            print(f"warning: abstracts unavailable for {len(chunk)} papers (HTTP {resp.status_code})")
            continue
        for entry in re.findall(r"<entry>(.*?)</entry>", resp.text, re.S):
            arxiv_id = re.search(r"<id>http://arxiv.org/abs/(.*?)(v\d+)?</id>", entry).group(1)
            out[arxiv_id] = {
                "summary": " ".join(re.search(r"<summary>(.*?)</summary>", entry, re.S).group(1).split()),
                "published": re.search(r"<published>(.*?)</published>", entry).group(1)[:10],
            }
        time.sleep(5)
    return out


def first_sentences(text: str, n: int = 2) -> str:
    return " ".join(re.split(r"(?<=[.!?])\s+", text)[:n])


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    seen: set[str] = set(json.loads(SEEN.read_text())) if SEEN.exists() else set()

    with httpx.Client(timeout=90, headers=HEADERS, follow_redirects=True) as client:
        papers: dict[str, str] = {}
        for cat in CATEGORIES:
            papers.update(fetch_listing(client, cat))
            time.sleep(5)
        print(f"{len(papers)} papers listed across {', '.join(CATEGORIES)} in the past week")

        matched: dict[str, list[str]] = {name: [] for name in CYCLES}
        for arxiv_id, title in papers.items():
            if arxiv_id in seen:
                continue
            for name, (pattern, needs_agentic) in CYCLES.items():
                if re.search(pattern, title, re.I) and (not needs_agentic or re.search(AGENTIC, title, re.I)):
                    matched[name].append(arxiv_id)
                    break  # each paper appears once, under its first matching cycle

        wanted = [i for ids in matched.values() for i in ids]
        abstracts = fetch_abstracts(client, wanted)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# arXiv triage — week ending {today}",
             f"{len(papers)} new papers in {', '.join(CATEGORIES)}; {len(wanted)} matched by title.", ""]
    for name, ids in matched.items():
        lines += [f"## Cycle {name} ({len(ids)})", ""]
        if not ids:
            lines += ["_No title matches._", ""]
        for i in ids:
            info = abstracts.get(i, {})
            lines.append(f"- **{papers[i]}** — [{i}](https://arxiv.org/abs/{i})")
            if info:
                lines.append(f"  {first_sentences(info['summary'])}")
        lines.append("")

    out = ROOT / f"arxiv_digest_{today}.md"
    out.write_text("\n".join(lines))
    SEEN.write_text(json.dumps(sorted(seen | set(wanted)), indent=0))
    print(f"{len(wanted)} matched ({len(abstracts)} with abstracts) -> {out}")


if __name__ == "__main__":
    main()
