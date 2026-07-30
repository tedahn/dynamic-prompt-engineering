Initialize the Dynamic Prompt Engineering in Execution research workspace.

# Decision

Determine which modern prompt-engineering technique families should be prioritized for reusable Codex skill prototypes, which should remain guidance, and which should be rejected or deferred.

# Surface

- Decision owner: Project owner (identity unresolved)
- Proposed first review: 2026-08-04
- Target model and ChatGPT plan: Unknown; verify before model-current claims
- Initial anchor: the supplied `professionalize-prompt` skill
- Comparison scope: model and product surfaces supported by current first-party documentation; evaluate each surface separately

# Starting thesis

A technique warrants a skill only when it adds a repeatable trigger, workflow, artifact contract, authority boundary, and measured advantage over a simpler baseline. Generic advice without operational leverage should remain guidance. Treat this as a forecast/opinion to test, not a fact.

# Options

1. Prototype a technique as a standalone skill.
2. Compose it into an existing domain skill.
3. Retain it as model- or surface-specific guidance.
4. Defer or reject it.
5. Do nothing until evidence improves.

# Scope and evidence

Include current first-party model guidance, primary research papers and artifacts, direct local observations, evaluation design, context engineering, tool use, verification, prompt optimization, and multi-agent patterns. Exclude jailbreaks, hidden-chain-of-thought extraction, prompt marketplaces, unsupported social-media tricks, and claims that cannot be traced upstream.

For model/product claims, require a first-party source, exact surface, `as_of` date, and refresh trigger. For technique claims, record the tested model, task, dataset, comparison, and limitations. Do not generalize benchmark gains across models or workflows. Promotion requires a representative baseline-versus-candidate evaluation, no unacceptable regression, a rollback path, and named human approval.

# Required output

Create separate, save-ready artifacts:

- `RESEARCH_BRIEF-prompt-techniques-as-skills.md`
- `RESEARCH_PLAN-[date].md`
- `TECHNIQUE_TAXONOMY.md`
- one `TECHNIQUE_PROFILE-[slug].md` for each of the three highest-value candidates
- populated `claims.csv`, `sources.csv`, `assumptions-forecasts.csv`, `eval-cases.csv`, and `change-log.csv`
- `NEXT_ACTION-001.md`
- `DECISION-[id]-DRAFT.md` only if the predeclared evidence threshold is already met

First decompose `professionalize-prompt` into separately testable interventions. Then map documented technique families, strongest contrary evidence, transfer limits, and maintenance burden. Rank candidates by expected user value, distinctiveness from model-native behavior, testability, safety, and maintenance cost.

Commit the highest-value unresolved uncertainty to `NEXT_ACTION-001.md` with Do, Done when, Verify, owner, deadline, run budget, stop rule, approval needed, and the decision it unlocks. If no named owner is assigned, mark execution blocked after producing the research design. Do not implement or install a new skill in this kickoff.
