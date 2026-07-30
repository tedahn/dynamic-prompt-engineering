# Explore Approaches promotion and installation process

This process promotes `skills/explore-approaches` to GitHub and installs it at `~/.codex/skills/explore-approaches`. Prototype creation does not authorize either action.

## Gate 1 — validate and freeze

1. Run the contract checker, automation tests, skill-creator `quick_validate.py`, and `git diff --check`.
2. Before signing, run `holdout-template` with the final private `--run-dir`. Automation creates one 32-byte random blinding key for that run and the named holdout owner signs an external v2 custody manifest binding its SHA-256 commitment plus the private holdout, domains, candidate, exact B02/C01 arm materials, subject adapter/provider/model/settings and executable artifacts, resolved installer/validator/canary paths and hashes, rubric, protocol, frozen configuration, thresholds, and plan design; automation verifies and copies it exactly before creating the immutable plan.
3. Keep the private holdout and run directory outside the repository. Keep the run root and private directories at `0700` and the key and private map at `0600`. The signed manifest is valid only with that run directory and key; key loss, replacement, a different run directory, or a public-seed-era artifact requires a new template, signature, and run.

## Gate 2 — fresh held-out evaluation

1. A named human prepares and protects the fresh holdout described in `PROTOCOL.md`.
2. The automation executes all four arms under matched conditions through configured fresh-process adapters. Each subject response must echo the frozen runtime and assert `fresh_session: true`; hashed request, raw-response, normalized-response, and attempt records are preserved and reverified before resume, blinding, and summary.
3. Automation derives opaque packet/candidate IDs and presentation order with domain-separated HMAC-SHA-256. Model grades remain provisional and can never establish promotability. Export only the public blind packet and rubric to a human-final grader with no run-directory or `private/` access; the signed review must bind the exact public-packet and final-grade hashes before unblinding. Filesystem modes are custody controls rather than a same-UID sandbox, so the grader wrapper is trusted computing-base code unless separately isolated.
4. Missing trials, exact rubric dimensions, telemetry, predeclared task-cluster coverage, confidence bounds, or human-final adjudication is inconclusive. Zero or missing resource denominators do not pass. Contamination is invalid. A development forward test or mechanical check cannot satisfy this gate.

## Gate 3 — post-evaluation human approval

Generate an unsigned approval that validates against `schemas/promotion-approval.schema.json`. It must be dated after the evaluation summary and bind the named approver, frozen base commit and configuration, candidate manifest, signed blinding-key commitment, public-packet hash, and the explicit `blind_map_path` value `private/grading/blind-map.jsonl` plus `blind_map_sha256` already present in summary evidence. Its `evidence_manifest_sha256` remains the canonical root of the evidence graph. It also binds the GitHub target, root destination, permissions, zero accepted exceptions, and tested rollback. The private key and map remain in the private run directory for deterministic reconstruction and audit; only the relative map locator and digest, not their contents, are embedded in the approval. A named human reviews those artifacts and signs the canonical payload with an allowed SSH key.

The approval never contains a future pull-request URL or merge commit; those belong in machine receipts. The automation never creates its own signature. A failed, forged, mismatched, or expired approval stops the process.

## Gate 4 — scoped GitHub promotion

The automation builds a manifest from approved regular files plus individual ledger and taxonomy records. It clones `main` into a new directory, disables hooks, reconstructs only those records, stages the exact allowlist, and fails if any other path appears. It never stages the dirty source worktree.

After signature attachment, `scripts/automate_lifecycle.py auto ... --apply` resolves the active GitHub login in the same credential context and requires a case-insensitive match to the frozen automation actor before push, PR recovery, and merge. Provider-backed stages additionally require the separate signed execution authorization and explicit `--execute`; promotion approval never grants implicit model-spending authority. The frozen role map mechanically separates candidate author, holdout owner, human reviewer/adjudicator, provider-execution approver, promotion owner, automation actor, and PR reviewer. It pushes `codex/explore-approaches-v0.1.0` without force and opens or resumes the pull request. Recovery independently revalidates clone origin, branch, ancestry, clean tree, exact diff, manifest, approval, configuration, credential, blinding-commitment, packet, and private-map bindings. It stops at `pr-open` until GitHub reports the configured base, unchanged head, a current approval from at least one exact login in the frozen reviewer allowlist whose reviewed commit is that exact head, `CLEAN` merge state, and every exact configured check. The pull-request author and verified automation actor are never eligible reviewers; a later dismissal or changes-requested review supersedes an earlier approval. Release recovery always re-queries GitHub and reconciles the canonical merge evidence. Immutable PR and release records bind both the evidence and verified login to lifecycle events. It never approves its own pull request or uses an administrator bypass. Private holdouts, raw private grades, blinding keys, private maps, secrets, and credentials remain outside GitHub.

## Gate 5 — verified root installation

The automation checks out the GitHub-reported merge commit in detached mode, proves its configured-base reachability, and verifies the complete promoted manifest. It invokes the configured system `skill-installer` helper with the exact repository, skill path, and merge SHA into isolated staging, then verifies that subtree against the approved checkout before touching the root destination. Installer and validator subprocesses use `inherit_env=false` with separate explicit allowlists, preventing ambient provider, GitHub, cloud, or signing credentials from reaching them. Under an exclusive lock, a durable install intent journals the backup and swap so a retry can reconcile exact filesystem hashes after any crash. It then runs a new request-bound fresh-process canary under the signed execution budget. Empty canary configuration or missing execution authority is a blocking failure, never a pass. Release, intent, installation, canary, quarantine, and rollback receipts bind the exact merge commit and paths; recovery from `active` revalidates the persisted signed approval, event bindings, receipts, and installed tree.

## Rollback

On canary failure, the automation immediately moves the candidate into `.quarantine`, restores the exact prior directory when one existed, and emits `rollback-record.json`. After activation, `rollback-active --operator <frozen-promotion-owner> --reason <incident> --apply` performs the same recovery as an operational command: it locks the skill, verifies sealed install receipts and active hashes, journals intent before mutation, quarantines atomically, restores the predecessor or absence, runs a fresh credential-minimized rollback canary, and seals operator, reason, paths, hashes, and canary evidence. Crash recovery reconciles each boundary from durable intent and filesystem hashes. On any later authority, fabrication, trigger-collision, or material quality regression:

1. Quarantine the installed candidate.
2. Restore the timestamped prior version when one exists; otherwise leave the skill uninstalled.
3. Start a fresh task and verify the prior behavior or skill absence.
4. Record the trigger, version, evidence, operator, time, and follow-up decision in the change ledger and GitHub issue or pull request.
