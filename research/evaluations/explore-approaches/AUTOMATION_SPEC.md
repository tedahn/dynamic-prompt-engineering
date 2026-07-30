# Explore Approaches lifecycle automation specification

## Professional prompt

```text
Role: Build an evidence-governed release engineer for a Codex skill candidate.

# Goal
Automate the complete explore-approaches lifecycle: freeze a candidate, consume a human-authored private holdout, run matched B00/B01/B02/C01 trials through isolated adapters, blind and grade results, classify evidence as promotable/reject/inconclusive, obtain a post-result named-human authorization, reconstruct a scoped change in a clean Git worktree, push and merge a reviewed GitHub pull request, install the immutable merged skill into `~/.codex/skills`, run a fresh-process canary, and roll back automatically on failure.

# Success criteria
- Every stage is resumable, idempotent, content-addressed, and fail-closed.
- Missing telemetry, incomplete trials, insufficient task-cluster coverage, provisional-only grading, contamination, runtime drift, or unresolved disagreement yields inconclusive or invalid evidence, never promotion.
- Every run has one private 32-byte blinding key under a one-run/one-key contract whose signed SHA-256 commitment is bound through the plan, evidence manifest, summary, and approval; packet/candidate identifiers and presentation order are domain-separated HMAC outputs rather than recoverable public-seed labels. Summary evidence and signed approval both name `private/grading/blind-map.jsonl` and bind its SHA-256, while the evidence-manifest SHA-256 remains the canonical graph root.
- Promotion requires zero critical candidate failures, every configured quality/resource/domain threshold, human-final review, and an unexpired cryptographically verified approval bound to the exact evidence and candidate manifest.
- Git promotion never stages the dirty source tree: it copies approved regular files and reconstructs approved ledger/taxonomy records in a clean checkout.
- Installation invokes the configured system skill installer at the immutable merged commit into isolated staging, verifies the full approved manifest and installed subtree, creates a recoverable backup, canaries in a fresh process, and restores the backup on failure.

# Constraints
The model and harness may classify evidence and prepare approval material but may never identify themselves as the human approver, create a human signature, weaken frozen thresholds after holdout reveal, waive critical failures, publish private holdouts, disclose a blinding key or private map to a grader, force-push, bypass branch protection, overwrite an unbacked-up root skill, or treat unavailable data as a zero score. Provisional model grades are diagnostic only and can never establish promotability.

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

- `automation/evaluation.py`: signed external holdout custody, arm-material and runtime-identity binding, immutable matched-cell plans, private per-run HMAC key custody and commitment verification, opaque grouped blinding, raw request/response hash verification before resume/blinding/summary, bounded retry accounting, exact rubric-dimension aggregation, task-cluster coverage/bootstrap intervals, and human-final summary generation.
- `automation/event_store.py` and `automation/orchestrator.py`: compare-and-swap transitions and a tamper-evident hash chain.
- `automation/promotion.py`: SSH verification, exact-base clean-clone reconstruction, recovery-time clone/diff/tree revalidation, canonical GitHub review/merge re-query, full-manifest verification, exact-ref installer-helper staging, locked crash-recoverable install, active-tree revalidation, fresh canary, quarantine, and rollback rehearsal.
- `scripts/automate_lifecycle.py`: resumable subcommands plus `auto`, which advances until it reaches honest missing evidence or human authority.

## Required live configuration

Before a live run, set subject, grader, and canary adapter argv plus the subject adapter/provider/model/settings identity; explicitly allow only required environment variables; configure separate SSH allowed-signers paths and expected identities for holdout custody, human-final review, and promotion approval in operator-controlled files outside the repository and run directory; confirm the GitHub repository and protected branch; replace the committed GitHub automation-actor and required-reviewer placeholders with the exact automation login and a non-empty independent-reviewer allowlist; configure the system skill-installer path and canary validator; and choose private holdout/run paths outside this repository. Empty or placeholder adapter, signer, reviewer, validator, or runtime settings intentionally block. Run `holdout-template --run-dir <fresh-run-directory>` before signing: it creates the 32-byte key under `private/grading/` and includes its SHA-256 commitment in the holdout seal. The operator-controlled configuration and reviewer policy are frozen into the signed evidence. Before holdout reveal, the automation freezes resolved installer, validator, and canary regular-file paths and SHA-256 values into the holdout seal and plan; the signed approval binds their digest and invocation rehashes every artifact. Private run directories/files are enforced at `0700`/`0600` with owner checks on resume. A signed manifest cannot be moved to a different run/key or resumed from the former public-seed contract; either case requires a new run and signature. The automation requires the subject response to echo the exact runtime with `fresh_session: true`, and never creates a review or approval signature.

Filesystem modes are custody controls, not a same-UID sandbox. The configured grader wrapper is trusted computing-base code and must expose only the public request/packet to its model or reviewer. If the wrapper is outside the trusted computing base, run it as a separate UID or in an operating-system sandbox that cannot traverse the private run directory.

## Human handoff and automatic continuation

The first `auto` run may create provisional model grades but stops for human-final grades and review; provisional evidence alone cannot enter a promotable state. The human-final grader receives an exported copy of the public blind packet and rubric in an environment with no run-directory or `private/` access, and binds the public packet hash and final-grade hash in the signed review receipt. The private map is retained for later deterministic summary and audit reconstruction. Summary evidence and the signed promotion approval explicitly bind `blind_map_path` as `private/grading/blind-map.jsonl` plus `blind_map_sha256`; `evidence_manifest_sha256` remains the canonical root of the evidence graph and the signed key commitment remains in that post-grade chain. After conclusive results the lifecycle rehearses rollback and emits `promotion-approval.unsigned.json`. A named promotion approver fills the timestamps and identity, inspects the now-unblinded bound evidence, exports the canonical payload with `approval-payload`, signs it using `ssh-keygen -Y sign`, and attaches the detached signature with `attach-signature`. Rerunning `auto --approval ... --apply` creates the scoped pull request; the same command can wait for or later observe independent GitHub review, merge, install, canary, and activate without further model judgment.
