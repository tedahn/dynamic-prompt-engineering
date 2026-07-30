# Evaluation protocol — stateful Codex loop v1

- **Status:** mechanics implemented; live study blocked pending owner, budget, and fresh holdout
- **Primary estimand:** the incremental held-out task value of gated evolving context over retrieval from a frozen approved context, under matched surface and tool controls
- **Experimental unit:** an ordered episode of 5–7 tasks and feedback events
- **Evidence state before execution:** design-only

## Conditions

| ID | Condition | Purpose |
| --- | --- | --- |
| B0_STATELESS_RAW | Fresh session, no persistent context | Model-native floor |
| B1_FROZEN_CONTEXT | Same curated context injected for every task; no retrieval or mutation | Controls for fixed extra instructions |
| B2_APPEND_ONLY | Raw prior episode history appended until budget | Controls for more history/tokens without curation |
| B3_RETRIEVAL_ONLY | Versioned approved state with deterministic retrieval; no updates | Primary adoption baseline |
| B4_HUMAN_MAINTAINED | Blinded expert updates context from identical development evidence | Diagnostic ceiling only |
| C1_GATED_EVOLVING | Codex proposes scoped patches; harness validates; candidate is evaluated before activation | Candidate process |

B2 and B4 are diagnostic conditions used when the primary comparison is ambiguous; they are not required in every phase.

## Episode families

Development episodes cover the existing editing, coding, research, decision-analysis, and creative domains, overlaid with:

1. useful preference or fact recall;
2. correction and supersession;
3. stale-state expiry and refresh;
4. same-scope transfer;
5. out-of-scope and negative transfer;
6. authority change or attempted escalation;
7. prompt injection and memory poisoning;
8. privacy deletion and forbidden persistence;
9. restart, compaction, and handoff survival;
10. contradiction handling;
11. null-memory cases where context should not affect the answer;
12. state-bloat and retrieval-budget pressure.

Committed development episodes are calibration material only. The existing readable V1 holdout is contaminated for this challenger. The full study requires at least 24 new episodes authored after the updater, schema, retrieval policy, rubric, runtime, and thresholds are frozen, then stored outside the optimizer-visible workspace.

## Phases

| Phase | Episodes | Conditions | Trials | Runs | Decision use |
| --- | ---: | --- | ---: | ---: | --- |
| Mechanical | Synthetic recorded artifacts | Harness only | 1 | 0 model calls | Validate state transitions and invariants |
| Smoke | 3 development | B0, B3, C1 | 1 | 9 | Catch integration failures only |
| Pilot | 12 development | B0, B1, B3, C1 | 3 | 144 | Tune rubric and estimate variance; no adoption |
| Full | ≥24 fresh escrowed holdout | B1, B3, C1 | ≥3 | ≥216 | Human promotion decision |

The full sample may increase after a power analysis from pilot variance; it may not decrease below the preregistered floor after outcomes are inspected.

## Assignment and blinding

- Clone isolated workspaces per episode-condition-trial.
- Start every replicate from the same accepted snapshot; discard state learned inside a holdout replicate.
- Use fixed independent execution, anonymization, and grading seeds.
- Rotate condition order by episode/trial and randomize anonymous IDs and pairwise left/right order independently.
- Give the subject only the authorized condition packet.
- Give graders neither condition identity, context contents, prompt provenance, nor state lineage.
- Double-score every high-authority episode and at least 20% of others. Model grades are provisional until required human review.

## Score channels

Scores remain separate in the ledger. No composite can conceal a critical failure.

### Task outcomes

- deterministic requirement compliance (0–100);
- blinded human quality (0–100);
- explicit pairwise preference;
- factual/evidence correctness where applicable.

### State quality

- required-memory recall;
- irrelevant or stale retrieval rate;
- mutation precision and recall;
- valid provenance, expiry, and supersession;
- unauthorized persistence/deletion rate;
- context-pack precision and budget adherence.

### Dynamics

- time to recover from correction;
- transfer gain and negative-transfer rate;
- regression flips by family;
- retention after distractors, restart, and compaction;
- state churn, revert rate, and size growth.

### Operations

- actual input/output tokens, calls, latency, storage growth, retries, and tool actions;
- cost ratio against B3 using the same provider accounting source.

## Analysis

Aggregate within episode first. Compare C1 with B3 using paired episode effects and a family-stratified bootstrap. Report means, medians, 95% intervals, family effects, worst cases, critical gates, missingness, and actual cost. Treat retries for completed low-quality answers as forbidden; retry only frozen transient-error classes.

## Preregistered promotion defaults

These are provisional engineering thresholds to freeze before the pilot and recalibrate only without holdout access:

- zero privacy, authority, destructive-action, unauthorized-persistence, or holdout-leakage gates;
- lower 95% confidence bound for C1 minus B3 task score of at least +5 points;
- lower 95% bound on pairwise win probability above 0.50;
- no episode-family mean effect below −3 points;
- context precision at least 0.80 and stale/irrelevant retrieval at most 0.05;
- no regression in requirement preservation or deletion compliance;
- cost no more than 2× B3 unless mean task gain is at least +10 points;
- fresh holdout, named owner, human review, tested rollback, and canary plan.

The harness may report `eligible_for_human_review`; only a named human may decide `promote`.

## Learning boundary

The optimizer may learn from development events and spent regression cases. It may not receive fresh holdout prompts, expected behavior, outputs, grades, rationales, context-pack traces, or aggregate family results. Within-holdout adaptation is allowed only inside an isolated replicate and is discarded at episode end.

## Stop rules

Stop on surface/runtime drift, policy/hash mismatch, unapproved provider processing, holdout exposure, context-pack near-duplicate leakage, conflicting duplicate cell results, a critical gate, exhausted cost ceiling, missing trace/usage, or evaluator identity leakage.

## Reporting

Keep mechanical validation, development observations, provisional model grades, adjudicated human outcomes, and promotion decisions distinct. Preserve negative/null results, the exact active and candidate snapshots, artifact hashes, owner, review date, canary, and rollback target.
