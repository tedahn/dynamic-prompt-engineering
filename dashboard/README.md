# Prompt Research Observatory

Open `index.html` directly, or serve the repository root and visit `/dashboard/`.

```sh
python3 -m http.server 4173
```

The committed `data.js` is a truthful snapshot of the repository artifacts. Refresh it after research or evaluation records change:

```sh
node dashboard/scripts/build-data.mjs --write
```

Check that the committed snapshot still matches its sources without modifying files:

```sh
node dashboard/scripts/build-data.mjs --check
node --test dashboard/tests/dashboard.test.mjs
```

## Evidence rule

An empty behavioral score is rendered as **Unknown**, never `0`. The static design audit and evidence-readiness review describe the frozen skill design; they are not behavioral efficacy measurements.

The Codex state-evolution panel follows the same rule: its architecture, local mechanics, conditions, and planned run counts are visible, while live authorization and behavioral efficacy remain explicitly absent. Its canonical records live under `research/evaluations/codex-stateful-loop/`.

## Source of truth

The dashboard is a generated view. Edit the research records and ledgers, then rebuild; do not treat `data.js` as the canonical research record.
