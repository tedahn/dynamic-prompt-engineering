# Codex stateful evolution lab

This package evaluates whether a Codex agent becomes more useful when it can build and maintain durable context across ordered episodes. It is an evaluation harness, not an autonomous production updater.

## Current state

- Architecture and local mechanics: implemented
- Development episode bank: implemented with synthetic data
- Fresh holdout: not authored or committed; must be generated and escrowed independently
- Provider-backed Codex runs: not authorized for this study
- Behavioral efficacy: Unknown
- Durable state promotion: blocked until a full blinded study and named-human approval

## Loop

`observe → propose → branch state → run development/regression episodes → freeze candidate → leakage scan → fresh holdout → candidate canary → human review → activate or rollback`

Codex can act as the subject, optimizer, grader, and adjudicator, but every role runs in a fresh isolated context. Role outputs are linked through content-addressed artifacts rather than shared conversation history.

## Local mechanical demo

The demo exercises persistence, a guarded context proposal, context selection, smoke-plan generation, and event/artifact audit without calling a model. The test suite separately exercises evaluation, approval, promotion, and rollback boundaries.

```sh
python3 research/evaluations/codex-stateful-loop/scripts/state_loop.py demo --instance /tmp/codex-state-loop-demo
python3 research/evaluations/codex-stateful-loop/scripts/state_loop.py status --instance /tmp/codex-state-loop-demo
python3 research/evaluations/codex-stateful-loop/scripts/state_loop.py audit --instance /tmp/codex-state-loop-demo
```

Promotion and rollback are executable but deliberately unreachable from the demo. Promotion requires an independently produced eligible full-study summary, fresh sealed-holdout attestations, human-final grades, canary evidence, tested rollback evidence, a named-human approval, and an unchanged active-state version:

```sh
python3 research/evaluations/codex-stateful-loop/scripts/state_loop.py promote \
  --instance <instance> --epoch-id <full-epoch-id> --approval <promotion-approval.json>
python3 research/evaluations/codex-stateful-loop/scripts/state_loop.py rollback \
  --instance <instance> --approval <rollback-approval.json>
```

The approval contracts are `schemas/promotion-approval.schema.json` and `schemas/rollback-approval.schema.json`. Rollback can point only to an accepted ancestor and uses compare-and-swap against the active snapshot and version.

## Tests

```sh
python3 -m unittest discover -s research/evaluations/codex-stateful-loop/tests -p 'test_*.py'
```

## Live execution boundary

`codex_adapter.py` is preflight-only. It validates a prepared episode selection only when given a separate approval JSON whose exact cell IDs and ceiling, plan hash, runtime-profile hash, provider-processing acknowledgment, named-human approver, stage, and expiry all match. No approval file is committed, and the adapter exposes no execution subcommand.

```sh
python3 research/evaluations/codex-stateful-loop/scripts/codex_adapter.py preflight \
  --instance <instance> --epoch <epoch-id> \
  --cli-path /Applications/ChatGPT.app/Contents/Resources/codex \
  --codex-home <isolated-codex-home> --approval <approval.json>
```

The adapter reuses the frozen runtime profile referenced in `config/loop-v1.json` and checks the CLI binary, version, isolated ChatGPT authentication, feature controls, empty read-only working directory, and the command template that a future runner would use. It invokes only `--version`, `login status`, and `features list`; it never invokes a model. The repository kill switch remains closed (`live_execution.authorized: false`), so the real study intentionally blocks before these readiness checks until a separate authorization change is approved.

The approval format is frozen in `schemas/run-approval.schema.json`. Approval manifests must stay outside this research package and are valid for at most 72 hours. Adding a provider-backed execution command requires a separately reviewed change; preflight approval does not authorize grading, state promotion, or external side effects.

## Canonical versus derived state

- Canonical runtime log: `<instance>/state.db` (SQLite WAL)
- Immutable artifacts: `<instance>/artifacts/sha256/`
- Review exports: `<instance>/exports/*.jsonl`
- Repository fixtures, schemas, prompts, and config: frozen study inputs
- Dashboard: derived view only

See `ARCHITECTURE.md` for state boundaries and `PROTOCOL.md` for experimental design.
