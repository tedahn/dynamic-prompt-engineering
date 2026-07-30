# Review artifact contract

## Bundle layout

```text
review-bundle/
├── manifest.json
├── context-pack.md
├── gate.md
├── assignments/
│   ├── evidence-methodology.md
│   ├── engineering-reproducibility.md
│   └── skill-safety-operations.md
├── submissions/
│   └── <role>.json
├── adjudication/
│   └── adjudication.json
├── human-decision/
│   └── decision.json
└── validation-summary.json
```

`init` creates the manifest, context pack, proposed gate, assignments, and empty output directories. Reviewers create submissions from the template. The adjudicator works only after all required submissions exist. The human decision is last.

## Finding requirements

Each finding contains:

- stable ID namespaced by role;
- P0–P3 severity and `open`, `resolved`, `accepted_risk`, `rejected`, or `unresolved` status;
- concise title and falsifiable claim;
- impact on the requested decision;
- evidence anchors with repository-relative path and line range;
- recommendation and strongest counterevidence;
- high, medium, or low confidence.

Use an empty findings array for a clean review, but still declare coverage and limitations. Never omit a required role to imply zero findings.

## Integrity requirements

- All artifacts repeat the review ID and immutable target hashes.
- Reviewer IDs are unique and `independent_context` is true.
- Submission filenames match reviewer roles.
- Adjudication records exact SHA-256 values for every submission.
- A human decision names an actor of type `human`, repeats the target, records conditions and reversal evidence, and cannot be generated as approved by the validator.
- Validation summaries report merge eligibility, behavioral efficacy, promotion readiness, and installation readiness as separate fields.

## Templates and schemas

- `assets/templates/review-submission.json`
- `assets/templates/adjudication.json`
- `assets/templates/human-decision.json`
- `assets/schemas/review-submission.schema.json`
- `assets/schemas/adjudication.schema.json`
- `assets/schemas/human-decision.schema.json`

Copy a template into the bundle before editing. Validate with `scripts/review_bundle.py validate --repo-root <repo> --bundle <bundle>`.
