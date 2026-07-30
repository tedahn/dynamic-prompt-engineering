# Explore Approaches promotion and installation process

This process promotes `skills/explore-approaches` to GitHub and installs it at `~/.codex/skills/explore-approaches`. Prototype creation does not authorize either action.

## Gate 1 — validate and freeze

1. Run the contract checker, automation tests, skill-creator `quick_validate.py`, and `git diff --check`.
2. A named holdout owner signs an external v2 custody manifest binding the private holdout, domains, candidate, exact B02/C01 arm materials, subject adapter/provider/model/settings and executable artifacts, rubric, protocol, frozen configuration, thresholds, and base commit; automation verifies and copies it exactly before creating the immutable plan.
3. Keep the private holdout and run directory outside the repository. Do not modify frozen artifacts during the held-out run.

## Gate 2 — fresh held-out evaluation

1. A named human prepares and protects the fresh holdout described in `PROTOCOL.md`.
2. The automation executes all four arms under matched conditions through configured fresh-process adapters. Each subject response must echo the frozen runtime and assert `fresh_session: true`; hashed request, raw-response, normalized-response, and attempt records are preserved and reverified before resume, blinding, and summary.
3. Complete blinded grading, independent human review, disagreement adjudication, and resource reporting.
4. Missing trials, exact rubric dimensions, telemetry, predeclared task-cluster coverage, confidence bounds, or human-final adjudication is inconclusive. Zero or missing resource denominators do not pass. Contamination is invalid. A development forward test or mechanical check cannot satisfy this gate.

## Gate 3 — post-evaluation human approval

Generate an unsigned approval that validates against `schemas/promotion-approval.schema.json`. It must be dated after the evaluation summary and bind the named approver, frozen base commit and configuration, candidate manifest, evidence hashes, GitHub target, root destination, permissions, zero accepted exceptions, and tested rollback. A named human reviews those artifacts and signs the canonical payload with an allowed SSH key.

The approval never contains a future pull-request URL or merge commit; those belong in machine receipts. The automation never creates its own signature. A failed, forged, mismatched, or expired approval stops the process.

## Gate 4 — scoped GitHub promotion

The automation builds a manifest from approved regular files plus individual ledger and taxonomy records. It clones `main` into a new directory, disables hooks, reconstructs only those records, stages the exact allowlist, and fails if any other path appears. It never stages the dirty source worktree.

After signature attachment, `scripts/automate_lifecycle.py auto ... --apply` pushes `codex/explore-approaches-v0.1.0` without force and opens or resumes the pull request. Recovery independently revalidates clone origin, branch, ancestry, clean tree, exact diff, manifest, approval, and configuration bindings. It stops at `pr-open` until GitHub reports the configured base, unchanged head, independent approval, `CLEAN` merge state, and every exact configured check. Release recovery always re-queries GitHub and reconciles the canonical merge evidence. Immutable PR and release records bind this evidence to lifecycle events. It never approves its own pull request or uses an administrator bypass. Private holdouts, raw private grades, secrets, and credentials remain outside GitHub.

## Gate 5 — verified root installation

The automation checks out the GitHub-reported merge commit in detached mode, proves its configured-base reachability, and verifies the complete promoted manifest. It invokes the configured system `skill-installer` helper with the exact repository, skill path, and merge SHA into isolated staging, then verifies that subtree against the approved checkout before touching the root destination. Under an exclusive lock, a durable install intent journals the backup and swap so a retry can reconcile exact filesystem hashes after any crash. It then runs a new request-bound fresh-process canary. Empty canary configuration is a blocking failure, never a pass. Release, intent, installation, canary, quarantine, and rollback receipts bind the exact merge commit and paths; recovery from `active` revalidates the persisted signed approval, event bindings, receipts, and installed tree.

## Rollback

On canary failure, the automation immediately moves the candidate into `.quarantine`, restores the exact prior directory when one existed, and emits `rollback-record.json`. On any later authority, fabrication, trigger-collision, or material quality regression:

1. Quarantine the installed candidate.
2. Restore the timestamped prior version when one exists; otherwise leave the skill uninstalled.
3. Start a fresh task and verify the prior behavior or skill absence.
4. Record the trigger, version, evidence, operator, time, and follow-up decision in the change ledger and GitHub issue or pull request.
