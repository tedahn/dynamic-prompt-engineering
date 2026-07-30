# Research workspace instructions

## Mission

Determine which prompt-engineering techniques can be encoded as reliable, maintainable skills. Optimize for falsifiable evidence and useful decisions, not for collecting prompt folklore.

## Required reading

Before substantive work, read:

1. `README.md`
2. `research/RESEARCH_BRIEF-prompt-techniques-as-skills.md`
3. `research/SURFACE_REGISTRY.md`
4. `chatgpt-project/handbook/EVIDENCE_GOVERNANCE.md`
5. `chatgpt-project/handbook/CONTINUOUS_IMPROVEMENT.md`

Read `chatgpt-project/handbook/PRE_UPLOAD_SAFETY.md` before proposing uploads, connectors, or externally shared context.

## Research rules

- Frame every investigation around a decision, a falsifiable claim, or an evaluation case.
- Use first-party model documentation for model/product-surface claims and primary papers or direct artifacts for technique claims. Secondary sources may aid discovery but do not establish decision-critical claims.
- Record volatile facts with an `as_of` date and refresh trigger in `research/SURFACE_REGISTRY.md` or a ledger.
- Separate documented guidance, observed experiment results, and inference. Use the claim states in `chatgpt-project/handbook/EVIDENCE_GOVERNANCE.md`.
- Search for failure conditions, contradictory evidence, transfer limits, cost, latency, and regressions.
- Do not treat benchmark gains on one model, dataset, or tool surface as general proof.
- Keep negative and null results.

## Skill promotion gate

Do not add or install a production skill from this repository unless a named human owner approves it after a recorded baseline/candidate evaluation. A promotable candidate must define its trigger, non-trigger, inputs, outputs, workflow, authority boundary, target surfaces, evals, failure modes, maintenance owner, review date, and rollback path.

Use `templates/technique-profile.md` and `templates/skill-candidate.md`. Update the claim, source, eval, assumption, and change ledgers in the same change.

## Stable versus volatile state

Keep durable research policy in these instructions. Keep model names, availability, reasoning controls, limits, tool surfaces, and vendor recommendations in dated research records. Never silently rewrite stable instructions after a promising single example.

## Safety and authority

Local read-only research and repository edits requested by the user are in scope. External publication, contacting people, spending money, installing or promoting skills, changing ChatGPT Project settings, uploading data, connecting sources, or destructive actions require explicit approval.
