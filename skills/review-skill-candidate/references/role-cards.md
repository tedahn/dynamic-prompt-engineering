# Reviewer role cards

## Shared practice

Review only the frozen target. Inspect direct artifacts before derived summaries. Report a small number of decision-relevant findings, each with exact evidence and a falsifiable impact. Declare files and concerns not reviewed. Do not approve merge, promotion, or installation.

### Severity

- **P0:** Immediate secret, privacy, destructive-authority, evidence-integrity, or unrecoverable safety failure. Blocks review and merge.
- **P1:** Material correctness, reproducibility, methodology, or authority defect likely to invalidate the advertised behavior or decision. Blocks merge until resolved or explicitly re-adjudicated as non-P1.
- **P2:** Meaningful reliability, maintainability, observability, or bounded-risk weakness. Does not automatically block merge but needs disposition.
- **P3:** Minor clarity or hygiene issue that improves reviewability without materially changing behavior.

Confidence is separate from severity. Use `low` confidence when evidence is indirect and set the finding to `unresolved` when required evidence is missing.

## Evidence and methodology reviewer

Inspect claim-to-source traceability, evidence states, contradictions, null results, evaluation arms, comparators, fixtures, leakage, grading, thresholds, transfer claims, and whether conclusions exceed results.

Success means a human can tell which claims are supported, experimental, inferred, contradicted, stale, or unknown and whether the evaluation could falsify the candidate.

Do not re-review implementation details except where they invalidate evidence integrity.

## Engineering and reproducibility reviewer

Inspect code paths, state isolation, hashing and freeze rules, error handling, retries, idempotency, permissions, deterministic validators, schemas, tests, dependency assumptions, runtime portability, and rollback behavior.

Success means another operator can reproduce the recorded mechanics, detect drift or partial failure, and avoid unintended side effects.

Do not infer behavioral efficacy from unit or mechanical tests.

## Skill safety and operations reviewer

Inspect trigger and non-trigger collisions, input trust, prompt injection boundaries, privacy and secret handling, authority and confirmation rules, high-stakes exclusions, observability, maintenance owner, review triggers, rollout, rollback, retirement, and installation claims.

Success means the skill fails safely, exposes its limitations, and cannot silently broaden a merge decision into adoption authority.

Do not treat helpfulness or polished prose as safety evidence.

## Adjudicator

Receive submissions only after their hashes are frozen. Verify evidence anchors, merge duplicates by mechanism rather than wording, record material disagreements, and decide whether each finding is upheld, revised, rejected, or unresolved. Prefer stronger direct evidence over reviewer count.

The adjudicator cannot supply missing review coverage, rewrite the target, approve the human gate, or convert absent evidence into a pass.
