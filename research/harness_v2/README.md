# Harness v2: retrieve → compile → track → recover (2026-09-29, $0)

**Code:**
- `bench/ledger.py`: the task ledger and the `task_plan` tool;
- `bench/compiler.py`: the just-in-time procedure compiler;
- `bench/harness.py`: the v2 checks.

**Tests:** `tests/test_harness_v2.py` (14) and `tests/test_batch_parallel.py` (4). v1 is unchanged, and H001 is still frozen to it: `{"version": "v2"}` turns v2 on.

## What v2 adds to v1

| Stage | Component | What it does |
|---|---|---|
| **Track** | **Ledger** (`bench/ledger.py`) | Task state kept by code, rebuilt from the agent's own conversation on every check, so it cannot drift from what happened: who is verified, clock readings, every search and the documents it returned, tools used or handed over, successful writes with receipts, and the agent's plan |
| **Track** | **`task_plan`** (runs inside the harness, never sent to the benchmark) | The agent records the customer's requests and, for each, what it must find out. Each need is `open` / `found` (with the doc_id that answered it) / `not_found`. The environment never sees these calls |
| **Compile** | **Procedure compiler** (`bench/compiler.py`) | Compiles each document the agent retrieves that names a tool into a card for that tool: its requirements section, the steps that use the tool, and the points where the customer must be asked or told something. Every item is a verbatim line of the document. **The prior work compiles offline from a policy it is handed** (PolicyGuide, STAGE); **here only documents this agent retrieved in this conversation are compiled** |
| **Recover** | `procedure_checklist` (soft) | Before the first use of a discovered tool (a write, or handing it to the customer), shows that tool's card. It is skipped if the plan already cites the card's document |
| | `plan_before_acting` (soft, once per conversation) | Before a first write, transfer or denial with no plan: record one |
| | `needs_covered` (soft) | Before a write, transfer or denial: lists needs still `open`, and needs marked `found` whose cited document was never retrieved (a fabricated source) |
| | `transfer_after_asking` (soft) | Policy rule 5: ask the customer before transferring, unless a retrieved procedure requires an immediate transfer |
| | `claims_need_receipts` (soft) | A reply saying a change was made, when no change has succeeded and no tool was handed to the customer |
| | `duplicate_write` (hard) | A write identical to one that already succeeded (it would change the account twice) |

**Budget and limits:**
- The soft checks each advise once per turn and are released on a repeat.
- A `task_plan` call is not a correction; at most 3 per turn.
- The v1 caps still apply: 1 correction per turn, 8 per conversation.

**What we decided not to add:** a verification check before handing a tool to the customer. The reference solution for task 015 hands over a customer tool without any verification, which is correct under the policy (verify only to access or change records). The earlier review packet listed this as a gap; the reference solution shows it isn't one.

## Positive control: the 19 saved failures (`replay_saved_v2.json`)

The checks fire at a failure point in **17/19** conversations; v1 reached 13/19. The newly reached ones:
- **019 (variant arm), the unauthorized rewards write.** The checklist for `update_transaction_rewards_3847` (doc `_004`) tells the agent to first look up the resolved disputes and independently verify rates and eligibility.
- **015, R001's one policy failure.** The checklist fires when the referral tool is handed over. It is only partly relevant: its card covers how to use the tool, not the referral-programme requirement.
- **047, the statement credit.** The checklist for `apply_statement_credit_8472` fires.
- **066 (baseline).** The agent transfers without a plan.

**Still unreached:** 069 and 031 (baseline). They are retrieval failures that never reach a write or a give-up.

## Negative control: correct behaviour on all 30 dev tasks (`reference_controls_v2.json`)

The scripted careful agent from v1 now also records a plan, citing the documents its searches actually returned (BM25, computed offline).

**Results:**
- **Same official reward with and without v2: 30/30** (all 1.0).
- **Hard checks firing on correct behaviour: 0/30,** including the new duplicate-write check.
- **Soft checks:** 32 firings, in 21/30 tasks; 9 tasks had none.
  - `procedure_checklist`: 26 firings in 18 tasks. This is by design: it fires before the first use of each tool whose card the plan does not cite.
  - `transfer_after_asking`: 4, on correct transfers the reference makes without asking.
  - `search_before_giving_up`: 2.
- **Cost of the soft firings:** each costs one extra model call, and the script's next step is consumed. So the hard-check-only run decides the reward (see `reference_controls.py`).
- **Prompt size:** agent input tokens are **1.09×** the baseline.
- **Unchanged v1:** a rerun of the v1 control (30/30, 0 hard firings, 1.09×) confirms v2 did not change v1.
- **What this does not show:** whether a live model follows the checklists to better outcomes, or ignores them at the cost of extra calls. H002 has to measure that.

## Limits

- **A soft check costs one extra model call when it fires.** On correct behaviour it fires only where noted above; on a live model it will fire more often, and H002 must measure what that costs.
- **The compiler is rule-based.** It covers requirements for *using a tool* (45 documents produce cards). Eligibility and rates spread across other documents remain the job of search and the plan. If the rule-based cards turn out too noisy, an LLM compiler is the next step.
- **Context compaction is not built yet.** Replacing old search results with notes risks losing a detail we needed, so it gets its own offline test first.
- **Everything is dev-set engineering until a frozen held-out run.**
