# Skill candidate — explore-approaches

- **Technique ID:** T-019
- **Candidate version:** explore-approaches-v0.1.0
- **Lifecycle:** repository-local prototype; not installed or promoted
- **Owner / approver:** Ted Ahn
- **Review date:** 2026-08-29

## Contract

- **Trigger:** Suggestions, options, strategies, solution paths, tradeoffs, or recommendations about how to approach a goal in the current topic or workspace.
- **Non-triggers:** A selected solution needing implementation; unconstrained brainstorming; consequential decisions reserved for an authorized person.
- **Inputs and evidence:** User goal, relevant workspace artifacts, constraints, prior decisions, evidence, unknowns, authority, and decision horizon.
- **User-visible outcome:** An inspectable comparison, recommendation when warranted, strongest countercase, and reversible next test.
- **Artifacts or side effects:** Decision support only by default; no file mutation or external action.
- **Authority boundary:** Advice never implies approval to act. Implementation requires a separate explicit request and applicable workflow.
- **Target surface:** Repository-local Codex prototype. Other model and product surfaces are untested.

## Workflow

Frame the decision; inspect relevant evidence; ask only decision-changing questions; generate three to five distinct options including a simple baseline; compare criteria and countercases; recommend or identify decisive missing evidence; propose a reversible falsification test; validate and stop.

## Distinctiveness

The candidate combines workspace inspection, option diversity, baseline inclusion, consistent tradeoff analysis, counterevidence, falsification, and an advice-only boundary. It remains redundant if a minimal advisory prompt or `professionalize-prompt` achieves equivalent outcomes with less overhead.

## Evaluation and evidence

- **Protocol:** `research/evaluations/explore-approaches/PROTOCOL.md`
- **Development fixtures:** `research/evaluations/explore-approaches/fixtures/fixtures-v1.jsonl`
- **Static validation:** Contract checker plus skill-creator `quick_validate.py`.
- **Current result:** Skill-creator validation, deterministic contract checks, and three candidate unit tests pass. Forty-eight model-free lifecycle and adversarial tests plus an eight-check end-to-end rehearsal also pass, covering signed plan and custody, exact runtime and raw-artifact binding, blind reconstruction, evidence-manifest-bound grading, deterministic classification, recovery receipts, allowlisted reviewed-merge evidence, helper-staged atomic installation, canary, and verified rollback. Four independent development requests found one technical calibration/test-isolation defect; revision R1 corrected the contract and one fresh technical request passed the diagnosed gates. These results are diagnostic and cannot authorize promotion.
- **Forward-test record:** `research/evaluations/explore-approaches/results/forward-test-2026-07-29.md`.
- **Open gate:** Fresh held-out evaluation, resource measurements, independent human review, and explicit post-evaluation promotion approval.

## Operations

- **Installation scope:** None until the promotion process completes.
- **GitHub target:** `origin` at `https://github.com/tedahn/dynamic-prompt-engineering-in-execution.git` through a scoped branch and reviewed pull request.
- **Root destination after approval and merge:** `~/.codex/skills/explore-approaches`.
- **Review signals:** Hard-gate failures, task-quality rubric, pairwise preference, latency, tokens, cost, reviewer effort, trigger collision, and user override rate.
- **Canary:** Explicit invocation on low-authority, non-sensitive advisory tasks.
- **Rollback:** Quarantine the installed copy and restore the timestamped prior version; retain raw and minimal-prompt baselines.
- **Promotion runbook:** `research/evaluations/explore-approaches/PROMOTION.md`.
- **Automation runbook:** `research/evaluations/explore-approaches/AUTOMATION_RUNBOOK.md`.
- **Automation:** `research/evaluations/explore-approaches/scripts/automate_lifecycle.py` implements the resumable fail-closed path from signed arm/runtime freeze and hash-verified evaluation artifacts through signed approval, exact-diff clean-clone pull request, canonical reviewed-merge recovery, full-manifest verification, exact-ref system-installer staging, atomic activation, canary, and rollback.
- **Human boundary:** Models may prepare evidence and unsigned signature material but cannot author or sign holdout custody, create the human-final decision, sign promotion authority, or supply independent GitHub approval.
- **Current readiness:** Model-free lifecycle and adversarial tests pass. Live adapters, signer configuration, a fresh private holdout, human-final adjudication, and post-result approval remain unavailable; the candidate is not promotable or installed.
