# Skill candidate — model-aware professionalize-prompt

- **Candidate ID and version:** `professionalize-prompt-model-aware@2026-07-30`
- **Related technique IDs:** `T-004`; uses `T-014` evaluation controls
- **Proposed skill name:** `professionalize-prompt` (revision, not a separate skill)
- **Status:** prototype
- **Owner / approver / review date:** Ted Ahn / promotion approver unassigned / 2026-08-30

## Contract

- **Trigger:** Rough-request transformation plus a named/current GPT model, reasoning level, surface, or material capability distinction.
- **Non-triggers:** Model-independent tasks; generic model questions without prompt transformation; inconsequential wording changes; unsupported provider migration.
- **Inputs and evidence:** User request and artifacts, active surface, actually callable GPT models when observable, exact official model guidance, operational constraints, and task-specific validation criteria.
- **User-visible outcome:** The shortest reliable execution-ready prompt and completed result under the existing execution-mode contract.
- **Artifacts or side effects:** Prompt/result artifacts requested by the user; internal model profile and evaluation matrix remain hidden unless decision-relevant or requested.
- **Authority and confirmation boundaries:** Model-aware wording cannot broaden authority. External writes, destructive work, purchases, large paid evaluations, promotion, and installation require their existing approvals.
- **Target models and surfaces:** Available GPT models on Codex, ChatGPT, Work, or API. Availability and labels are verified per surface; transfer is not assumed.

## Workflow

Recover the task contract; decide whether model differences matter; resolve a dated model profile from official sources and actual surface availability; adapt only affected prompt layers; execute under the original authority; validate the result; and, for comparative claims, isolate prompt, model, reasoning, surface, tool, and optional-capability effects.

## Distinctiveness

This is not a new skill. It extends the existing request-to-prompt workflow at the point where model capabilities can change execution. A concise instruction is insufficient for volatile capability resolution, surface-label separation, callable-model discovery, and controlled multi-axis evaluation, while a second skill would create overlapping triggers and routing ambiguity.

## Evaluation and evidence

- **Baseline:** immutable `professionalize-prompt@2026-07-28-eec246d1`.
- **Candidate:** `skills/professionalize-prompt/`; manifest in `research/evaluations/professionalize-prompt/candidates/2026-07-30-model-aware/manifest.json`.
- **Eval:** `E-027`; no behavioral run yet.
- **Graders:** deterministic contract and artifact checks, blinded comparative human review, and task-specific outcome checks.
- **Regressions:** prompt bloat, unnecessary model lookup, fabricated capability claims, surface-label mismatch, increased latency/cost, lost constraints, or authority expansion.
- **Held-out gate:** fresh cases are required because the existing holdout is readable and cannot validate this challenger.
- **Decision:** prototype only; efficacy and transfer remain `Unknown`.

## Operations

Keep the repository candidate uninstalled. Refresh official sources before current claims, model-comparison runs, or 30 days after the 2026-07-30 snapshot. Monitor prompt length, unnecessary lookups, task success, critical regressions, latency, tokens, and cost. Roll out only after `E-027`, held-out replication, and named-human approval. Roll back by restoring the frozen 2026-07-28 skill package and removing the model-aware candidate from active discovery. Retire or simplify the intervention if model-native behavior matches it without measurable regressions or maintenance burden.
