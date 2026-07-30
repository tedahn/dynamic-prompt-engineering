# PR-001-8371f0f9634b — merge-readiness decision

- Gate: G5 review handoff; merge decision only
- Status: proposed
- Decision owner: Ted Ahn
- Requested by: Ted Ahn via Codex task 2026-07-30
- Opened at: 2026-07-30T05:38:48Z
- Decided at: null
- Expires at: target or policy change
- Supersedes: null
- Evidence snapshot: `8371f0f9634bf86e3417bae09772418034239969 / 24048aec899e9298b8fa5b08893e428e9de03aba518f9a99431f565c9a7943ca`

## Decision requested

After independent reviews and adjudication, decide whether the exact frozen target may merge.

## Why now

The target is published for review and requires evidence beyond deterministic tests.

## In scope / out of scope

In scope: merge coherence, evidence integrity, implementation reproducibility, skill safety, and operational reviewability. Out of scope: behavioral-efficacy claims, skill promotion, installation, deployment, or broader adoption.

## Roles

- Responsible: three isolated reviewers and one adjudicator
- Accountable: Ted Ahn
- Consulted: repository maintainers and evidence owners as needed

## Evidence

Use only the frozen context packet, target commits, allowlisted policies, raw submissions, and deterministic validation summary.

## Acceptance criteria

Target and packet integrity pass; all required roles are independent; every finding is adjudicated; no upheld unresolved P0/P1 remains; the named human decides.

## Stop conditions

Stop on target drift, missing role coverage, contaminated independence, secrets, privacy risk, invalid evidence anchors, or unavailable decision authority.

## Decision

Pending named-human decision. Models and harnesses may not change this status to approved.

## Reversal evidence

Any target, policy, evidence, reviewer-independence, or authority change reopens the gate.

## Handoff

Adjudicator receives immutable submissions after independence closes; the decision owner receives adjudication plus validation and retains final authority.
