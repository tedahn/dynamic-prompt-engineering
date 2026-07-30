# Professional prompt: research observatory

Build a repository-local, responsive research dashboard that turns the current prompt-engineering artifacts into a truthful decision view.

## Goal

Make it easy to see, in one place, which prompting techniques are being studied, how each evaluation workflow differs, what evidence exists, what has not run, and what must happen before a skill can be promoted.

## Authoritative inputs

- `research/DYNAMIC_PROMPTING_TECHNIQUES.md`
- `research/TECHNIQUE_TAXONOMY.md`
- `research/ledgers/*.csv`
- `research/evaluations/professionalize-prompt/workflows/workflows-v1.json`
- `research/evaluations/professionalize-prompt/fixtures/fixtures-v1.jsonl`
- `research/evaluations/professionalize-prompt/scores/static-design-audit-2026-07-28.json`
- `research/evaluations/professionalize-prompt/scores/score-ledger.csv`
- `research/evaluations/professionalize-prompt/pilot-v2/experiments/EXP-PP-V2-PILOT.json`

## Requirements

1. Use a calm, editorial research-instrument aesthetic rather than a generic SaaS card grid.
2. Provide four linked views: overview, workflows, evaluations, and technique map.
3. Visualize the candidate lifecycle, baseline/candidate/ceiling workflows, ablations, fixture coverage, pilot plan, score state, and evidence ledgers.
4. Separate documented guidance, static design assessment, provisional observations, and unknown behavioral efficacy. Never render an absent score as zero.
5. Preserve the frozen skill snapshot ID and identify the adoption baseline.
6. Make workflow and technique details inspectable with keyboard-accessible controls.
7. Work offline with no external dependencies. Remain useful when opened directly from disk.
8. Include a dependency-free data adapter so later score-ledger rows can be surfaced reproducibly.
9. Include a reduced-motion path, visible focus states, semantic landmarks, adequate contrast, and responsive layouts at desktop and mobile widths.

## Constraints

- Do not imply that `professionalize-prompt` is effective: behavioral efficacy is currently unknown and the official score ledger has zero data rows.
- Do not compare static design scores with future behavioral outcome scores as though they share a scale.
- Label planning estimates and inferences explicitly.
- Keep source links repository-local and preserve existing research artifacts.

## Validation

- Verify source-derived counts and snapshot identity.
- Run syntax and data-integrity checks.
- Exercise the main view/filter interactions.
- Inspect one desktop and one mobile rendering; fix any glaring issue in one visual pass.

## Deliverables

- `dashboard/index.html`
- `dashboard/styles.css`
- `dashboard/data.js`
- `dashboard/app.js`
- `dashboard/scripts/build-data.mjs`
- `dashboard/tests/dashboard.test.mjs`
- `dashboard/README.md`
