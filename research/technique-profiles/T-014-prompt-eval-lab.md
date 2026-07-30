# Technique profile — prompt evaluation lab

- **Technique ID:** T-014
- **Lifecycle state:** sourced
- **Owner:** Project owner (identity unresolved)
- **As of:** 2026-07-28
- **Review trigger:** target model, grader, evaluation platform, cost model, or production workflow changes

## Intended behavior

Turn a prompt or skill hypothesis into a reproducible baseline-versus-candidate decision with representative fixtures, calibrated graders, regressions, budget, approval, and rollback. Its value is enabling trustworthy adoption decisions rather than directly improving a task output.

## Trigger and non-trigger

Trigger before tuning, promoting, or materially changing prompts, context, tools, or skills; after a recurring failure; or when a claimed improvement lacks a baseline. Do not trigger for inconsequential one-off wording where evaluation cost cannot affect a decision.

## Intervention

Produce an eval case set, frozen baseline, candidate version, target surface/settings, grader mix, pass and regression thresholds, repeated-trial budget, held-out check, decision record, rollout, and rollback.

## Evidence map

- OpenAI optimizer and evaluation guidance requires representative data/graders and warns that optimized prompts can regress on particular inputs (`C-003`, `S-005`, `S-006`).
- Anthropic describes combining code-, model-, and human-based graders over outcomes and transcripts (`C-006`, `S-010`).
- APE, DSPy, and TextGrad show optimization potential in tested systems while raising transfer, leakage, and stability questions (`C-017`, `S-031`–`S-033`).

## Failure and transfer analysis

Risks include fixture leakage, overfitting, biased model judges, verbosity preference, weak human calibration, noisy trials, moving model versions, high cost, and metrics that do not predict user value.

## Evaluation readiness

Dogfood the lab on `research/NEXT_ACTION-001.md`. It must preserve all conditions and raw outcomes, distinguish specification from execution quality, flag critical authority/factuality regressions, and produce the same adoption decision under an independent review.

## Skill recommendation

Highest enabling priority, but prototype only after the named owner approves the target surface, data boundary, and budget. Reuse existing `ce-optimize` patterns where possible rather than duplicating them.
