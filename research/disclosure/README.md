# Identity-value disclosure check (flag `disclosure_check`; 2026-10-01, $0)

**Why** (D005, `experiments/D005_findings.md`). After v3.2 held an unsupported verification, gpt-5-mini asked for the missing fields. In 4 of 30 replies it also showed the customer's real stored values, usually as an "example", although its feedback forbade it. The bank's rule (tau2 `prompts/components/additional_instructions.md`, "Authenticating Users"): "Do not leak any information about the user before they are verified."

## What it does (`bench/identity_disclosure.py`, gate `identity_disclosure` in `bench/harness.py`)

- **Scope.** It checks every customer-facing text the agent proposes, before delivery and throughout the conversation, including text that accompanies tool calls. The trigger is not limited to a failed verification attempt.
- **Prohibited** (a hard check): a stored date of birth, email, phone number or street address, from a customer record retrieved in this conversation, when both of these hold:
  - that customer is not yet verified (no "Verification logged successfully" receipt for that user_id);
  - the value was not supplied **independently** by the customer.
- **Provenance** (`verify_evidence.provenance`, the one rule shared with the verification check and the probe classifier): a value is the customer's only if the customer wrote it before any DELIVERED agent message showed it. A value the agent showed first stays prohibited after the customer echoes it. Read-backs of independently supplied values are allowed. Drafts the harness held, replaced or withheld do not count, because the customer never saw them (fixed after the second review: `readback/README.md`).
- **Release.** A successful verification receipt releases that customer only. Other retrieved customers stay protected.
- **Handling:**
  - **A verification-related, text-only draft is replaced at once**, with no regeneration, by the fixed request for the missing fields (`withheld_reply`). That request is a template of field names only. It now also leaves out fields the agent had already revealed (those can only come back as echoes). If too few usable fields remain, it sends an apology instead of a request.
  - **Any other caught draft**, including one beside tool calls, gets one regeneration with feedback (field kinds only, never values). If it still leaks, a fixed apology is sent ("I can't share details from your account until your identity is verified"); this is not an identity request.
  - The rejected draft and the customer-visible replacement are logged separately (`disclosure_replaced`, `held`/`withheld` events).
- **Fail-closed:** a checker defect holds the draft.
- **Separate flags:**
  - `disclosure_check` turns this check on.
  - `verification_feedback: "fields_only"` is the WORDING revision on its own: v3.2's feedback adds "name the fields only; never give example values". So the two effects can be measured apart.
  - Both are off by default. Each spec registers under its own agent name; before this, a spec that ADDED a gate could share a name, so the later run got the first spec's settings. That was found and fixed here, and no earlier run was affected.

**Coverage, stated narrowly.** This enforces ONE part of the disclosure rule: four stored identity fields, in the formats `verify_evidence` recognises (dates in common written forms, phones by digits, emails, street lines). It does not cover:
- other account information (balances, card digits, transactions, the internal user_id);
- partial values;
- confirming that a field matched or did not;
- confirming that an account exists;
- reformatted values it does not recognise.

The blind review found such other disclosures in 4 of 23 messages (below). The read-back review found 3 more kinds in its set: match confirmation (2 real messages) and city/state/ZIP added to a street (1 synthetic).

## Offline evidence (which messages WOULD be held or replaced; not conversation outcomes)

| Question (from the review) | Evidence |
|---|---|
| Catches all four D005 disclosure replies? | Yes: runs 10, 18, 21 and 29. The three verification-related ones are replaced without regeneration (test) |
| Allows read-backs of independently supplied values? | Unit tests. The blind sample barely tests it (14 of its 15 allowed messages went to already-verified customers), so a second review focused on it (`readback/`): all 6 real pre-verification read-backs allowed and judged correct. 14 labelled synthetic cases found 1 false block, an unambiguous day-first date, now fixed: 14/14 |
| Does an intercepted draft spoil the customer's own later evidence? | It did: held drafts counted as shown. Fixed: provenance counts delivered messages only; tests in both directions, plus an end-to-end test (`readback/README.md`) |
| Still blocks repeats after customer echoes? | Unit test (origin "agent") |
| Date, phone, email and address formats? | Unit tests: 5 formats, plus verify_evidence's 30+ format tests |
| Valid verification releases the restriction? | Unit test: released for the verified customer; another retrieved customer stays protected |
| Safe through retries and mixed text/tool responses? | End-to-end: held → withheld apology; a draft with tool calls is held as a whole and its calls do not run; replacement path tested end to end; the fallback is tested against all 39 customers' stored values |

**Replay over every saved agent message** (`replay.py` → `replay.json`):
- 1,301 agent texts in all live traces.
- 82 contain a stored identity value of a retrieved record.
- **13 would be caught**, in 13 conversations. All are new disclosures and all are verification-related, so all would be replaced. 5 of the 13 are in the 10 D005 development histories.
- 69 contain identity values but are allowed: read-backs, or data shown after verification.

**Blind review on fresh data** (`review/`; the D005 histories excluded):
- The sample: all 8 fresh flagged messages plus 15 random fresh allowed ones, shuffled, judged against the bank's rule.
- **23 of 23 agree**: all 8 flagged are leaks, with the same fields named; all 15 allowed are not.
- This is a selected validation sample, not an accuracy estimate.
- The reviewer separately noted disclosures outside this check's coverage: confirming which field matched (2), the internal user_id (1), and confirming that an account exists (2).

**Reference controls** (the identity script), with `disclosure_check` on: 30/30 under bm25 and alltools, nothing fired.

## Reproduce

    uv run --extra bench python research/disclosure/replay.py
    uv run --extra bench python research/harness_v1/reference_controls.py --version=v3.2dc [--retrieval=alltools]
