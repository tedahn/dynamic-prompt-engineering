# Professional prompt used for this expansion

Role: Prompt-systems researcher and evaluation engineer working inside the governed Dynamic Prompt Engineering in Execution repository.

## Goal

Expand the research beyond general prompt advice toward techniques that transform a rough request into an effective prompt or dynamically adapt prompting at run time. Preserve an immutable snapshot of `professionalize-prompt`, define several reproducible baselines and component ablations, and implement a file-backed evaluation harness that retains scores without overstating efficacy.

## Context

The existing workspace contains evidence governance, a primary-source ledger, an 18-family taxonomy, and a blocked reference-skill evaluation. The anchor skill defaults to prompt-plus-execute and supports prompt-only and execute-only modes. Current owner identity and target ChatGPT/model surface remain unresolved.

## Success criteria

- Add current first-party or primary-paper techniques directly relevant to prompt rewriting, clarification, adaptive examples/context, routing, and prompt optimization.
- Snapshot the complete skill package dependency closure byte-for-byte with per-file and aggregate SHA-256 hashes.
- Define raw, static, sham, prompt-only, inline, and human-reference workflows plus one-component ablations.
- Separate prompt quality from downstream task success and use deterministic checks, blind human judgment, safety gates, cost, latency, repeated trials, held-out fixtures, and uncertainty.
- Persist fixture, run, score, audit, and decision contracts in versioned files.
- Provide deterministic validation and score-summary tools that require no external Python packages.

## Constraints

Do not call a static design score evidence of effectiveness. Do not run or claim a broad behavioral evaluation while the owner, target model/surface, runtime settings, fixture data boundary, and budget are unresolved. Do not expose holdout cases during prompt development. Do not promote or install a new skill. Keep source claims scoped to the documented model, task, and experiment.

## Output

Create a research synthesis, immutable snapshot, evaluation protocol, baseline/ablation registry, 30-development/15-holdout fixture bank, rubric, preregistration, raw score ledger, static audit, validation script, summary script, and tests. Update the workspace ledgers and navigation.

## Validation

Verify snapshot byte identity and hashes, fixture strata and uniqueness, workflow and rubric integrity, score formulas and hard gates, deterministic run planning, tests, CSV/JSON/JSONL validity, repository whitespace, and the existing ChatGPT Project pack. Report behavioral scores as `not run` until real outputs exist.
