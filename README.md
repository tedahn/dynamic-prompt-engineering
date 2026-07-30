# Dynamic Prompt Engineering in Execution

This repository is a governed research workspace for deciding which modern prompt-engineering techniques deserve to become reusable Codex skills.

The working thesis is deliberately narrow: a technique should become a skill only when it supplies a repeatable trigger, workflow, artifact contract, safety boundary, and measured improvement over a simpler baseline. Useful advice that does not meet that bar remains guidance rather than becoming another skill.

## Current state

- Workspace type: `research`
- Initialized: 2026-07-28
- Decision owner: `Project owner (identity unresolved)`
- Target ChatGPT plan, Project memory mode, collaborators, and connectors: `Unknown`
- Consequential adoption or new-skill promotion is blocked until a named owner approves it.
- No ChatGPT Project, upload, connector, or external integration was created by this repository setup.

## Start here

1. Read `research/RESEARCH_BRIEF-prompt-techniques-as-skills.md`.
2. Open `dashboard/index.html` for the visual research, workflow, and evaluation state.
3. Review `research/SURFACE_REGISTRY.md` before making model-current claims.
4. Use the records in `research/ledgers/` for claims, sources, assumptions, evaluations, and changes.
5. Review `research/DYNAMIC_PROMPTING_TECHNIQUES.md` and the frozen evaluation lab in `research/evaluations/professionalize-prompt/`.
6. Review the governed state-evolution process in `research/evaluations/codex-stateful-loop/`; its local demo is model-free and live cells require a separate approval record.
7. Execute the frozen `research/NEXT_ACTION-001.md` pilot through preflight and scored cells; its development result cannot authorize adoption.
8. For a ChatGPT Project, complete the local safety check and follow `chatgpt-project/UPLOAD_MANIFEST.md` manually.

## Repository map

- `chatgpt-project/`: validated, copy-ready ChatGPT Project initialization pack.
- `research/`: current brief, plan, surface registry, technique taxonomy, next action, and live ledgers.
- `skills/context-composer/`: working repository-local T-005 candidate; validated mechanically but intentionally uninstalled.
- `research/evaluations/professionalize-prompt/`: immutable skill snapshot, baseline/ablation workflows, 45 fixtures, rubrics, score ledgers, and deterministic harness.
- `research/evaluations/codex-stateful-loop/`: event-sourced context loop, six evaluation conditions, state schemas, 12 development episodes, guarded Codex adapter, human promotion/rollback gates, and tests.
- `dashboard/`: offline visual observatory plus a reproducible adapter from canonical research records.
- `templates/`: local records for technique profiles and skill candidates.
- `AGENTS.md`: durable instructions for agents working in this repository.

## Candidate lifecycle

`discovered -> sourced -> specified -> evaluated -> approved -> promoted`

A candidate may instead become `guidance-only`, `deferred`, `rejected`, or `retired`. Cross-model or cross-surface claims require separate evidence; transfer is never assumed.

## Manual ChatGPT Project handoff

Repository initialization does not create or configure a ChatGPT Project. Project creation, settings, project-only memory availability, uploads, membership, and connectors remain manual. Run `chatgpt-project/handbook/PRE_UPLOAD_SAFETY.md` before any upload or connection.
