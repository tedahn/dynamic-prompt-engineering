# Skill candidate — review-skill-candidate

- **Technique ID:** T-020
- **Candidate version:** review-skill-candidate-v0.1.0
- **Lifecycle:** repository-local prototype; not installed or promoted
- **Owner / approver:** Ted Ahn
- **Review date:** 2026-08-30

## Contract

- **Trigger:** Requests to review a research-backed skill, prompt workflow, evaluation harness, candidate package, or pull request for merge readiness; prepare independent reviewer context; reconcile reviews; or decide what evidence a human needs before merging.
- **Non-triggers:** Ordinary narrow code review that does not need the research or skill governance; behavioral-efficacy evaluation; implementation of review findings; PR merge; skill installation or production adoption.
- **Inputs and evidence:** Repository and frozen base/head refs, one requested decision, named decision owner, canonical policies, changed artifacts, known validation, authority, stop rules, and reviewer identities.
- **User-visible outcome:** A frozen evidence packet, isolated role assignments, structured reviewer submissions, hash-bound adjudication, deterministic validation summary, and a narrow named-human decision request.
- **Artifacts or side effects:** Repository-local review bundle only. The default workflow is read-only against the target and performs no merge, installation, deployment, or external communication.
- **Authority boundary:** Models may prepare, review, critique, adjudicate evidence, and draft a decision packet. Only the named human may decide merge; later promotion and adoption gates remain separate.
- **Target surface:** Repository-local Codex prototype. Prompt packets are portable to separate ChatGPT chats, but ChatGPT transfer is untested.

## Workflow

Classify one decision; open a proposed human gate; freeze and hash the target; build a bounded evidence context; assign three isolated reviewer lenses; collect schema-valid findings; freeze submissions; independently adjudicate evidence and conflicts; run deterministic bundle validation; request the narrow human decision; reopen on target or policy drift.

## Distinctiveness

The candidate operationalizes review independence, provenance, target integrity, decision separation, artifact schemas, and human authority. A standard code reviewer remains preferable if one general review catches the same material defects with less time, context, cost, and maintenance.

## Evaluation and evidence

- **Protocol:** `research/evaluations/skill-review-process/PROTOCOL.md`
- **Synthetic fixtures:** `research/evaluations/skill-review-process/fixtures/fixtures-v1.jsonl`
- **Deterministic tests:** `research/evaluations/skill-review-process/tests/test_review_bundle.py`
- **Development target:** GitHub PR #1 frozen at head `8371f0f9634bf86e3417bae09772418034239969`.
- **Current result:** The skill and bundle schemas validate; eight unit tests cover target freeze, overwrite refusal, missing-role failure, provisional clean review, open-P1 gating, duplicate identity, stale hashes, and packet drift. Three isolated reviewers and a separate adjudicator completed the frozen PR #1 development cycle. Seven findings were upheld: three open P1 and four open P2. The computed merge gate is `changes_required`; the human decision remains pending.
- **Remediation status:** Targeted mechanical validation now addresses all seven PR #1 findings in the working tree, with 25 pilot, 17 context-composer, and 44 explore-approaches tests passing. These checks are not review closure evidence. PR #1 remains immutable; a fresh exact-head review is still required before merge.
- **Open gate:** Run a new frozen-head review before any merge decision. Separately run a fresh blinded matched-budget B0/B1/C1/C2 holdout with resource measures and independent human grading before promotion or installation.

## Operations

- **Installation scope:** None until fresh held-out evidence and post-result named-human approval.
- **GitHub target:** Draft PR #1 in `tedahn/dynamic-prompt-engineering`.
- **Root destination after approval and merge:** `~/.codex/skills/review-skill-candidate`.
- **Review signals:** Critical-defect recall, unsupported blocking findings, evidence-anchor validity, coverage, contamination, latency, tokens, cost, reviewer effort, adjudication effort, trigger collision, and reopen rate.
- **Canary:** Explicit invocation on low-risk repository-local candidate reviews with a human merge owner.
- **Rollback:** Remove or quarantine the installed copy, preserve raw/static review paths, and keep prior review bundles immutable.
- **Retirement:** Retire or compose into a general reviewer if a simpler single-reviewer workflow matches recall and auditability with lower overhead.
