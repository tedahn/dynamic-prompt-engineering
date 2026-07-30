window.PROMPT_RESEARCH_DATA = {
  "schemaVersion": "1.0",
  "meta": {
    "asOf": "2026-07-28",
    "generatedAt": "2026-07-28",
    "snapshotId": "professionalize-prompt@2026-07-28-eec246d1",
    "bundleSha256": "eec246d1ed31cee3be7965516c31bf3225246ff462a1be6b0526f6f582dd841c",
    "classification": "Experimental - well-specified frozen design; efficacy unproven",
    "adoptionBaseline": "B01_STATIC_MIN_1CALL"
  },
  "staticAudit": {
    "assessmentType": "static-design-only",
    "auditedAt": "2026-07-28",
    "rubricId": "skill-static-design-v1",
    "designQuality": 79.6,
    "evidenceReadiness": 63.5,
    "behavioralEfficacy": "Unknown / not run",
    "note": "Scores describe the frozen instruction design. They must not be compared with behavioral S scores or used to call the skill effective."
  },
  "scoreLedger": {
    "rows": [],
    "recordCount": 0,
    "status": "not-run"
  },
  "fixtures": {
    "count": 45,
    "splits": {
      "dev": 30,
      "holdout": 15
    },
    "modes": {
      "prompt-only": 15,
      "default": 15,
      "execute-only": 15
    },
    "ambiguity": {
      "clear": 15,
      "vague": 15,
      "consequentially-incomplete": 15
    },
    "domains": {
      "editing": 9,
      "coding": 9,
      "research": 9,
      "decision-analysis": 9,
      "creative": 9
    }
  },
  "workflows": [
    {
      "id": "B00_RAW_1CALL",
      "shortId": "B00",
      "name": "Raw request",
      "kind": "baseline",
      "calls": 1,
      "transformer": "none",
      "purpose": "Measure model-native direct execution.",
      "isolates": "The value already supplied by the base model and authorized context."
    },
    {
      "id": "B01_STATIC_MIN_1CALL",
      "shortId": "B01",
      "name": "Minimal specification",
      "kind": "baseline",
      "calls": 1,
      "transformer": "fixed minimal wrapper",
      "purpose": "Adoption baseline controlling for a concise professional specification.",
      "isolates": "Whether a small static contract is sufficient without dynamic transformation.",
      "adoptionBaseline": true
    },
    {
      "id": "B02_SHAM_2CALL",
      "shortId": "B02",
      "name": "Sham transformation",
      "kind": "baseline",
      "calls": 2,
      "transformer": "verbatim delimiter wrapper",
      "purpose": "Control for a second call and fresh executor.",
      "isolates": "Extra call/context effects without a meaningful rewrite."
    },
    {
      "id": "B03_PRO_PROMPT_2CALL",
      "shortId": "B03",
      "name": "Prompt-only transform",
      "kind": "candidate",
      "calls": 2,
      "transformer": "professionalize-prompt prompt-only",
      "purpose": "Estimate prompt-transformation effect independently of inline execution.",
      "isolates": "The transformed prompt handed to a fresh executor."
    },
    {
      "id": "B04_PRO_INLINE_1CALL",
      "shortId": "B04",
      "name": "Inline professionalization",
      "kind": "candidate",
      "calls": 1,
      "transformer": "professionalize-prompt default prompt-plus-execute",
      "purpose": "Estimate deployed end-to-end effect.",
      "isolates": "The default skill behavior users would actually experience."
    },
    {
      "id": "B05_HUMAN_SPEC_UPPER",
      "shortId": "B05",
      "name": "Human-authored ceiling",
      "kind": "diagnostic-ceiling",
      "calls": 2,
      "transformer": "blinded human expert using behavior rubric v1",
      "purpose": "Estimate remaining headroom; never serve as adoption baseline.",
      "isolates": "A diagnostic upper comparator, not a deployment alternative."
    }
  ],
  "ablations": [
    {
      "id": "A01_NO_ADAPTIVE_STRUCTURE",
      "remove": "Adaptive prompt structure",
      "parent": "B04_PRO_INLINE_1CALL"
    },
    {
      "id": "A02_NO_CLARIFY_GATE",
      "remove": "Question versus assumption router",
      "parent": "B04_PRO_INLINE_1CALL"
    },
    {
      "id": "A03_NO_PRESERVE_GUARD",
      "remove": "Preservation and no-invention rules",
      "parent": "B04_PRO_INLINE_1CALL"
    },
    {
      "id": "A04_NO_DOMAIN_ADAPT",
      "remove": "Domain adaptation",
      "parent": "B04_PRO_INLINE_1CALL"
    },
    {
      "id": "A05_NO_VALIDATION",
      "remove": "Prompt and execution validation",
      "parent": "B04_PRO_INLINE_1CALL"
    },
    {
      "id": "A06_NO_MODE_CONTRACT",
      "remove": "Prompt-only and execute-only routing",
      "parent": "B04_PRO_INLINE_1CALL",
      "negativeControl": true
    },
    {
      "id": "A07_NO_MODEL_REFERENCE",
      "remove": "GPT-5.6 prompting reference",
      "parent": "B04_PRO_INLINE_1CALL"
    }
  ],
  "pilot": {
    "experimentId": "EXP-PP-V2-PILOT",
    "status": "pilot-authorized-frozen",
    "frozenArtifacts": "frozen",
    "workflows": [
      "B00_RAW_1CALL",
      "B01_STATIC_MIN_1CALL",
      "B04_PRO_INLINE_1CALL"
    ],
    "fixtureIds": [
      "FX-ED-01",
      "FX-CD-02",
      "FX-RS-03",
      "FX-DA-03",
      "FX-CR-04"
    ],
    "domains": 5,
    "trials": 3,
    "executionCells": 45,
    "concurrency": 1,
    "executionSeed": 20260728,
    "gradeSeed": 7282026,
    "modelAlias": "gpt-5.6-sol",
    "reasoningEffort": "high",
    "evidenceState": "provisional-model-graded",
    "humanReview": "Required before any behavioral score is final",
    "boundary": "Synthetic fixture data only; network and external side effects forbidden",
    "preflightInfrastructure": {
      "evidenceState": "discarded-preflight-infrastructure-only",
      "completedCells": 3,
      "scoredCells": 0,
      "replacementApproval": "REPLACEMENT-PREFLIGHT-001 pending"
    }
  },
  "statefulLoop": {
    "processId": "codex-stateful-context-loop-v1",
    "asOf": "2026-07-29",
    "evidenceState": "design-only",
    "liveAuthorized": false,
    "behavioralEfficacy": "Unknown",
    "activeState": {
      "snapshotId": "CTX-STATE-000",
      "revision": 0,
      "status": "accepted",
      "entries": 0
    },
    "episodes": {
      "development": 12,
      "holdoutCommitted": 0,
      "holdoutMinimum": 24,
      "holdoutStatus": "not-authored-not-sealed"
    },
    "mutableBoundary": {
      "allowed": [
        "durable_context_entries"
      ],
      "operations": [
        "add",
        "supersede",
        "retire"
      ],
      "forbidden": [
        "policy",
        "authority",
        "code",
        "schemas",
        "fixtures",
        "holdout",
        "graders",
        "thresholds",
        "runtime_controls",
        "approval_rules"
      ]
    },
    "conditions": [
      {
        "id": "B0_STATELESS_RAW",
        "contextMode": "none",
        "updates": "none",
        "role": "baseline"
      },
      {
        "id": "B1_FROZEN_CONTEXT",
        "contextMode": "full-frozen",
        "updates": "none",
        "role": "baseline"
      },
      {
        "id": "B2_APPEND_ONLY",
        "contextMode": "raw-history",
        "updates": "append-only",
        "role": "diagnostic"
      },
      {
        "id": "B3_RETRIEVAL_ONLY",
        "contextMode": "retrieved-active",
        "updates": "none",
        "role": "adoption-baseline"
      },
      {
        "id": "B4_HUMAN_MAINTAINED",
        "contextMode": "human-curated",
        "updates": "human",
        "role": "diagnostic-ceiling"
      },
      {
        "id": "C1_GATED_EVOLVING",
        "contextMode": "retrieved-candidate",
        "updates": "codex-proposed-gated",
        "role": "candidate"
      }
    ],
    "stages": [
      {
        "id": "smoke",
        "split": "dev",
        "episodes": 3,
        "conditions": 3,
        "trials": 1,
        "runs": 9,
        "decisionUse": "integration only",
        "status": "designed-not-run"
      },
      {
        "id": "pilot",
        "split": "dev",
        "episodes": 12,
        "conditions": 4,
        "trials": 3,
        "runs": 144,
        "decisionUse": "calibration and variance only",
        "status": "designed-not-run"
      },
      {
        "id": "full",
        "split": "holdout",
        "episodes": 24,
        "conditions": 3,
        "trials": 3,
        "runs": 216,
        "decisionUse": "human promotion review",
        "status": "designed-not-run"
      }
    ],
    "stateLayers": [
      {
        "id": "L0",
        "contents": "Human-owned policy and authority",
        "writer": "Named human only",
        "visibility": "All roles receive the applicable hash and rules"
      },
      {
        "id": "L1",
        "contents": "Frozen model, CLI, tools, and runtime",
        "writer": "Evaluation owner",
        "visibility": "Subject and harness"
      },
      {
        "id": "L2",
        "contents": "Evidence and claim ledgers",
        "writer": "Governed research workflow",
        "visibility": "Optimizer receives cited development evidence"
      },
      {
        "id": "L3",
        "contents": "Approved durable context",
        "writer": "Atomic promotion gate",
        "visibility": "Retrieval-only and evolving subjects"
      },
      {
        "id": "L4",
        "contents": "Candidate context branch",
        "writer": "Codex may propose; harness validates",
        "visibility": "Candidate condition only"
      },
      {
        "id": "L5",
        "contents": "Episode scratch and task context",
        "writer": "Subject agent",
        "visibility": "One isolated episode; discarded afterward"
      },
      {
        "id": "L6",
        "contents": "Private holdout and grader state",
        "writer": "Evaluation owner",
        "visibility": "Graders/harness only; never optimizer"
      },
      {
        "id": "L7",
        "contents": "Reports and dashboard projections",
        "writer": "Deterministic builders",
        "visibility": "Read-only derived view"
      }
    ],
    "promotion": {
      "candidate_condition": "C1_GATED_EVOLVING",
      "adoption_baseline": "B3_RETRIEVAL_ONLY",
      "eligible_stage": "full",
      "minimum_task_delta_lcb95": 5,
      "minimum_pairwise_win_lcb95": 0.5,
      "minimum_family_delta": -3,
      "minimum_context_precision": 0.8,
      "maximum_stale_or_irrelevant_rate": 0.05,
      "maximum_cost_ratio": 2,
      "cost_exception_minimum_task_delta": 10,
      "maximum_critical_gates": 0,
      "human_approval_required": true,
      "canary_required": true,
      "rollback_test_required": true,
      "status": "provisional-preregistration-defaults"
    },
    "stopRules": [
      "runtime profile hash mismatch",
      "policy or schema hash mismatch",
      "missing or expired run approval",
      "fresh holdout exposure to optimizer",
      "context-pack duplicate or leakage alert",
      "conflicting duplicate cell result",
      "confirmed critical gate",
      "cost ceiling exhausted",
      "missing trace or usage artifact",
      "workflow identity exposed to a grader"
    ]
  },
  "contextComposer": {
    "snapshotId": "CC-MECH-2026-07-30-02",
    "scope": "deterministic hardened packet-construction evaluation only",
    "behavioralEfficacy": null,
    "gateResult": "mechanical-pilot-gate-passed",
    "fixtureCount": 12,
    "negativeSecurityCases": 4,
    "gateInterpretation": "C1 passed the narrow safety and B2 recall non-inferiority gate; this is not a superiority result against B0 or evidence of behavioral efficacy.",
    "claimDispositions": {
      "claim_1_higher_recall_than_every_baseline": "not-supported: C1 and B0 tied at 1.0 macro required recall",
      "claim_1_lower_prohibited_and_stale_inclusion": "observed on this synthetic development suite",
      "claim_2_declared_route_selection": "observed on this synthetic development suite",
      "claim_3_behavioral_outcome_gain": "not-tested"
    },
    "families": {
      "lexical_retrieval": 1,
      "paraphrase_metadata": 1,
      "multi_document": 1,
      "temporal_supersession": 1,
      "conflicting_authority": 1,
      "restricted_scope": 1,
      "retrieved_injection": 1,
      "distractor_overload": 1,
      "position_sensitivity": 1,
      "abstention_clarification": 1,
      "workflow_gotcha": 1,
      "budget_pressure": 1
    },
    "conditions": [
      {
        "id": "B0_FULL_DUMP",
        "required_recall_macro": 1,
        "precision_macro": 0.4722,
        "critical_failures": 2,
        "stale_failures": 2,
        "budget_failures": 0,
        "route_accuracy": 0.3333,
        "ordering_failures": 0
      },
      {
        "id": "B1_RECENCY",
        "required_recall_macro": 0.7083,
        "precision_macro": 0.2917,
        "critical_failures": 2,
        "stale_failures": 2,
        "budget_failures": 0,
        "route_accuracy": 0,
        "ordering_failures": 1
      },
      {
        "id": "B2_KEYWORD_TOPK",
        "required_recall_macro": 0.875,
        "precision_macro": 0.4028,
        "critical_failures": 2,
        "stale_failures": 5,
        "budget_failures": 0,
        "route_accuracy": 0,
        "ordering_failures": 1
      },
      {
        "id": "C1_COMPOSED",
        "required_recall_macro": 1,
        "precision_macro": 0.5139,
        "critical_failures": 0,
        "stale_failures": 0,
        "budget_failures": 0,
        "route_accuracy": 0.5833,
        "ordering_failures": 0
      },
      {
        "id": "C2_ROUTED",
        "required_recall_macro": 1,
        "precision_macro": 0.5972,
        "critical_failures": 0,
        "stale_failures": 0,
        "budget_failures": 0,
        "route_accuracy": 1,
        "ordering_failures": 0
      }
    ],
    "limitations": [
      "Fixtures are synthetic development cases.",
      "The trusted fixture producer derives security labels from curated fixture fields; production producer authenticity and classification accuracy remain untested.",
      "No model generated answers, so grounded outcome quality, latency, tokens, cost, and transfer remain unknown.",
      "Dependency ordering is mechanically validated; behavioral ordering effects remain untested.",
      "The B0/C1 required-recall result is a tie, so the original all-baseline recall-superiority claim is unsupported."
    ]
  },
  "dynamicTechniques": [
    {
      "id": "DP-001",
      "name": "Dynamic Prompt Refinement Controls",
      "category": "request-transformer",
      "burden": "medium",
      "summary": "Exposes request-specific context or preference refinements for user selection",
      "workflow": "Parse invariants → propose 3–5 editable refinements → user selects/edits → compile prompt → preservation check",
      "firstComparison": true
    },
    {
      "id": "DP-002",
      "name": "Rephrase-and-Respond (RaR)",
      "category": "request-transformer",
      "burden": "low",
      "summary": "Rewrites or expands the question before response; two-model form retains original plus rewrite",
      "workflow": "Extract invariants → rewrite → bidirectional intent check → execute with original and rewrite",
      "firstComparison": true
    },
    {
      "id": "DP-003",
      "name": "Selective clarification (CLAM)",
      "category": "request-transformer",
      "burden": "medium",
      "summary": "Detects ambiguity, asks only when material, then answers after clarification",
      "workflow": "Enumerate plausible interpretations → estimate decision divergence → ask one targeted question or proceed → log regret",
      "firstComparison": true
    },
    {
      "id": "DP-004",
      "name": "Future-turn clarification value",
      "category": "request-transformer",
      "burden": "high",
      "summary": "Uses simulated downstream turns to learn when clarification will matter",
      "workflow": "Predict downstream divergence and resolution value → compare against interaction cost → ask or proceed"
    },
    {
      "id": "DP-005",
      "name": "Constraint-led prompt compiler",
      "category": "request-transformer",
      "burden": "low",
      "summary": "Converts rough intent into a compact goal/context/constraints/output/validation contract",
      "workflow": "Extract explicit requirements → classify unknowns → compile minimal prompt → round-trip preservation diff"
    },
    {
      "id": "DP-006",
      "name": "KATE",
      "category": "retrieval-routing",
      "burden": "medium",
      "summary": "Retrieves semantically similar examples for each request",
      "workflow": "Retrieve → leakage/quality/diversity filter → freeze k and order → compare zero-shot and random",
      "firstComparison": true
    },
    {
      "id": "DP-007",
      "name": "EPR",
      "category": "retrieval-routing",
      "burden": "high",
      "summary": "Learns an exemplar retriever from LM-likelihood positive/negative labels",
      "workflow": "Build example bank → score pairs → train/reuse retriever → retrieve k → held-out test"
    },
    {
      "id": "DP-008",
      "name": "Universal Self-Adaptive Prompting",
      "category": "retrieval-routing",
      "burden": "high",
      "summary": "Routes task type and creates/selects pseudo-demonstrations from unlabeled examples",
      "workflow": "Classify task → sample unlabeled cases → generate responses → quality/diversity filter → attach demonstrations"
    },
    {
      "id": "DP-009",
      "name": "Rewrite–Retrieve–Read",
      "category": "retrieval-routing",
      "burden": "medium",
      "summary": "Rewrites user language into better retrieval queries before reading evidence",
      "workflow": "Freeze requirement ledger → generate 1–3 queries → retrieve → answer from evidence → compare original-query baseline"
    },
    {
      "id": "DP-010",
      "name": "Adaptive-RAG routing",
      "category": "retrieval-routing",
      "burden": "medium",
      "summary": "Routes requests to no retrieval, single retrieval, or iterative retrieval by complexity",
      "workflow": "Score complexity/evidence need → route → log confusion/cost → compare always-cheap and always-expensive policies"
    },
    {
      "id": "DP-011",
      "name": "Grader-backed iterative optimization",
      "category": "offline-optimizer",
      "burden": "medium",
      "summary": "Rewrites prompts using labeled outputs, critiques, and narrow graders",
      "workflow": "Snapshot prompt/model/data/graders → optimize → frozen holdout → invariant audit → version/rollback"
    },
    {
      "id": "DP-012",
      "name": "Automatic Prompt Engineer (APE)",
      "category": "offline-optimizer",
      "burden": "medium",
      "summary": "Generates multiple instruction candidates and selects by task score",
      "workflow": "Generate N → reject requirement violations → score on development set → select → untouched test",
      "firstComparison": true
    },
    {
      "id": "DP-013",
      "name": "ProTeGi",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Uses failure critiques as textual gradients and beam/bandit search over edits",
      "workflow": "Sample errors → generate critiques → bounded edit beam → development selection → frozen test"
    },
    {
      "id": "DP-014",
      "name": "PRewrite",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Trains a prompt-rewriter with downstream-task reinforcement learning",
      "workflow": "Curate prompt/task pairs → define reward plus preservation penalties → train → heldout and shift tests"
    },
    {
      "id": "DP-015",
      "name": "MIPROv2",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Jointly optimizes instructions and demonstrations across multi-stage LM programs",
      "workflow": "Freeze program graph → bootstrap demonstrations/proposals → capped search → component and end-to-end holdout"
    },
    {
      "id": "DP-016",
      "name": "GEPA",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Evolves prompts from trajectory reflection and retains Pareto-complementary lessons",
      "workflow": "Sample failures → structured reflection → mutation/crossover → Pareto select quality/cost/preservation → holdout"
    },
    {
      "id": "DP-017",
      "name": "OPRO",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Prompts an LLM with prior candidates and scores to generate improved candidates",
      "workflow": "Freeze scorer and budget → iterate candidate/score history → invariant filter → untouched test"
    },
    {
      "id": "DP-018",
      "name": "PromptBreeder",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Evolves task prompts and the mutation prompts that produce them",
      "workflow": "Initialize populations → mutate prompts and mutators → fitness/select → preserve diversity → heldout"
    },
    {
      "id": "DP-019",
      "name": "PromptAgent",
      "category": "offline-optimizer",
      "burden": "high",
      "summary": "Uses strategic planning/search to navigate expert prompt edits",
      "workflow": "Define edit actions → search with task feedback → preserve requirements → budgeted selection → holdout"
    }
  ],
  "skillCandidates": [
    {
      "id": "T-001",
      "family": "Outcome-first specification and ambiguity policy",
      "skillForm": "prompt-contract or the existing professionalize-prompt",
      "state": "Sourced; anchor evaluation blocked",
      "falsifier": "A minimal direct specification matches it on usefulness with less user effort and no added risk"
    },
    {
      "id": "T-002",
      "family": "Redundancy, contradiction, and obsolete-instruction detection",
      "skillForm": "prompt-linter / lean-prompt-pruner",
      "state": "Specified; needs precision eval",
      "falsifier": "Linter overcorrects valid constraints or fails to beat manual review"
    },
    {
      "id": "T-003",
      "family": "Surface-specific example selection",
      "skillForm": "exemplar-curator",
      "state": "Sourced; transfer-sensitive",
      "falsifier": "Modern zero-shot baselines match examples or leakage/overfit erases gains"
    },
    {
      "id": "T-004",
      "family": "Model/product control calibration",
      "skillForm": "surface-calibrator",
      "state": "Sourced; volatile",
      "falsifier": "Prompt-level adaptation adds no value beyond settings or cannot stay current"
    },
    {
      "id": "T-005",
      "family": "Relevance selection, ordering, retrieval, compaction, and token budgeting",
      "skillForm": "context-composer",
      "state": "v0.2 repository candidate; security/schema remediation and mechanical pilot passed; behavioral efficacy Unknown",
      "falsifier": "A simple uncurated context baseline matches it across fresh held-out behavioral tasks"
    },
    {
      "id": "T-006",
      "family": "Output schema plus semantic validation and repair",
      "skillForm": "output-contract-engineer",
      "state": "Sourced; priority candidate",
      "falsifier": "Schema validity fails to improve semantic success or repair adds regressions"
    },
    {
      "id": "T-007",
      "family": "Tool descriptions, schemas, response shaping, and errors",
      "skillForm": "tool-contract-engineer",
      "state": "Sourced; priority candidate",
      "falsifier": "Tool linting does not improve task success or increases tool-selection errors"
    },
    {
      "id": "T-008",
      "family": "Safe/reversible autonomy and confirmation gates",
      "skillForm": "authority-boundary",
      "state": "Specified; safety-critical",
      "falsifier": "Added policy either fails to prevent unsafe actions or blocks ordinary in-scope work"
    },
    {
      "id": "T-009",
      "family": "Sequential/parallel/direct/programmatic tool routing",
      "skillForm": "orchestration-router",
      "state": "Sourced; needs tool harness",
      "falsifier": "Matched-budget direct execution is as good or more reliable"
    },
    {
      "id": "T-010",
      "family": "Decompose then compose",
      "skillForm": "decomposition-planner",
      "state": "Experimental outside paper tasks",
      "falsifier": "Decomposition errors propagate or modern direct baselines match quality at lower cost"
    },
    {
      "id": "T-011",
      "family": "Executable reasoning with deterministic checks",
      "skillForm": "code-backed-reasoner",
      "state": "Experimental; bounded domains",
      "falsifier": "Wrong-code risk or sandbox overhead outweighs accuracy gains"
    },
    {
      "id": "T-012",
      "family": "Independent verification with tools or isolated questions",
      "skillForm": "independent-verifier",
      "state": "Experimental; priority study",
      "falsifier": "Verifier is correlated with generator or false corrections exceed declared threshold"
    },
    {
      "id": "T-013",
      "family": "Criterion-driven iterative refinement",
      "skillForm": "refinement-loop",
      "state": "Experimental; guarded",
      "falsifier": "Intrinsic feedback degrades held-out reasoning or fails cost/iteration stop rules"
    },
    {
      "id": "T-014",
      "family": "Baselines, fixtures, graders, holdouts, promotion, and rollback",
      "skillForm": "prompt-eval-lab",
      "state": "Sourced; enabling priority",
      "falsifier": "Workflow cannot predict human usefulness or overhead prevents ordinary adoption"
    },
    {
      "id": "T-015",
      "family": "Sampling, aggregation, and deliberative search",
      "skillForm": "deliberation-budgeter",
      "state": "Experimental; cost-sensitive",
      "falsifier": "A single higher-quality run matches results at lower cost/latency"
    },
    {
      "id": "T-016",
      "family": "Planner/generator/evaluator long-run harness",
      "skillForm": "long-run-harness",
      "state": "Sourced for specific surfaces; not universal",
      "falsifier": "Stronger model-native execution makes the harness pure overhead"
    },
    {
      "id": "T-017",
      "family": "Multi-agent specialization, debate, and handoffs",
      "skillForm": "dynamic-skill-router / multi-agent router",
      "state": "Experimental; low priority",
      "falsifier": "Matched-token single-agent baseline wins or correlated errors persist"
    },
    {
      "id": "T-018",
      "family": "Execution-grounded, retrievable skill libraries",
      "skillForm": "skill-library-operator",
      "state": "Experimental; environment-specific",
      "falsifier": "Skills do not replay reliably, collide in identity, or fail transfer/safety tests"
    },
    {
      "id": "T-019",
      "family": "Workspace-grounded approach exploration and falsifiable next-step selection",
      "skillForm": "explore-approaches",
      "state": "Mechanically validated advisory and sealed-record lifecycle prototype; behavioral efficacy Unknown",
      "falsifier": "A minimal advisory prompt or composed professionalize-prompt mode matches quality with lower overhead"
    },
    {
      "id": "T-020",
      "family": "Role-separated evidence-grounded skill and research review",
      "skillForm": "review-skill-candidate",
      "state": "Repository prototype; mechanical tests passed; behavioral value Unknown",
      "falsifier": "One general reviewer plus deterministic checks matches critical recall and auditability with lower overhead"
    }
  ],
  "ledgers": {
    "claims": {
      "count": 53,
      "status": {
        "Grounded fact": 31,
        "Looks believable": 3,
        "Corroborated": 10,
        "Forecast/opinion": 2,
        "Experimental": 7
      },
      "confidence": {
        "high": 34,
        "medium": 17,
        "low": 2
      }
    },
    "sources": {
      "count": 64,
      "type": {
        "official documentation": 8,
        "official help": 2,
        "official engineering article": 4,
        "direct artifact": 6,
        "research paper": 36,
        "direct observation": 4,
        "research preprint": 2,
        "vendor technical report": 1,
        "direct technical report": 1
      }
    },
    "evalCases": {
      "count": 26,
      "status": {
        "blocked": 1,
        "designed": 13,
        "deferred": 1,
        "mechanically-validated": 5,
        "development-diagnostic": 2,
        "remediation-validated": 4
      }
    },
    "assumptions": {
      "count": 12,
      "status": {
        "open": 12
      }
    },
    "changes": {
      "count": 10,
      "status": {
        "validated": 1,
        "validated-design": 4,
        "mechanically-validated-prototype": 1,
        "mechanically-validated-automation": 1,
        "development-reviewed-prototype": 1,
        "remediation-validated-pending-head-review": 1,
        "mechanically-validated-pending-head-review": 1
      }
    }
  },
  "promotionRunway": [
    {
      "id": "01",
      "name": "Discover",
      "state": "done",
      "note": "19 dynamic techniques mapped"
    },
    {
      "id": "02",
      "name": "Source",
      "state": "done",
      "note": "64 sources registered"
    },
    {
      "id": "03",
      "name": "Specify",
      "state": "done",
      "note": "Frozen skill and comparators"
    },
    {
      "id": "04",
      "name": "Evaluate",
      "state": "current",
      "note": "Pilot pending preflight"
    },
    {
      "id": "05",
      "name": "Approve",
      "state": "pending",
      "note": "Named human review required"
    },
    {
      "id": "06",
      "name": "Promote",
      "state": "pending",
      "note": "No production skill authorization"
    }
  ]
};
