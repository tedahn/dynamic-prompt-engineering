# Validation evidence contract

Use `scripts/validation_evidence.py` when a review finding, remediation claim, or merge decision depends on deterministic checks. The recorder binds the checks to the exact non-ignored worktree content they exercised and preserves failures as evidence.

## Evidence set

A run creates one new, initially empty output directory containing:

- `content-projection-manifest.json`: every Git-tracked and untracked, non-ignored worktree path with type, mode, size, and SHA-256; tracked deletions and Git links have explicit entries.
- `validation-result.json`: exact argument arrays, repository-relative working directories, declared tool dependencies, UTC start/completion times, durations, timeouts, execution statuses, exit codes, and the tested projection hash.
- `artifacts/tools/*.txt`: complete stdout and stderr from each version probe.
- `artifacts/commands/*.txt`: complete stdout and stderr from each validation command.

The artifact manifest hashes every generated file except `validation-result.json`. The result cannot hash itself. The content projection therefore excludes exactly the manifest, result, and captured streams; the exclusion list participates in the projection hash. A frozen review packet must hash both top-level JSON files. This final packet binding closes the intentional self-reference boundary.

The recorded Git head is context, not the tested-tree identity. The content projection is the tested-tree identity, so it can survive the later commit that adds only the excluded evidence files. The exact-head review packet must independently bind the final commit.

## Run

Pass commands as JSON objects. Argument arrays are executed directly without a shell. Every validation command must declare the version-probe names for the tools it uses. If an argument array invokes a wrapper, the operator must list every decision-relevant tool behind that wrapper.

```sh
python3 research/evaluations/skill-review-process/scripts/validation_evidence.py run \
  --repo-root . \
  --output-dir research/evaluations/skill-review-process/results/PR-NNN-validation \
  --tool-version '{"name":"python","argv":["python3","--version"],"cwd":"."}' \
  --command '{"name":"review-tests","argv":["python3","-m","unittest","discover","-s","research/evaluations/skill-review-process/tests"],"cwd":".","tools":["python"],"timeout_seconds":600}'
```

The command exits nonzero when a probe or validation command fails, times out, cannot launch, or changes projected source. It still writes the complete failed result. Do not discard or relabel that negative evidence.

## Verify

Verification does not rerun the checks. It recomputes the current projection, verifies the manifest hash carried by the result, checks every artifact hash and size, enforces exact artifact/exclusion sets, validates timestamps and status derivation, and checks the recorder implementation hash.

```sh
python3 research/evaluations/skill-review-process/scripts/validation_evidence.py verify \
  --repo-root . \
  --manifest research/evaluations/skill-review-process/results/PR-NNN-validation/content-projection-manifest.json \
  --result research/evaluations/skill-review-process/results/PR-NNN-validation/validation-result.json
```

Integrity-valid negative evidence returns verification success while reporting `recorded_status: failed`. A reviewer must distinguish artifact integrity from validation success.

## Authority and limitations

- The recorder runs only argument arrays explicitly supplied by the operator. It does not install, publish, deploy, promote, contact providers, or infer authority for those actions.
- The inherited environment is used but variable values are not persisted because they may contain secrets. Put non-secret, decision-relevant configuration in versioned files or explicit arguments.
- Git-ignored files are outside the projection. A validation that depends on an ignored file must copy a safe, reviewable representation into the projected tree or record it as a separately hashed artifact.
- Generated evidence paths must not preexist. The recorder refuses a non-empty output directory and never overwrites prior evidence.
- A passing record establishes only that the named commands exited successfully against the recorded projection. It does not establish behavioral efficacy, generalization, or skill promotion eligibility.
