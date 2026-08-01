# Build specification — governed skill review process

## Goal

Create a repository-local `review-skill-candidate` package that turns a skill or research pull request into a frozen, role-separated, evidence-bound review bundle and a narrow named-human merge decision.

## Acceptance criteria

- Resolve base and head refs to immutable commit SHAs and hash the complete diff.
- Index every changed file and allowlisted policy with content hashes.
- Bind deterministic validation claims to a content-projection manifest, exact argument arrays, tool-version probes, UTC timestamps, execution statuses, and a hashed artifact manifest.
- Create isolated evidence/methodology, engineering/reproducibility, and skill-safety/operations assignments.
- Require schema-shaped findings with file/line evidence, declared coverage, counterevidence, confidence, and limitations.
- Bind adjudication to exact reviewer-submission hashes and require every finding to receive one disposition.
- Fail closed on target or packet drift, missing roles, duplicate reviewers, malformed evidence, stale hashes, or unresolved P0/P1 findings.
- Keep merge eligibility, behavioral efficacy, promotion readiness, and installation readiness separate.
- Reserve approval for the named human decision owner.
- Preserve unrelated worktree changes and avoid external side effects.

## Deliverables

- `skills/review-skill-candidate/`
- deterministic packet and validation script
- self-reference-safe validation-evidence recorder and verifier
- schemas, templates, role cards, and workflow contract
- synthetic regression fixtures and unit tests
- a frozen, provisional PR #1 review bundle
- candidate, technique, ledger, and dashboard records

## Validation

Run unit tests, skill validation, JSON and JSONL parsing, real packet initialization, independent forward reviews, adjudication, bundle validation, dashboard freshness/tests, secret and absolute-path scans, and scoped `git diff --check`.

Behavioral superiority over a single reviewer and transfer to ChatGPT remain `Unknown` until a fresh matched-budget holdout is run.
