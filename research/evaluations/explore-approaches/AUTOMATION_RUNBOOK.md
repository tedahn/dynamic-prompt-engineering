# Explore Approaches automation runbook

The lifecycle CLI advances until the next evidence or authority gate. It is resumable: reuse the same private run directory after a blocked exit.

## 1. Configure live integrations

Copy `config/pipeline-v1.json` to a private configuration file and set:

- `evaluation.subject_adapter_argv`, `grader_adapter_argv`, and `canary_adapter_argv`, using `{input}` and `{output}` as whole argv elements;
- `evaluation.subject_runtime`, naming the exact adapter, provider, model, and settings used for every matched subject cell;
- `evaluation.adapter_env_allowlist`, containing only environment variables required by those adapters;
- `holdout_verification.allowed_signers_path` and `expected_identity` for the named holdout owner;
- `approval_verification.allowed_signers_path` and `expected_identity`;
- the GitHub repository, protected base branch, feature branch, configured required-check identities, system `skill-installer` helper, root-skill paths, and non-empty canary validator.

Keep credentials, the live configuration and signer trust files, private holdout tasks, raw outputs, grades, and the run directory outside this repository. Each adapter runs in a fresh process with `shell=False`, a capped response size, a timeout, and at most two transient retries. Subject executable/script hashes and the resolved runtime identity are frozen; every successful response must echo that identity, assert `fresh_session: true`, and explicitly report `completed`. Raw request, response, normalization, and attempt-record hashes are reverified before resume, blinding, and summary construction. Unavailable telemetry cannot pass.

## 2. Run through evaluation

Generate and sign the exact holdout seal:

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  holdout-template \
  --holdout /private/path/holdout.jsonl \
  --output /private/path/holdout-manifest.unsigned.json

ssh-keygen -Y sign \
  -f /private/path/holdout-owner-key \
  -n codex-skill-holdout \
  /private/path/holdout-manifest.unsigned.json.payload

python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  attach-signature \
  --document /private/path/holdout-manifest.unsigned.json \
  --signature /private/path/holdout-manifest.unsigned.json.payload.sig \
  --output /private/path/holdout-manifest.signed.json
```

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  auto \
  --run-dir /private/path/explore-run \
  --holdout /private/path/holdout.jsonl \
  --holdout-manifest /private/path/holdout-manifest.signed.json
```

The v2 seal computes the exact holdout, task-count, domain, candidate-manifest, private-config, protocol, and rubric hashes. The signer identity must match both `created_by` and the configured allowed signer. The automation verifies the seal before writing a plan and copies it byte-for-byte into the private run directory; it never invents authorship. It also persists the canonical candidate manifest and private configuration and rechecks their frozen hashes before every later stage.

The command then freezes the plan, executes 144 matched cells, blinds outputs, and optionally creates provisional model grades. It stops for human-final grades and review. Create those artifacts using `schemas/grade-record.schema.json` and `schemas/human-review.schema.json`; the review must bind the final-grades SHA-256.

Rerun with `--final-grades` and `--human-review`. A rejected, invalid, or inconclusive result is terminal for that frozen run. A promotable result triggers a rollback rehearsal and writes `promotion-approval.unsigned.json`.

## 3. Human review and SSH authorization

A named human inspects the summary, raw evidence, disagreements, accepted exceptions, target, and rollback evidence; fills the unsigned approval timestamps and identity; and signs it outside the automation:

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  approval-payload \
  --approval /private/path/promotion-approval.unsigned.json \
  --output /private/path/promotion-approval.payload.json

ssh-keygen -Y sign \
  -f /private/path/human-approval-key \
  -n codex-skill-promotion \
  /private/path/promotion-approval.payload.json

python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  attach-signature \
  --approval /private/path/promotion-approval.unsigned.json \
  --signature /private/path/promotion-approval.payload.json.sig \
  --output /private/path/promotion-approval.signed.json
```

The signer must appear in the configured OpenSSH allowed-signers file. The automation verifies the signature over canonical JSON with the `signature` object excluded, then rechecks every evidence hash, target, permission, timestamp, candidate version, manifest, and frozen base commit.

## 4. Promote, wait for independent review, merge, and install

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  auto \
  --run-dir /private/path/explore-run \
  --approval /private/path/promotion-approval.signed.json \
  --apply \
  --poll-seconds 30 \
  --max-review-wait-seconds 3600
```

The command prepares a clean commit at the exact signed base SHA, pushes without force, and opens or resumes the PR. Recovery revalidates clone origin, branch, ancestry, clean tree, exact diff, manifest, approval, and configuration bindings. It requires an unchanged head, the configured base, an independent GitHub approval, `CLEAN` merge state, and every exact configured check. Release recovery re-queries GitHub and reconciles a canonical receipt. It then verifies the complete promoted manifest, invokes the configured system installer at the exact merge SHA into isolated staging, verifies the downloaded subtree, swaps it atomically, and activates only after the fresh-process canary explicitly passes. Failure quarantines the candidate and restores the verified prior root skill; active recovery revalidates signed approval, receipts, event bindings, and the installed tree.

PR, release, install-intent, canary, installation, quarantine, and rollback records are sealed and hash-bound to lifecycle events. Rerunning the same command resumes `frozen`, `promotable`, `promoting`, `pr-open`, `merged`, `installing`, or `canary` without trusting a pre-existing receipt; root installation uses an exclusive lock and reconciles filesystem hashes before proceeding.

Use `status --run-dir /private/path/explore-run` to audit the hash chain. Exit `0` means the requested stage completed; `10` means a conclusive non-promotion outcome; `20` means an expected evidence or human gate; `2` means a configuration, integrity, or external failure.

## Current non-readiness

The repository configuration intentionally contains empty live adapter argv, signer path, and signer identity. No fresh private holdout, human-final review, signed approval, reviewed PR, live merge, or production root install has been performed.
