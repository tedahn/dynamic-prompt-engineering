# Explore Approaches automation runbook

The lifecycle CLI advances until the next evidence or authority gate. It is resumable: reuse the same private run directory after a blocked exit.

## 1. Configure live integrations

Copy `config/pipeline-v1.json` to a private configuration file and set:

- `evaluation.subject_adapter_argv`, `grader_adapter_argv`, and `canary_adapter_argv`, using `{input}` and `{output}` as whole argv elements, plus an absolute non-symlink `canary_entrypoint_path` and absolute `canary_dependency_paths`;
- `evaluation.subject_runtime`, naming the exact adapter, provider, model, settings, absolute non-symlink `entrypoint_path`, and absolute `dependency_paths` used for every matched subject cell;
- `evaluation.adapter_env_allowlist`, containing only environment variables required by those adapters;
- `roles`, resolving unique identities for candidate author, holdout owner, human reviewer/adjudicator, provider-execution approver, promotion owner, automation actor, and PR reviewer;
- `holdout_verification.allowed_signers_path` and `expected_identity` for the named holdout owner;
- `human_review_verification.allowed_signers_path` and `expected_identity` for the named final reviewer;
- `execution_verification.allowed_signers_path` and `expected_identity` plus bounded `provider_execution_limits` for the separate provider-execution approver;
- `approval_verification.allowed_signers_path` and `expected_identity`;
- the GitHub repository, protected base branch, feature branch, exact required-check identities, non-placeholder `promotion.automation_actor`, a non-empty `promotion.required_reviewer_logins` allowlist, an absolute system `skill-installer` helper with `installer_dependency_paths` and `installer_env_allowlist`, an absolute validator entrypoint with `validator_dependency_paths` and `validator_env_allowlist`, root-skill paths, and a non-empty canary validator.

Keep credentials, the live configuration and signer trust files, private holdout tasks, raw outputs, grades, and the run directory outside this repository. The run root and every persisted private directory must be caller-owned mode `0700`; private files, SQLite state, JSONL, and adapter-produced files must be caller-owned regular non-symlinks at mode `0600`. Creation normalizes adapter output under a restrictive contract, while resume rejects ownership or mode drift. This is the local multi-user threat boundary: group/world-readable run artifacts are invalid even when their hashes still match.

Blinding uses one 32-byte cryptographically random key per private run. The key and private map live at `private/grading/blind-key.bin` and `private/grading/blind-map.jsonl` under the mode contract above. These permissions provide custody against other operating-system users, not a sandbox from code running as the same UID. The local grader adapter wrapper is therefore part of the trusted computing base: it must send only the exported public request to the grader and must not inspect or transmit the run tree. Use a separate UID or operating-system sandbox when that wrapper is not trusted.

Each adapter runs in a fresh process with `shell=False`, a capped response size, a timeout, and at most two transient retries. Lifecycle argv executables and entrypoints must be configured as concrete absolute regular non-symlink files; bare relative scripts, PATH or ambient-working-directory resolution, unresolved tokens, and module or inline interpreter forms are rejected. Before holdout contents are read, the installer helper, validator, and canary executable, entrypoint, argv file artifacts, and declared dependency files or trees are hashed into the signed holdout seal and frozen plan. The post-result approval signs the same lifecycle-executable digest, and every installer, validator, and canary invocation immediately rehashes its frozen paths. Post-approval substitution blocks before the helper can run. Declarative image digests are not accepted until the runner can independently verify and execute the named image. Every successful response must echo the frozen runtime identity, assert `fresh_session: true`, and explicitly report `completed`. Raw request, response, normalization, and attempt-record hashes are reverified before resume, blinding, summary construction, and promotion. Promotion also rehashes and deterministically reconstructs the canonical evidence manifest after approval. Unavailable telemetry cannot pass.

Provider-backed adapters and promotion installation or rollback require a POSIX runtime with isolated process-group signaling and POSIX file locking. The runner checks this capability before creating an adapter attempt or mutating an installation, and it refuses the operation before any external or mutating helper child can launch when the prerequisite is unavailable. Installer, validator, canary, and rollback-validator processes run in new sessions; timeout cleanup covers the whole group, and a descendant that outlives a normally completed or failed leader is terminated and treated as a fail-closed lifecycle error. Model-free artifact checks still require no provider call; the explicit `local-test` copy path preserves that model-free behavior on the supported POSIX promotion runtime.

## 2. Run through evaluation

Generate and sign the exact holdout seal:

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  holdout-template \
  --run-dir /private/path/explore-run \
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

`holdout-template --run-dir ...` must run before the holdout owner signs. It creates or reuses that run's private 32-byte blinding key and places its SHA-256 commitment in the v2 seal. The seal also binds the exact holdout, task count, domains, candidate manifest, private configuration, protocol, rubric, arm materials, runtime, lifecycle executables, and plan design. The signer identity must match both `created_by` and the configured allowed signer. The automation verifies the seal before writing a plan and copies it byte-for-byte into the same private run directory; it never invents authorship.

The signed manifest, run directory, and blinding key are a one-run/one-key set. Reuse the same `--run-dir` for freeze, execution, grading, summary, approval, and recovery. Losing or replacing the key, using the signed manifest with another run directory, or changing any committed input requires a newly templated and newly signed run. Public-seed runs and artifacts created before this contract are incompatible and must not be migrated or resumed as evidence.

The first command freezes the plan and stops without a provider call. It writes `execution-authorization.unsigned.json`. The distinct provider-execution approver sets a post-freeze time and bounded expiry, may lower (never raise) the configured call/retry/token limits, signs the canonical payload in the `codex-skill-provider-execution` namespace, and attaches the signature:

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  execution-authorization-payload \
  --authorization /private/path/explore-run/execution-authorization.unsigned.json \
  --output /private/path/execution-authorization.payload.json

ssh-keygen -Y sign \
  -f /private/path/provider-execution-key \
  -n codex-skill-provider-execution \
  /private/path/execution-authorization.payload.json

python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  attach-signature \
  --document /private/path/explore-run/execution-authorization.unsigned.json \
  --signature /private/path/execution-authorization.payload.json.sig \
  --output /private/path/execution-authorization.signed.json

python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  auto \
  --run-dir /private/path/explore-run \
  --execution-authorization /private/path/execution-authorization.signed.json \
  --execute
```

Only the final command executes the 144 matched cells. Each provider attempt is durably reserved before the call and conservatively charges the signed per-call token bound; missing or excessive telemetry blocks the result. The process derives opaque packet IDs, candidate IDs, candidate order, and packet order with domain-separated HMAC-SHA-256. It writes the public packet to `grading/blind-packet.jsonl` and retains the key and arm mapping under `private/grading/`. The evidence manifest records the private map as `private/grading/blind-map.jsonl` with its SHA-256. The summary evidence and signed promotion approval each carry that explicit `blind_map_path` and `blind_map_sha256`; their `evidence_manifest_sha256` remains the canonical graph root. Preserve the key and map until the run and its promotion or rejection audit are complete; never give their paths, contents, or evidence-manifest linkage to a grader.

Optional model grades are provisional and can never make a run promotable. For human-final grading, export only `grading/blind-packet.jsonl` plus the frozen rubric to a reviewer environment that has no run-directory or `private/` access. Create the final grade and review artifacts using `schemas/grade-record.schema.json` and `schemas/human-review.schema.json`. The review must bind the exact public blind-packet SHA-256 and final-grades SHA-256, and carry a detached OpenSSH signature whose identity exactly matches `reviewer` and `human_review_verification.expected_identity` in the `codex-skill-human-review` namespace, before the private map is used to construct the summary.

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

The signer must appear in the configured OpenSSH allowed-signers file. `approved_by`, the signature identity, and `approval_verification.expected_identity` must be the same exact identity. The automation verifies the signature over canonical JSON with the `signature` object excluded, then rechecks every evidence hash, lifecycle-executable digest, target, permission, timestamp, candidate version, manifest, and frozen base commit.

## 4. Promote, wait for independent review, merge, and install

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  auto \
  --run-dir /private/path/explore-run \
  --execution-authorization /private/path/provider-execution-authorization.signed.json \
  --approval /private/path/promotion-approval.signed.json \
  --execute \
  --apply \
  --poll-seconds 30 \
  --max-review-wait-seconds 3600
```

The command prepares a clean commit at the exact signed base SHA, resolves `gh api user` in the same ambient credential context, and requires that login to match the frozen `automation_actor` case-insensitively before every push, PR recovery, and merge. Pushes are never forced. Immutable PR and release receipts retain the verified login. Recovery revalidates clone origin, branch, ancestry, clean tree, exact diff, manifest, approval, configuration, and actor bindings. It requires an unchanged head, the configured base, a current GitHub approval from an exact login in the frozen reviewer allowlist whose reviewed commit equals that exact head, `CLEAN` merge state, and every exact configured check; the PR author and verified automation actor cannot satisfy review. Release recovery re-queries GitHub and reconciles a canonical receipt. It then verifies the complete promoted manifest, invokes the configured system installer at the exact merge SHA into isolated staging, verifies the downloaded subtree, swaps it atomically, and activates only after the fresh-process canary explicitly passes. Failure quarantines the candidate and restores the verified prior root skill; active recovery revalidates signed approval, receipts, event bindings, and the installed tree.

PR, release, install-intent, canary, installation, quarantine, active-rollback intent, rollback-canary, and rollback records are sealed and hash-bound to lifecycle events. Rerunning the same command resumes `frozen`, `running`, `promotable`, `promoting`, `pr-open`, `merged`, `installing`, `canary`, or operational rollback without trusting a pre-existing receipt; root mutation uses an exclusive lock and reconciles filesystem hashes before proceeding. Installer and validator subprocesses receive only their explicit environment allowlists and never inherit the ambient credential environment.

## 5. Operational rollback after activation

Use the frozen promotion owner identity and a concrete incident reason. The command is inert without `--apply`:

```sh
python research/evaluations/explore-approaches/scripts/automate_lifecycle.py \
  --config /private/path/pipeline.json \
  rollback-active \
  --run-dir /private/path/explore-run \
  --operator exact-promotion-owner-identity \
  --reason "material post-activation regression in guarded task class" \
  --apply
```

The command verifies the completed install receipt and active hashes, writes a durable sealed intent, atomically moves the active candidate into the configured quarantine, restores the sealed predecessor (or leaves the skill absent), runs a fresh credential-minimized rollback canary, and seals the operator, reason, receipt hashes, candidate hashes, predecessor hashes, and rollback-canary hash. A crash at any mutation boundary resumes from filesystem hashes under the same exclusive lock.

Use `status --run-dir /private/path/explore-run` to audit the hash chain. Exit `0` means the requested stage completed; `10` means a conclusive non-promotion outcome; `20` means an expected evidence or human gate; `2` means a configuration, integrity, or external failure.

## Current non-readiness

The repository configuration intentionally contains empty live adapter argv and signer trust plus distinct non-live role, GitHub automation, and reviewer placeholders. No fresh private holdout, signed provider-execution authorization, provider call, human-final review, signed promotion approval, reviewed PR, live merge, production root install, or operational active rollback has been performed.
