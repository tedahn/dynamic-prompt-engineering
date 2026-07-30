# Local skill landscape

- **Observed:** 2026-07-28
- **Scope:** 132 local skill entrypoints inventoried; 19 prompt/workflow-oriented skills compared
- **Refresh trigger:** local skill installation, removal, or material revision

## Anchor and adjacent skills

- `~/.codex/skills/professionalize-prompt/SKILL.md`: intent normalization, specification, execution modes, domain adaptation, and validation.
- `<local-checkout>/skills/initialize-chatgpt-project/SKILL.md`: routing, deterministic scaffolding, evidence ledgers, source freshness, and approval gates.
- `~/.codex/skills/.system/skill-creator/SKILL.md`: skill authoring and packaging reference.
- `~/.codex/skills/ce-brainstorm/SKILL.md`, `ce-ideate`, `ce-plan`, `ce-work`, and `ce-optimize`: staged divergence, planning, execution, measurement, and iteration.
- `~/.codex/skills/web-researcher/SKILL.md` and `best-practices-researcher`: source-driven retrieval and synthesis.
- `~/.codex/skills/document-review/SKILL.md` and `adversarial-document-reviewer`: review routing and challenge passes.

## Reusable design patterns already present

1. Intent normalization that preserves constraints and infers only low-risk details.
2. Scope routing that chooses a mode or level of ceremony before work.
3. Grounding in canonical artifacts before generation.
4. Diverge, critique, reject explicitly, and converge.
5. Artifact pipelines from requirements through execution and review.
6. Evidence hierarchy, freshness, uncertainty, and stopping rules.
7. Evaluation loops: fixture, baseline, isolated change, metric/gate, retain or revert.
8. Progressive disclosure through lean triggers, references, and scripts.

## Gaps worth researching

The clearest gaps are a prompt linter, context composer, exemplar curator, output-contract engineer, tool-contract engineer, prompt-eval lab, model-surface adapter, and dynamic skill router. These are research candidates, not installation recommendations; each must be checked for overlap with existing skills and model-native behavior.
