# professionalize-prompt evaluation lab

This lab evaluates whether transforming a rough request improves the downstream result, and which components cause any improvement. It deliberately separates design quality from behavioral efficacy.

## Current status

- Frozen package: `professionalize-prompt@2026-07-28-eec246d1`
- Static design audit: 79.6/100 for specified design quality; 63.5/100 including missing evidence readiness
- Behavioral efficacy: **not run / Unknown**
- Full evaluation: blocked until a named owner approves the target surface, runtime settings, data boundary, graders, and budget
- No skill promotion or installation is authorized
- Model-aware challenger: `professionalize-prompt-model-aware@2026-07-30`; prototype only, tracked under `skills/professionalize-prompt/`, with evaluation case `E-027`

## Files

- `WORKING_SPEC.md`: professionalized request used to build this lab.
- `PROTOCOL.md`: preregistration and evaluation rules.
- `workflows/`: frozen baseline and ablation definitions.
- `fixtures/fixtures-v1.jsonl`: 30 development and 15 holdout cases.
- `fixtures/check-registry-v1.json`: exact mapping from every fixture check to its deterministic or blinded-human grader channel; adapter-required checks remain a run gate.
- `rubrics/`: behavior and static-design score contracts.
- `experiments/EXP-PP-V1-PREREG.json`: blocked full-study and deterministic 45-cell pilot plans.
- `snapshots/`: immutable source bundle and manifest.
- `candidates/`: challenger manifests that preserve provenance without changing the frozen baseline.
- `scores/`: raw score ledger and static audit.
- `scripts/eval_harness.py`: validation, deterministic run planning, and summary commands.
- `tests/test_eval_harness.py`: standard-library tests.

## Commands

```bash
python3 scripts/eval_harness.py validate
python3 scripts/eval_harness.py plan --experiment experiments/EXP-PP-V1-PREREG.json --phase pilot
python3 scripts/eval_harness.py summarize --scores scores/score-ledger.csv --baseline B01_STATIC_MIN_1CALL
python3 -m unittest discover -s tests -v
```

The `plan` and `summarize` commands print deterministic JSON/JSONL to stdout. Save their output as an immutable run artifact only after the preregistration gate is cleared.
