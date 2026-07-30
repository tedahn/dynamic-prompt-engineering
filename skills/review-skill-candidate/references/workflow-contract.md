# Governed review workflow contract

## Decision separation

| Decision | Evidence required | Authorized decider |
|---|---|---|
| Merge readiness | Frozen diff, deterministic checks, independent reviews, adjudication | Repository merge owner |
| Evidence admission | Provenance, relevance, contradictions, freshness | Research evidence owner |
| Evaluation activation | Preregistered arms, fixtures, budget, isolation, stop rules | Experiment owner |
| Result promotion | Held-out results, regressions, replication limits | Research decision owner |
| Installation or adoption | Promotion record, operations, privacy, cost, rollback | Adoption owner |

No row implies another. A merge may publish an explicitly experimental candidate without authorizing its use.

## Required sequence

1. Resolve base and head refs to immutable SHAs.
2. Hash the diff, changed files, canonical policies, and target artifacts.
3. Open a proposed gate for one decision and one target.
4. Build a shared core context packet.
5. Create role-specific assignments without other reviewer outputs.
6. Run reviewers independently and retain raw structured submissions.
7. Freeze submission hashes.
8. Adjudicate evidence, conflicts, and severity.
9. Run deterministic bundle validation.
10. Request a named-human decision.
11. Record conditions, dissent, expiry, and reversal evidence.

## Context minimum

Every reviewer receives:

- review ID, repository, base SHA, head SHA, and diff SHA-256;
- the requested decision and named decision owner;
- authorized and forbidden actions;
- changed-file and evidence indexes with exact paths and hashes;
- canonical governance and evaluation-policy pointers;
- known validation evidence and declared limitations;
- its role card, output schema, severity rubric, and stop rules.

Exclude other submissions, expected findings, author intent, hidden labels, and proposed fixes until adjudication.

## Timeout and replacement

Treat a missing or late reviewer/adjudicator output as incomplete, never as a pass. Preserve the failed attempt in the evaluation record, stop that context, and assign a fresh identity with a fresh bounded packet. A replacement must not receive unpublished partial output from the failed attempt. Validate the replacement artifact normally and disclose the substitution in limitations and resource accounting.

## Merge gate

Mechanical eligibility requires all required roles, unique reviewer identities, target-integrity checks, valid evidence anchors, an adjudication bound to exact submission hashes, and zero upheld unresolved P0/P1 findings. The result remains `provisional` until the named human decides.

Reopen or supersede the review if any target or decision-critical input changes.
