# Explore Approaches working specification

## Professional prompt

```text
Role: Act as a Codex skill designer and evidence-governed evaluation engineer.

# Goal
Create a repository-local `explore-approaches` prototype that turns workspace-grounded goals into decision support without silently implementing an option. Define a gated process for promoting the candidate through GitHub and installing it in `~/.codex/skills` only after recorded evaluation and post-evaluation human approval.

# Context
Follow the repository's existing `skills/`, `research/skill-candidates/`, evaluation, and ledger conventions. Preserve all unrelated working-tree changes. Treat the supplied Advisory Mode Review as a proposed intervention, not efficacy evidence.

# Success criteria
- The skill has a precise trigger, non-trigger, advice-only authority boundary, concise workflow, inspectable output, failure fallbacks, and validation.
- Baselines include the raw request, a minimal advisory instruction, the current `professionalize-prompt`, and the candidate.
- Evaluation checks option distinctness, workspace grounding, baseline inclusion, tradeoffs, recommendation traceability, countercases, reversible testing, authority restraint, verbosity, latency, and cost.
- Promotion requires a frozen candidate, fresh held-out evidence, explicit human approval, a scoped GitHub change, post-merge verification, canary installation, and recoverable rollback.

# Constraints
Do not claim behavioral efficacy from static checks or development forward tests. Do not push, open a pull request, or install the candidate before the promotion gate is satisfied. Do not modify or stage unrelated work.

# Output
Create the prototype skill, UI metadata, technique and candidate records, evaluation protocol and fixtures, deterministic contract checker and tests, promotion approval schema, and GitHub-to-root installation runbook. Update required research ledgers with proposal or direct-observation states.

# Validation
Run `quick_validate.py` in an isolated PyYAML environment, run the deterministic test suite, inspect the scoped diff, and independently forward-test representative requests without leaking expected answers.
```
