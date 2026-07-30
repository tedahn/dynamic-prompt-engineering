# Technique profile — T-020 role-separated evidence-grounded skill review

- **Status:** repository prototype
- **As of:** 2026-07-30
- **Owner:** Ted Ahn
- **Target surface:** Codex desktop skill and local git repositories; ChatGPT transfer untested

## Intended behavior

Turn one immutable skill or research change into a bounded review packet, independent evidence, engineering, and safety assessments, an evidence-based adjudication, and a narrow named-human merge decision without implying behavioral efficacy or adoption authority.

## Trigger and non-trigger

- **Trigger:** Skill-candidate, prompt-workflow, evaluation-harness, or research-PR review requiring auditable context, multiple technical lenses, and a human merge gate.
- **Non-trigger:** A small ordinary code review, behavioral benchmark execution, implementation of fixes, merging, installation, or deployment.
- **Mis-trigger cost:** Multi-agent latency, duplicated findings, context expense, false blocking severity, and maintenance burden.
- **Miss cost:** Self-review bias, evidence overclaim, hidden gaps between methodology and code, unreviewed safety boundaries, and merge decisions without provenance.

## Intervention

Freeze the target and policies; create a decision-focused context pack; run isolated role prompts; require schema-bound findings and declared coverage; adjudicate immutable submission hashes using evidence rather than vote count; validate target and artifact integrity; reserve the decision for the named human.

## Evidence map

- **Direct artifact:** `skills/review-skill-candidate/` defines the workflow, roles, schemas, templates, and deterministic tooling.
- **Local governance:** `EVIDENCE_GOVERNANCE.md`, `CONTINUOUS_IMPROVEMENT.md`, the stateful-loop isolation design, and candidate promotion protocols require provenance, negative evidence, independent review, human gates, and rollback.
- **Mechanical evidence:** Eight unit tests exercise packet integrity and fail-closed review conditions. This establishes implementation behavior only.
- **Development evidence:** Three isolated role reviews plus a separate adjudicator upheld seven findings on frozen PR #1: three P1 and four P2. This demonstrates one end-to-end fail-closed cycle, but the target has no blinded defect ground truth, so recall, precision, and comparative value remain unknown.
- **Strongest countercase:** One competent general reviewer plus deterministic checks may find the same material problems with lower coordination and context overhead.

## Failure and transfer analysis

Watch for correlated same-model errors, role theater without distinct coverage, severity inflation, invalid file anchors, reviewer cross-contamination, adjudicator majority voting, context bloat, stale target refs, author-controlled evidence, and human rubber-stamping. Measure time, tokens, cost, reviewer effort, and false-positive burden. Do not claim ChatGPT, cross-model, or cross-repository transfer without separate evidence.

## Evaluation readiness

The baseline arms, candidate arms, fixtures, metrics, critical gates, stop rules, and provisional holdout floor are specified in `research/evaluations/skill-review-process/PROTOCOL.md`. Fresh seeded holdouts, matched-budget runs, blinded human adjudication, and a pilot power analysis remain incomplete.

## Skill recommendation

Keep as a repository-local prototype while it improves the active PR review. Promote only if fresh holdouts show better critical-defect recall or materially better auditability than one general reviewer without unacceptable blocking false positives or operational cost; otherwise retain the packet and gate practices as guidance inside an existing review skill.
