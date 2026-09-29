# How to get a better banking agent than the published results: research and plan (2026-09-28)

**Question.** Nidhi's goal is a harness around an LLM agent on τ-Knowledge (`banking_knowledge`) that beats published results. This document gathers the evidence on what is achievable, which levers matter for *our* agent, and a staged, budgeted way to get there.

**Sources.**
- The τ-Knowledge paper (arXiv 2603.04370, full text).
- The official leaderboard submission files (tau2-bench repo, 72 submissions) and open submission PRs.
- A literature review: 40 arXiv IDs, all resolved; 5 papers test harnesses on banking itself.
- A $0 re-analysis of our 19 saved live conversations against each task's required documents and reference actions.

---

## 1. What "the published results" are

| Reference point | pass^1 | pass^4 | Setup | Status |
|---|---|---|---|---|
| **Paper, best** | **25.5** | 9.3 (best pass^4 13.4) | GPT-5.2 (high reasoning), terminal search, 97 tasks × 4 | published |
| Paper, gold documents in context (upper reference) | 32.7 (GPT-5.2), **39.7** (Opus 4.5) | 18.6 / 26.8 | retrieval removed as a factor | published |
| Leaderboard, best standard agent | **55.2** | 35.1 | Qwen 3.8 Max, `alltools` | merged (verified in repo files) |
| Leaderboard, best merged custom | 31.2 | 13.4 | Distyl: GPT-5.4 + custom retrieval (graded on a pre-1.0.1 version) | merged |
| Claimed custom | **86.6** | 77.3 | ByteVerity: DeepSeek V4 Flash proposes, a deterministic "decision layer" tracks state, checks policy and gates actions; about $0.016/trajectory | **open PR since July, not verified or merged** |
| Closest to our model | 12.6 | 4.1 | GPT-5.2 with reasoning *off* | merged |
| **Ours** | **0/18** full conversations | – | gpt-5-mini (low), BM25, 12 dev tasks | our runs |

**Reading.**
- "Beat the paper" (25.5%) and "beat the leaderboard" (55%) are very different targets.
- The claimed 86.6% suggests a harness that makes decisions deterministically can move a *cheap* model far above frontier models. That claim is unverified. It also compiled a "clause store" from the public corpus; whether that included task-derived data is unknown.
- Our agent currently sits at the bottom of the range.

## 2. Why our agent fails (the $0 re-analysis of 19 conversations)

Each conversation was classified by the first reference action it failed, using explicit rules. Full table: scratch `failure_analysis/`.

| Primary cause | Conversations | What it looks like |
|---|---|---|
| **Retrieval** | 8 | The documents or tool names needed were never retrieved. 8 of 19 conversations searched only **once**. Required-document recall was **34%** (68/200). |
| **Tool use** | 7 | The needed tool's name was in the results, then "I don't have access" or a transfer |
| **Argument** | 2 | Invented verification timestamp; the agent never read the clock. Fatal to the database grade |
| **User simulator** | 1 | The customer withheld information (ambiguous) |
| **Policy reasoning** | 1 | Handed over a referral tool for a card with no referral programme |

Other facts from the analysis:
- The agent transferred to a human in **11** conversations; the reference includes a transfer in only **1**. Customer-requested transfers always followed the agent's own "I can't".
- Most conversations have **several** sufficient causes: secondary tool-use failures in 4, secondary retrieval or product-choice failures in 4.
- **The direct-tool adapter alone** would plausibly rescue about **1 of 19** (at most 5). It fixes a necessary step, not enough of them.
- The paper points the same way: gold documents add about 15 points, and even then the best model reaches only 40%, so reasoning over policy is the larger ceiling. Its failure clusters are search inefficiency and assumptions (~23%), product interdependencies (~14.5%), subtask ordering (~5%) and over-trusting the user (~4%).

**Conclusion.** No single fix will do it. Our agent fails at four stacked stages:
1. finding the knowledge;
2. acting on discovered tools;
3. getting mechanical details right (clock, identifiers);
4. reasoning over policy.

A harness has to address the first three together to show a measurable gain. The fourth is mostly the model's job.

## 3. What the evidence says works (and what doesn't)

**Measured on banking_knowledge itself:**

| Evidence | Result | Implication |
|---|---|---|
| Paper App. F: reranker, adding grep, k = 5/10/20 | **no significant effect** | Don't spend effort on retrieval tuning |
| Paper: terminal vs retrievers | +2 pts average, **only for high-reasoning models** | A shell doesn't help a low-reasoning model |
| Paper: reasoning off → high (GPT-5.2) | **11.6 → 25.5** | Reasoning effort is the largest single factor |
| Paper: whole KB in context | worse than retrieval (11.9) | Don't stuff the context |
| Declarative Skills (2606.06923) | +2–5 pts with good retrieval; **state machines hurt every model (−3.5 to −26)**; skills hurt under noisy retrieval | Declarative notes yes; hard-coded flows no; fix retrieval first |
| HarnessLens (2608.27311) | gated harness evolution +4.5 to +14; **Meta-Harness and Self-Harness regressed** (20.9 → 13.4, 10.5) | Never accept a change without held-out evidence |
| Learning on the Job (2607.22157) | memory of rules: Mistral 6.4 → 17.0 (29 with a store built by another model); Sonnet 5 24.8 → 39.7 | Large gains, but learned on the tasks it's scored on. The honest version: a store frozen from dev, tested on held-out |
| AgentTether (2607.06273) | Reflexion repairs no more than blind retry (22/83 each) | Skip reflection and retry loops |

**On related benchmarks (τ², τ-bench):**
- **LedgerAgent (2606.20529):** grounding arguments in observed state gave **+12 to +15 pass^1** at zero extra tokens, with larger pass^4 gains. It regressed on one model and domain.
- **PolicyGuard (2606.29225):** a verifier before writes raised pass^4 by 6–12. A guard that only checks arguments *collapsed* legitimate writes on a mini model.
- **Verifier Tax (2603.19328):** blocking alone intercepts violations, but success stays under 5%, and agents *invent* IDs to get past blocks. **Blocks need a way to recover.**
- **Life-Harness (2605.22166):** an evolved harness averaged over 18 models took airline 49.7 → 62.6. Removing its action-validation layer cost 61.7%.
- **Outcome Monitors (2608.19303):** +12–14 on retail, and the gain disappeared without the list of recovery tools. **Fabrication After Tool Failure (2609.14758):** false "no access" claims fell from 14.1% to 0.9% with a forced status line.
- **Anthropic's tool-search and "think" tool reports:** tool search improved tool-use evals from 49 → 74; the "think" tool with domain examples improved airline 0.37 → 0.57.

**Pattern.** The measured wins come from **deterministic structure around the model**: state tracking, argument grounding, and validation that *explains the fix*. Prompts, reflection and automated self-rewriting do not deliver them. That matches our own D001–D003 results (instructions inconsistent) and the ByteVerity claim.

## 4. The levers, ranked for our agent

| # | Lever | Addresses | Evidence | $0 build? | Risk |
|---|---|---|---|---|---|
| 0 | **Model and reasoning effort** (a stronger cheap model, or gpt-5-mini at medium or high) | everything, especially policy reasoning | Paper: 2× from reasoning; our 0/18 at low effort | – (cost only) | Not a harness gain. Hold it fixed *within* a comparison |
| 1 | **Knowledge persistence** | retrieval (8/19) | 34% recall, single-search conversations; Sierra blog: top agents "keep retrieving" with targeted searches | yes | More cost per conversation |
| 2 | **Tool surfacing** (the direct-tool adapter, built) | tool use (7/19) | our T001/D001; tool-search reports | done | Alone ≈ 1/19 |
| 3 | **Mechanical state rules**: read the clock before verification; verify before writes; identifiers from records | argument (2/19) + safety | our guard + evidence checker; LedgerAgent | mostly built | Must *revise*, not only block |
| 4 | **Write gate with recovery**: a failed check tells the agent the next tool or document | wrong or unsupported writes | PolicyGuard, Verifier Tax, Outcome Monitors | extend `guard.py` / `evidence.py` | False blocks (we saw one in D002) |
| 5 | **Declarative domain notes**: unlock recipe, dispute-before-credit ordering, "check, don't trust the customer", "search before denying or transferring" | policy ordering, over-trust | Declarative Skills (+2–5) | yes | Only with good retrieval; no state machines |
| 6 | **Frozen rule memory** distilled from *dev* failures, accepted only on held-out | recurring policy mistakes | Learning on the Job (large, but contaminated protocol) | yes | Leakage; must gate on held-out |

**Levers 1–4 are the harness v1:**
- **Knowledge persistence**:
  - before any denial, transfer or write, the agent must have searched for that capability or product specifically;
  - search results are followed by fetching the documents they reference (by ID);
  - a list of discovered tools and their documents is kept;
  - this generalises our N001 nudge, with the lessons from its applicability review: name reads first, and never suggest writes.
- **Tool surfacing:** the direct-tool adapter, already built.
- **State and write rules that revise:**
  - read the clock before logging verification (this alone fixes 2/19);
  - verification before any write;
  - identifiers and amounts grounded in retrieved records, with a remediation message naming the tool that provides them.

**Deliberately not doing:** rerankers, k tuning, whole-KB context, reflection and retry, automated harness self-editing, hard-coded state machines, and training.

## 5. How to evaluate so a win is real

**Principles (we already follow these):**
- plans frozen before any run, with explicit approval;
- dev-only development, and a held-out test touched once;
- full conversations with official grades for any claim;
- continuations only for diagnosis;
- a disclosed custom scaffold;
- the answer-leak fix (F001) applied to the harness arm, with the harness never using `list_discoverable_agent_tools`.

**One change from ChatGPT's "one intervention at a time" guidance, and why.**
- Our failure analysis shows the adapter alone would move about 1/19. At n = 6–12 tasks, testing it alone would likely read 0 vs 0 and teach little.
- The stronger design is standard system building: build **harness v1 = levers 1–4**, verify each component at $0, compare **baseline vs harness v1** once, and only if v1 wins, **ablate** components (leave-one-out) to attribute the gain.
- This is still one controlled comparison with every other setting fixed. It trades per-component attribution *before* a win for statistical power.

**Staged plan with decision gates:**

| Stage | What | Size | Cost (forecast) | Gate to continue |
|---|---|---|---|---|
| 0 | Build harness v1 at $0: knowledge persistence, clock and verification rules that revise, write gate with remediation, on top of the adapter. Scripted equivalence and positive/negative controls for each; offline replay over the 19 traces (how often each rule fires, and whether it would fire wrongly) | – | $0 | Controls pass; no rule fires on correct reference behaviour |
| 1 | **Dev pilot:** baseline vs harness v1, gpt-5-mini, same settings as S002/S003 | 10 rule-selected dev tasks × 2 arms × 2 attempts = 40 conversations | about $4–6 | Harness passes clearly more tasks (e.g. ≥ 4 more passes of 20) **and** no increase in unauthorized writes |
| 1b | Model-sensitivity check: the same comparison at medium reasoning, or with one cheap stronger model | 10 × 2 × 1 | about $3–8 | Decide which model to take forward |
| 2 | **Ablation** of v1's components (leave-one-out) on the same dev tasks | about 40–60 conversations | about $5–8 | Keep only components that pull their weight |
| 3 | **Held-out test**, frozen harness vs baseline | 67 tasks × 2 arms × 2–4 trials | about $30–70 | The claim: improvement on unseen tasks |
| 4 | **Leaderboard-comparable run**: all 97 tasks × 4 trials, the GPT-5.2 low user simulator, a documented retrieval config, custom submission | 388 conversations (harness only) | about $40–$150, depending on model | Submit only if above a stated reference (e.g. paper best 25.5) |

**What we could honestly claim, by stage:**
- **Stage 1:** "on development tasks, the harness improved our small model."
- **Stage 3:** "on held-out tasks, …" (a real result).
- **Stage 4:** "gpt-5-mini (or X) with our harness reaches Y% on the full benchmark, above the paper's best frontier result of 25.5%, disclosed as a custom scaffold." It does not beat the current leaderboard (55%) unless Y > 55.

## 6. Realistic targets

- **Beat our own baseline (0/18):** likely achievable with harness v1. Tool-use, clock and search-persistence failures are 17 of 19 primary causes, though fixing one often reveals another.
- **Beat the paper's 25.5% with a cheap model:** plausible but unproven. The small-model data point (GPT-5.2 with reasoning off, 12.6) and LedgerAgent-style gains (+12–15) make 25% a stretch target for gpt-5-mini. It becomes more likely at medium reasoning, or with a cheap model like Gemini 3 Flash (27.3 on its own with terminal search).
- **Beat the leaderboard's 55%:** only with a much stronger decision layer (ByteVerity-style state and policy compilation) and likely a stronger model. That is a large engineering project, and it risks turning into hand-coding the benchmark. Not the next step.

## 7. Budget reality

Remaining credit: about $2.05.

| Stage | Cost | Can we do it now? |
|---|---|---|
| Stage 0 | $0 | yes |
| Stage 1 | about $4–6 | needs a top-up |
| Through Stage 3 | about $45–90 | needs a top-up |
| Stage 4 | +$40–150 | needs a top-up |

## 8. Recommended next step

**Stage 0 now ($0):** build harness v1 on top of the adapter, with controls and offline replay. Then a frozen plan for the Stage 1 dev pilot, costed, for Nidhi's decision. A002 (adapter alone) is superseded by Stage 1, since the analysis predicts it would be uninformative.

## 9. Update, 2026-09-29: closest prior work, and what harness v1 claims

A review of ChatGPT's advice (packet `agent-eval-platform_chatgpt_advice_review.md`) found that remediation after a
blocked action is already published *on tau2*:

| Work | What it does | Result |
|---|---|---|
| **PolicyGuard** (2606.29225) | Verifies writes, blocks with a specific remediation message | Airline pass^4 +6 to +12 |
| **PolicyGuide** (2608.19861) | Compiles the policy into a workflow graph; step-specific remediation; transfers gated | Mean pass^4 0.42 → 0.62 across airline, retail and telecom |
| **Outcome Monitors** (2608.19303) | A receipt that names recovery tools | The recovery-tool list is the active ingredient |

**What all three assume:** the full policy is available up front. None evaluates banking_knowledge.

**The difference harness v1 claims:**
- policies and tools must be *retrieved*;
- tools are discovered partway through the conversation;
- **give-ups are gated on whether the agent searched enough**, not only on writes.

**The costs these papers report,** which we should expect too:
- over-blocking (PolicyGuard's retail write tasks: 0.579 → 0.327);
- loops caused by static error messages;
- 2–5× cost for verifiers that are themselves language models.

Harness v1's checks are deterministic, cost no extra model calls to check, and give one correction per turn. The
build and its controls are in `research/harness_v1/README.md`.
