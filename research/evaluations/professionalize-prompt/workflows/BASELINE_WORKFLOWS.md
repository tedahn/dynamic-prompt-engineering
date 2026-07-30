# Baseline and ablation workflows v1

All workflows use identical fixture data, target surface, tools, settings, and execution authority. A fresh executor means a separate context that receives only the frozen transformed prompt and authorized fixture artifacts.

## Baselines

### B00_RAW_1CALL — raw request

Send the request and authorized context directly to the executor. Do not add a rewrite instruction. This measures current model-native behavior.

### B01_STATIC_MIN_1CALL — fixed minimal contract

Prepend one frozen instruction: identify the requested outcome, supplied context, explicit constraints, required output, and proportionate validation; preserve facts; do not invent missing consequential details; then execute. Do not use domain-specific guidance or an adaptive question policy. This is the adoption baseline.

### B02_SHAM_2CALL — two-call control

A transformer returns the original request and context unchanged inside fixed delimiters. A fresh executor performs it. This controls for call count, context boundary, and executor separation without professionalization.

### B03_PRO_PROMPT_2CALL — frozen skill prompt-only

Run snapshot `professionalize-prompt@2026-07-28-eec246d1` in prompt-only mode. Give only its professional prompt and authorized artifacts to a fresh executor. This is the primary transformation-effect condition.

### B04_PRO_INLINE_1CALL — frozen default prompt-plus-execute

Run the same snapshot in its default mode and capture both the generated professional prompt and result. This is the end-to-end deployed condition.

### B05_HUMAN_SPEC_UPPER — blinded human reference

A human expert writes a prompt using the frozen rubric without seeing candidate outputs. A fresh executor runs it. Use only on a preregistered calibration subset as a diagnostic ceiling.

## One-component ablations

- `A01_NO_ADAPTIVE_STRUCTURE`: remove the adaptive prompt-design section; retain a compact outcome sentence.
- `A02_NO_CLARIFY_GATE`: never ask; use labeled assumptions or a blocker.
- `A03_NO_PRESERVE_GUARD`: remove explicit preservation/no-invention rules. Run only on synthetic fixtures.
- `A04_NO_DOMAIN_ADAPT`: remove domain-specific success and validation guidance.
- `A05_NO_VALIDATION`: remove final prompt and execution checks.
- `A06_NO_MODE_CONTRACT`: always use prompt-plus-execute regardless of explicit user mode. Run only as a negative-control safety test.
- `A07_NO_MODEL_REFERENCE`: do not load the GPT-5.6 prompting reference.

Each ablation must be materialized as its own immutable skill bundle before a run; runtime paraphrases are not reproducible enough for causal claims.
