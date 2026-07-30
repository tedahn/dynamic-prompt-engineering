# Explore Approaches lifecycle automation specification

## Professional prompt

```text
Role: Build an evidence-governed release engineer for a Codex skill candidate.

# Goal
Automate the complete explore-approaches lifecycle: freeze a candidate, consume a human-authored private holdout, run matched B00/B01/B02/C01 trials through isolated adapters, blind and grade results, classify evidence as promotable/reject/inconclusive, obtain a post-result named-human authorization, reconstruct a scoped change in a clean Git worktree, push and merge a reviewed GitHub pull request, install the immutable merged skill into `~/.codex/skills`, run a fresh-process canary, and roll back automatically on failure.

# Success criteria
- Every stage is resumable, idempotent, content-addressed, and fail-closed.
- Missing telemetry, incomplete trials, insufficient task-cluster coverage, provisional-only grading, contamination, runtime drift, or unresolved disagreement yields inconclusive or invalid evidence, never promotion.
- Promotion requires zero critical candidate failures, every configured quality/resource/domain threshold, human-final review, and an unexpired cryptographically verified approval bound to the exact evidence and candidate manifest.
- Git promotion never stages the dirty source tree: it copies approved regular files and reconstructs approved ledger/taxonomy records in a clean checkout.
- Installation invokes the configured system skill installer at the immutable merged commit into isolated staging, verifies the full approved manifest and installed subtree, creates a recoverable backup, canaries in a fresh process, and restores the backup on failure.

# Constraints
The model and harness may classify evidence and prepare approval material but may never identify themselves as the human approver, create a human signature, weaken frozen thresholds after holdout reveal, waive critical failures, publish private holdouts, force-push, bypass branch protection, overwrite an unbacked-up root skill, or treat unavailable data as a zero score.

# Output
Create a standard-library Python automation package, CLI, configuration, JSON schemas, deterministic tests, dry-run fixtures, updated protocol/runbook/candidate records, and synchronized evidence ledgers. Keep provider/model commands, credentials, pricing, signer identity, and volatile tool paths in configuration.

# Validation
Run structural skill validation, unit and adversarial tests, a model-free end-to-end dry run, ledger integrity checks, JSON/Python validation, git diff checks, and independent architecture/security reviews. Record remaining human inputs and unavailable live integrations honestly.
```

## Authority model

Automation may collect evidence, compute a deterministic classification, prepare signature payloads, create and merge a pull request, install, canary, and roll back only within the permissions in a valid post-result human approval. It cannot author the private holdout, mark provisional grades human-final, sign either custody or promotion evidence, waive a hard gate, or expand the approved target.

## State model

`draft → frozen → holdout-ready → running → grading → promotable|rejected|inconclusive|invalid → awaiting-human-approval → approved → promoting → pr-open → merged → installing → canary → active`

External or configuration failures become resumable `blocked` events. Safety failure after installation becomes `quarantined → rolled-back`. Every transition records hashes, idempotency keys, actor role, timestamps, and receipts in a SQLite WAL event store.

## Executable components

- `automation/evaluation.py`: signed external holdout custody, arm-material and runtime-identity binding, immutable matched-cell plans, isolated request-bound adapters, raw request/response hash verification before resume/blinding/summary, bounded retry accounting, exact rubric-dimension aggregation, grouped blinding, task-cluster coverage/bootstrap intervals, and human-final summary generation.
- `automation/event_store.py` and `automation/orchestrator.py`: compare-and-swap transitions and a tamper-evident hash chain.
- `automation/promotion.py`: SSH verification, exact-base clean-clone reconstruction, recovery-time clone/diff/tree revalidation, canonical GitHub review/merge re-query, full-manifest verification, exact-ref installer-helper staging, locked crash-recoverable install, active-tree revalidation, fresh canary, quarantine, and rollback rehearsal.
- `scripts/automate_lifecycle.py`: resumable subcommands plus `auto`, which advances until it reaches honest missing evidence or human authority.

## Required live configuration

Before a live run, set subject, grader, and canary adapter argv plus the subject adapter/provider/model/settings identity; explicitly allow only required environment variables; configure the SSH allowed-signers path and expected identity in operator-controlled files outside the repository and run directory; confirm the GitHub repository and protected branch; replace the committed GitHub automation-actor and required-reviewer placeholders with the exact automation login and a non-empty independent-reviewer allowlist; configure the system skill-installer path and canary validator; and choose private holdout/run paths outside this repository. Empty or placeholder adapter, signer, reviewer, validator, or runtime settings intentionally block. The operator-controlled configuration and reviewer policy are frozen into the signed evidence. The automation freezes executable/script hashes, requires the subject response to echo the exact runtime with `fresh_session: true`, and never creates the approval signature.

## Human handoff and automatic continuation

The first `auto` run stops for human-final grades and review. After conclusive results it rehearses rollback and emits `promotion-approval.unsigned.json`. A named human fills the timestamps and identity, inspects the bound evidence, exports the canonical payload with `approval-payload`, signs it using `ssh-keygen -Y sign`, and attaches the detached signature with `attach-signature`. Rerunning `auto --approval ... --apply` creates the scoped pull request; the same command can wait for or later observe independent GitHub review, merge, install, canary, and activate without further model judgment.
