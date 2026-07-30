# Explore Approaches promotion and installation process

This process promotes `skills/explore-approaches` to GitHub and installs it at `~/.codex/skills/explore-approaches`. Prototype creation does not authorize either action.

## Gate 1 — validate and freeze

1. Run the contract checker, its tests, skill-creator `quick_validate.py`, and `git diff --check`.
2. Complete development diagnostics, resolve confirmed defects, and freeze the candidate, rubric, protocol, and development records.
3. Record SHA-256 hashes and the candidate Git commit. Do not modify frozen artifacts during the held-out run.

## Gate 2 — fresh held-out evaluation

1. A named human prepares and protects the fresh holdout described in `PROTOCOL.md`.
2. Execute all four arms under matched conditions and preserve raw evidence.
3. Complete blinded grading, independent human review, disagreement adjudication, and resource reporting.
4. Mark every threshold pass, failure, exception, and unresolved gap. A development forward test or mechanical check cannot satisfy this gate.

## Gate 3 — post-evaluation human approval

Create an approval JSON that validates against `schemas/promotion-approval.schema.json`. Approval must be dated after the evaluation summary and must identify the approver, candidate version and commit, evidence hashes, accepted exceptions, GitHub target, root install destination, canary, and tested rollback. A failed or expired approval stops the process.

## Gate 4 — scoped GitHub promotion

Use branch `codex/explore-approaches-v0.1.0`. The current worktree may contain unrelated changes, so stage only the approved allowlist:

```sh
git switch -c codex/explore-approaches-v0.1.0
git add skills/explore-approaches \
  research/technique-profiles/T-019-workspace-grounded-approach-exploration.md \
  research/skill-candidates/T-019-explore-approaches.md \
  research/evaluations/explore-approaches \
  research/ledgers/claims.csv research/ledgers/sources.csv \
  research/ledgers/eval-cases.csv research/ledgers/assumptions-forecasts.csv \
  research/ledgers/change-log.csv research/TECHNIQUE_TAXONOMY.md
git diff --cached --name-only
git diff --cached --check
git commit -m "Add explore-approaches skill candidate"
git push -u origin codex/explore-approaches-v0.1.0
```

Before committing, stop if the staged path list contains anything outside the approval allowlist. Open a pull request to `main`, attach the evaluation summary and approval record, require review, and merge only the reviewed commit. Record the pull-request URL and merge commit. Do not place private holdouts, secrets, provider credentials, or private grader data in GitHub.

## Gate 5 — verified root installation

1. Fetch the merged `main` branch in a clean checkout and verify that its candidate commit and hashes match the approval.
2. Validate the merged `skills/explore-approaches` directory again.
3. If `~/.codex/skills/explore-approaches` exists, move it to `~/.codex/skills/.backups/explore-approaches-<timestamp>` before copying. Stop if a recoverable backup cannot be created.
4. Copy the approved merged directory to `~/.codex/skills/explore-approaches` and validate the installed copy.
5. Start a fresh Codex task, verify explicit `$explore-approaches` invocation, and run low-authority canary requests. Record results before enabling implicit use.

## Rollback

On any authority, fabrication, trigger-collision, or material quality regression:

1. Move the installed candidate to `~/.codex/skills/.quarantine/explore-approaches-<timestamp>`.
2. Restore the timestamped prior version when one exists; otherwise leave the skill uninstalled.
3. Start a fresh task and verify the prior behavior or skill absence.
4. Record the trigger, affected version, evidence, operator, time, and follow-up decision in the change ledger and GitHub issue or pull request.
