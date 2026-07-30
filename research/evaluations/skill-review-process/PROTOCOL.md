# Protocol — role-separated skill review

- **Status:** mechanical forward-test authorized; behavioral comparison not run
- **As of:** 2026-07-30
- **Decision owner:** Ted Ahn
- **Target surface for current forward test:** Codex desktop subagents

## Claim under test

A frozen context packet plus isolated evidence, engineering, and safety reviewers with hash-bound adjudication will produce a more complete and auditable merge decision than direct merge or one unstructured general review, without unacceptable false positives, latency, cost, or human maintenance.

## Arms

- **B0 direct:** deterministic checks and human merge decision without model review.
- **B1 general:** one model reviewer receives the full diff and a generic “review this PR” instruction.
- **C1 role-separated:** three isolated reviewers plus hash-bound adjudication.
- **C2 governed:** C1 plus explicit human gate, decision separation, stop rules, and rollback/reopen record.

Use the same frozen commit, evidence sources, model snapshot, reasoning setting, tools, time budget, and artifact access for B1/C1/C2 where controllable. Do not show reviewers seeded defect labels, another reviewer’s output, or expected findings.

## Development and holdout

Use repository PR #1 only as a development forward test of mechanics and reviewer usability. It cannot establish superiority because the target was authored in the same research process and no defect ground truth exists.

Before promotion, have a holdout custodian create at least 12 fresh mutation PRs spanning evidence overclaiming, holdout leakage, state contamination, hash drift, trigger collision, injection/privacy, authority escalation, missing rollback, partial failure, stale surface claims, nonportable paths, and misleading status reporting. Randomize conditions and blind seeded labels from reviewers and adjudicators.

## Metrics and gates

- Critical-defect recall and false-negative count
- Finding precision after blinded human adjudication
- Unsupported P0/P1 false-positive count
- Evidence-anchor validity and declared coverage
- Cross-reviewer contamination or hidden-label leakage
- Time, tokens, cost, reviewer effort, and adjudication effort
- Reproducibility of the same target and packet
- Trigger collision and maintenance burden

Promotion requires zero missed seeded P0 defects, no more critical misses than B1, materially better total defect recall or auditability than B1, no unacceptable increase in unsupported blocking findings, and a named-human judgment that the added operational cost is justified. Use a pilot power analysis rather than treating 12 cases as sufficient by default.

## Stop rules

Stop on target drift, contaminated reviewer independence, hidden-label exposure, secret/privacy breach, missing decision owner, invalid anchors, exhausted budget, unavailable telemetry, or a surface/runtime change. Record missing measurements as `null` or `unresolved`.

## Current interpretation

Unit tests and a PR #1 forward cycle can establish mechanical integrity and expose usability defects. They cannot establish behavioral efficacy, ChatGPT transfer, promotion readiness, or installation readiness.
