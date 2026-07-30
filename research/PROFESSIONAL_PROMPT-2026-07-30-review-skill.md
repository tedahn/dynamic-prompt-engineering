# Professional prompt — governed skill-candidate review

Role: Design and implement auditable human-AI review systems for research-backed Codex skills and pull requests.

## Goal

Create a repository-local `review-skill-candidate` skill that prepares a frozen evidence packet, assigns isolated review lenses, captures structured findings, adjudicates disagreements, validates merge gates, and hands the final decision to a named human. Forward-test it against GitHub PR #1 without merging, installing, or production-promoting any skill.

## Context

- Repository: `tedahn/dynamic-prompt-engineering`
- Review target: PR #1, base `main`, head `codex/publish-dynamic-prompt-skills`
- Required lenses: evidence/methodology, engineering/reproducibility, skill safety/operations, and independent adjudication
- Canonical governance: repository evidence policy, continuous-improvement policy, candidate protocols, and human gate ladder
- Preserve unrelated in-progress automation changes already present in the worktree.

## Success criteria

- Package a valid skill with precise trigger and non-trigger rules, role isolation, severity definitions, evidence requirements, stop conditions, and human authority boundaries.
- Provide deterministic scripts, schemas, and reusable templates for packet creation and bundle validation.
- Freeze the reviewed base/head SHAs and context manifest; never silently review a moving target.
- Require file/line evidence, countercases, uncertainty, coverage declarations, and explicit `not_reviewed` fields.
- Keep reviewer outputs independent until adjudication; do not use majority vote as proof.
- Produce a first complete review bundle for PR #1 and record unresolved findings honestly.
- Keep merge readiness distinct from behavioral efficacy, skill promotion, and installation readiness.

## Constraints

- Do not let an author, reviewer, adjudicator, model, or harness approve its own work.
- Do not expose secrets, local credentials, private paths, hidden labels, or another reviewer’s conclusions in independent packets.
- Treat missing evidence as `unresolved`, not pass or fail.
- Do not alter or stage unrelated worktree changes.
- Do not merge PR #1 or install/promote candidates in this task.

## Output

- `skills/review-skill-candidate/`
- `research/evaluations/skill-review-process/`
- `research/reviews/PR-001/`
- Candidate, technique, ledger, and dashboard-source updates only where required by repository governance

## Validation

Run skill validation, unit and schema tests, deterministic bundle validation, independent forward reviews, dashboard/data checks if canonical records change, secret/path scans, and scoped whitespace checks. Report Codex-desktop forward-test evidence separately from untested ChatGPT transfer.
