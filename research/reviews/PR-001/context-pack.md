# PR-001-8371f0f9634b — frozen review context

- Version: 1.0
- Built at: 2026-07-30T05:38:48Z
- Owner: Ted Ahn
- Consumer: isolated reviewers and adjudicator
- Supported gate: merge readiness only
- Repository: tedahn/dynamic-prompt-engineering
- Base SHA: `506850f0d4cf7b21990231b40c560864fd82e9e2`
- Head SHA: `8371f0f9634bf86e3417bae09772418034239969`
- Diff SHA-256: `24048aec899e9298b8fa5b08893e428e9de03aba518f9a99431f565c9a7943ca`
- Context budget: changed files plus allowlisted policies; retrieve exact excerpts only as needed
- Refresh trigger: any target, policy, evaluation, or authority change

## Decision and success criteria

Decide whether the frozen target is coherent and safe enough to become eligible for a named-human merge decision. Success requires three independent role submissions, evidence-bound adjudication, target integrity, and no upheld unresolved P0/P1 finding.

## Authorized actions

- Read the frozen commits and allowlisted policies.
- Run read-only or local deterministic validation.
- Produce one structured reviewer submission or adjudication artifact.

## Forbidden actions

- Modify the target, merge, install, promote, deploy, contact people, or spend money.
- Read another reviewer submission before independent review closes.
- Treat merge readiness as behavioral, promotion, or installation evidence.

## Current state

The target is frozen for review. Existing validation is reported evidence, not a substitute for inspection.

## Known validation

- 67 Python evaluation tests passed before publication
- 9 dashboard tests and 12 source-derived invariants passed
- Both published candidate skills passed structural validation
- Secret identity-path private-endpoint and whitespace checks passed

## Canonical policies

- `AGENTS.md`
- `chatgpt-project/handbook/CONTINUOUS_IMPROVEMENT.md`
- `chatgpt-project/handbook/EVIDENCE_GOVERNANCE.md`
- `research/RESEARCH_BRIEF-prompt-techniques-as-skills.md`

## Evidence index

| ID | Exact location | State | Content SHA-256 |
|---|---|---|---|
| 001 | `README.md` | modified | `919cabed5c5891552936d0d807ebcf71824168f6fb77f0fb82ca3a834f3d6bca` |
| 002 | `dashboard/BUILD_SPEC.md` | modified | `d88f9133e4608633d2e8ed0abf15c5207504f6a30bace1287fd983e1a8866658` |
| 003 | `dashboard/app.js` | modified | `578243ac93860021e5bd9251abc47aa5dff86e384b59f8b35d1d322abe7e498a` |
| 004 | `dashboard/data.js` | modified | `5a0bc177f8af56e6fa1c42c6c223aa7325175f3f41965c0d382995cdcf70a3ff` |
| 005 | `dashboard/index.html` | modified | `57237d2208138314243bf35777a93221bba5e525d5bb8390c8e040375dde703f` |
| 006 | `dashboard/scripts/build-data.mjs` | modified | `23deeeac04f2d2fb9e96f14f54a347d3e710fc494087d78c57dbe1542b5bc230` |
| 007 | `dashboard/tests/dashboard.test.mjs` | modified | `e19bb5e3a7d3eecc6444b055c1ead513fa877a187389ebcaa26d445232f0810b` |
| 008 | `research/CONTINUATION_PROMPT-2026-07-29-full-completion.md` | added | `7f4ec6ebb1334e083b7a2a88cc8d63263a15db3cbc8cced5c1a81d0497d5e310` |
| 009 | `research/NEXT_ACTION-001.md` | modified | `d93d75b1bbfbb18d18a897a04b94ce3dbf5d314cbcea09a42bf1e2d624427432` |
| 010 | `research/RESEARCH_BRIEF-prompt-techniques-as-skills.md` | modified | `e0f0090014a3a823c4ceb0b037a3be424ee2851ea27355807a8f0d1e0763a8fa` |
| 011 | `research/SURFACE_REGISTRY.md` | modified | `2662d67c8c97921968b5cf958c0e63ad1e0454b86f6ea6362494a1cc8f987248` |
| 012 | `research/TECHNIQUE_TAXONOMY.md` | modified | `8f3368522d543ad63319117fc424847594f5170347f9609ae9ee37da5cd3ee0c` |
| 013 | `research/evaluations/context-composer/BUILD_SPEC.md` | added | `c5512ca7a3f3dfcd29a3c1bd0cdc3f4f50b620eec4de83b1ff58a4187065bd4c` |
| 014 | `research/evaluations/context-composer/PROTOCOL.md` | added | `258b8a9ab232f5208ac35ffa5bcc343c62ab9975024bbcc7677d0089f97fddb5` |
| 015 | `research/evaluations/context-composer/README.md` | added | `37ae38880fdd0dc0da516d8450945f14afd787137b6f482043875061a327d809` |
| 016 | `research/evaluations/context-composer/config/context-composer-v1.json` | added | `7356a7c803f6e8ad0245b552eb3733e8100ea1498862f3eb71b81cb2af357801` |
| 017 | `research/evaluations/context-composer/fixtures/fixtures-v1.jsonl` | added | `1c2d66cfa207ebfe4e6fd5834ffb48341c55a0725f696e3681562074e18cfd53` |
| 018 | `research/evaluations/context-composer/results/mechanical-summary-2026-07-29.json` | added | `2ec156c3cbddcd34b19d6c9583d98e8c80344d64434018edc6ed1f4bb93f7487` |
| 019 | `research/evaluations/context-composer/schemas/fixture.schema.json` | added | `69a75af503359dad2fd7120e80c0ee094f00fabead005db3736110f9f4406775` |
| 020 | `research/evaluations/context-composer/scripts/context_eval.py` | added | `b2deb5d499abba679967a9be6f6e1231e4cf88a54fc53e54f48b3558a185b595` |
| 021 | `research/evaluations/context-composer/tests/test_context_eval.py` | added | `e8a600d099a4f4f1e5d033f35452ae4c0f42cd1fbe19eeee655021e63403bb93` |
| 022 | `research/evaluations/explore-approaches/PROMOTION.md` | added | `6caaea10b9ad2ef588587f891bdcd83be3ef9ef95525428f54bc704635646c9a` |
| 023 | `research/evaluations/explore-approaches/PROTOCOL.md` | added | `3257f85308dfa3c365ebb91e38aa8fc61fafd2baaf05bda0020ca329aa00ed86` |
| 024 | `research/evaluations/explore-approaches/WORKING_SPEC.md` | added | `1432c151e4d25aef107af850496d643fe5a425ea87a4515588329b41f8e0d2ec` |
| 025 | `research/evaluations/explore-approaches/fixtures/fixtures-v1.jsonl` | added | `54890312946986f07beca895ae3396d168093d31430f6ca950feb47e28f352f0` |
| 026 | `research/evaluations/explore-approaches/results/forward-test-2026-07-29.md` | added | `a86a34f07614b830f5fb2791a46c87e5997dd5273f042622a85e285e4a389292` |
| 027 | `research/evaluations/explore-approaches/rubrics/rubric-v1.json` | added | `1f0459e6772bc295576e5f92b27ed9fd5e98128d766f1be6c16b11ca15ffc15c` |
| 028 | `research/evaluations/explore-approaches/schemas/promotion-approval.schema.json` | added | `67d39454d9a8daef6df472fa90e25ccd25e9654d2fb4516f86a45667eb1b9613` |
| 029 | `research/evaluations/explore-approaches/scripts/check_candidate.py` | added | `aeeb65e60902137c6a380bd01c68bee403ba608a3d2ef7f649c1889aeb598c35` |
| 030 | `research/evaluations/explore-approaches/tests/test_check_candidate.py` | added | `00393dbd3151c8e949bc1332aca7a87597c444910a824dd65e3df097d825cca0` |
| 031 | `research/evaluations/professionalize-prompt/pilot-v2/approvals/REPLACEMENT-PREFLIGHT-001.md` | added | `ffddde60acc926ecf2c46d9e7f8b449da96925b875ee0769b027a886cfd04988` |
| 032 | `research/evaluations/professionalize-prompt/pilot-v2/experiments/EXP-PP-V2-PILOT.json` | modified | `385b95f489917206a9a57d5dfef63f3fc91d73286db016a6f9f7e99b2881d14f` |
| 033 | `research/evaluations/professionalize-prompt/pilot-v2/results/PREFLIGHT-INFRA-2026-07-29.json` | added | `54a1b94fa7d0a10fc882e7c6765c62f3ba466025a01dc46027b5072681b310ee` |
| 034 | `research/evaluations/professionalize-prompt/pilot-v2/scripts/run_pilot.py` | modified | `aade1673c4dd0f2dab12ab186d354325bf72f646b1a42205be90cf543e7ac7aa` |
| 035 | `research/evaluations/professionalize-prompt/pilot-v2/tests/test_run_pilot.py` | modified | `fe859e4adf8e18a2562bc5df33150b998c72e1ff06ab89f3c1c559e30135d79b` |
| 036 | `research/ledgers/assumptions-forecasts.csv` | modified | `47779482002b8f1cabaf82032170143570fc5205d60b4ed74cc0b3f63c83d0b8` |
| 037 | `research/ledgers/change-log.csv` | modified | `da90c11a4441c4beace2e4acdde3941fdad02b4fabd02f33444a76909d33c273` |
| 038 | `research/ledgers/claims.csv` | modified | `f3b84c0d82e37541bb54777aa140e4f0930fd8d30aa687e36e749394e807fdef` |
| 039 | `research/ledgers/eval-cases.csv` | modified | `a080364727018043cc9ef2ed1f05f28e5c1a8242b843098ae1e6d7909cee08f8` |
| 040 | `research/ledgers/sources.csv` | modified | `a05f0fe53137a43a01749d59d7a0a7789f13133d2fd893e5e987f68fae640ba3` |
| 041 | `research/skill-candidates/T-005-context-composer.md` | added | `3ba6d051169961d6221ea48f2b01c0ceb31a679b3d069cbeb2869ccb16be302d` |
| 042 | `research/skill-candidates/T-019-explore-approaches.md` | added | `5b758394c8187c4a2831d8e31669a18e3f9717f404c02c8d280cd69857f9946e` |
| 043 | `research/technique-profiles/T-005-context-composer.md` | modified | `be211f7914bb0dc567e863ae30e1e6f247c33ffce36c3dc4cb65124d5415a5d3` |
| 044 | `research/technique-profiles/T-019-workspace-grounded-approach-exploration.md` | added | `2b7ec00d63c727c0cfd1a60bb384cc1a513568a5b4d6cbfe302ee59fdec36c49` |
| 045 | `skills/context-composer/SKILL.md` | added | `26e2fb2d7edcecb0317cc18c09a4d2becf53a260627b037f30b681b8948d13e6` |
| 046 | `skills/context-composer/agents/openai.yaml` | added | `c32041c6b867ec25c05e3dbf4c048f65186fa1c5d367dc26f7170f5ebdd460e6` |
| 047 | `skills/context-composer/references/contract.md` | added | `fd3b95b4b8264f81f64dee2c8a16ea2630488576ad8e9a522bbc3226f3634333` |
| 048 | `skills/context-composer/scripts/compose_context.py` | added | `6027f12c0a80cce5a9b3c29e0ebe5814656cad7e9ab790040f0a8c1de9cf0ba1` |
| 049 | `skills/explore-approaches/SKILL.md` | added | `9d0a24bdaa0a02c5632a170c19eedd3ab742ffb8e6c86333a30acfa32e508f0c` |
| 050 | `skills/explore-approaches/agents/openai.yaml` | added | `4843e4c3081c6fa24b1171894925421d237ca7f14b62529efa2834278e1d18b9` |

## Contradiction register

- Mechanical or unit-test success does not establish behavioral efficacy.
- Publication or merge does not authorize skill installation or production promotion.
- Reviewer agreement does not replace evidence quality or human authority.

## Material unknowns

- ChatGPT transfer is untested unless a ChatGPT run is separately recorded.
- Reviewer coverage outside the declared `reviewed_files` is unknown.
- Behavioral efficacy and adoption readiness remain outside this merge review.

## Excluded context

| Item | Reason | Reconsider when |
|---|---|---|
| Other reviewer outputs | Preserve independence | Adjudication begins |
| Uncommitted working tree | Target is the frozen commits | A superseding review is opened |
| Secrets and private local state | Outside public review boundary | Never include raw values |

## Required output

One schema-valid role submission with explicit coverage, evidence anchors, counterevidence, confidence, limitations, and no self-approval.

## Validation

Run `review_bundle.py validate` after all role submissions and adjudication exist. Only the named human may decide merge.

## Stop and fallback rules

Stop on target mismatch, missing authority, secret or privacy exposure, contaminated reviewer context, unavailable evidence, or material uncovered scope. Record `blocked` or `unresolved`; do not simulate completion.

## Handoff

Return the structured submission to the adjudicator after all independent reviews close. Preserve raw artifacts and hashes.
