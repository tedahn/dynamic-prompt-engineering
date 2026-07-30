window.PROMPT_RESEARCH_DATA = {
  schemaVersion: "1.0",
  meta: {
    asOf: "2026-07-29",
    generatedAt: "2026-07-30",
    snapshotId: "professionalize-prompt@2026-07-28-eec246d1",
    bundleSha256: "eec246d1ed31cee3be7965516c31bf3225246ff462a1be6b0526f6f582dd841c",
    classification: "Experimental — well-specified frozen design; efficacy unproven",
    adoptionBaseline: "B01_STATIC_MIN_1CALL"
  },
  staticAudit: {
    assessmentType: "static-design-only",
    auditedAt: "2026-07-28",
    rubricId: "skill-static-design-v1",
    designQuality: 79.6,
    evidenceReadiness: 63.5,
    behavioralEfficacy: "Unknown / not run",
    note: "Static scores describe the frozen instruction design. They must not be compared with behavioral outcome scores or used to call the skill effective."
  },
  scoreLedger: {
    rows: [],
    recordCount: 0,
    status: "not-run"
  },
  fixtures: {
    count: 45,
    splits: { dev: 30, holdout: 15 },
    modes: { "prompt-only": 15, default: 15, "execute-only": 15 },
    ambiguity: { clear: 15, vague: 15, "consequentially-incomplete": 15 },
    domains: {
      editing: 9,
      coding: 9,
      research: 9,
      "decision-analysis": 9,
      creative: 9
    }
  },
  workflows: [
    {
      id: "B00_RAW_1CALL",
      shortId: "B00",
      name: "Raw request",
      kind: "baseline",
      calls: 1,
      transformer: "none",
      purpose: "Measure model-native direct execution.",
      isolates: "The value already supplied by the base model and authorized context."
    },
    {
      id: "B01_STATIC_MIN_1CALL",
      shortId: "B01",
      name: "Minimal specification",
      kind: "baseline",
      calls: 1,
      transformer: "fixed minimal wrapper",
      purpose: "Adoption baseline controlling for a concise professional specification.",
      isolates: "Whether a small static contract is sufficient without dynamic transformation.",
      adoptionBaseline: true
    },
    {
      id: "B02_SHAM_2CALL",
      shortId: "B02",
      name: "Sham transformation",
      kind: "baseline",
      calls: 2,
      transformer: "verbatim delimiter wrapper",
      purpose: "Control for a second call and fresh executor.",
      isolates: "Extra call/context effects without a meaningful rewrite."
    },
    {
      id: "B03_PRO_PROMPT_2CALL",
      shortId: "B03",
      name: "Prompt-only transform",
      kind: "candidate",
      calls: 2,
      transformer: "professionalize-prompt prompt-only",
      purpose: "Estimate prompt-transformation effect independently of inline execution.",
      isolates: "The transformed prompt handed to a fresh executor."
    },
    {
      id: "B04_PRO_INLINE_1CALL",
      shortId: "B04",
      name: "Inline professionalization",
      kind: "candidate",
      calls: 1,
      transformer: "professionalize-prompt prompt-plus-execute",
      purpose: "Estimate deployed end-to-end effect.",
      isolates: "The default skill behavior users would actually experience."
    },
    {
      id: "B05_HUMAN_SPEC_UPPER",
      shortId: "B05",
      name: "Human-authored ceiling",
      kind: "diagnostic-ceiling",
      calls: 2,
      transformer: "blinded human expert using behavior rubric v1",
      purpose: "Estimate remaining headroom; never serve as adoption baseline.",
      isolates: "A diagnostic upper comparator, not a deployment alternative."
    }
  ],
  ablations: [
    { id: "A01_NO_ADAPTIVE_STRUCTURE", remove: "Adaptive prompt structure", parent: "B04_PRO_INLINE_1CALL" },
    { id: "A02_NO_CLARIFY_GATE", remove: "Question-versus-assumption router", parent: "B04_PRO_INLINE_1CALL" },
    { id: "A03_NO_PRESERVE_GUARD", remove: "Preservation and no-invention rules", parent: "B04_PRO_INLINE_1CALL" },
    { id: "A04_NO_DOMAIN_ADAPT", remove: "Domain adaptation", parent: "B04_PRO_INLINE_1CALL" },
    { id: "A05_NO_VALIDATION", remove: "Prompt and execution validation", parent: "B04_PRO_INLINE_1CALL" },
    { id: "A06_NO_MODE_CONTRACT", remove: "Prompt-only and execute-only routing", parent: "B04_PRO_INLINE_1CALL", negativeControl: true },
    { id: "A07_NO_MODEL_REFERENCE", remove: "GPT-5.6 prompting reference", parent: "B04_PRO_INLINE_1CALL" }
  ],
  pilot: {
    experimentId: "EXP-PP-V2-PILOT",
    status: "pilot-authorized-pending-preflight",
    frozenArtifacts: "TO_BE_FROZEN_BEFORE_PREFLIGHT",
    workflows: ["B00_RAW_1CALL", "B01_STATIC_MIN_1CALL", "B04_PRO_INLINE_1CALL"],
    fixtureIds: ["FX-ED-01", "FX-CD-02", "FX-RS-03", "FX-DA-03", "FX-CR-04"],
    domains: 5,
    trials: 3,
    executionCells: 45,
    concurrency: 1,
    executionSeed: 20260728,
    gradeSeed: 7282026,
    modelAlias: "gpt-5.6-sol",
    reasoningEffort: "high",
    evidenceState: "provisional-model-graded",
    humanReview: "Required before any behavioral score is final",
    boundary: "Synthetic fixture data only; network and external side effects forbidden"
  },
  statefulLoop: {
    processId: "codex-stateful-context-loop-v1",
    asOf: "2026-07-29",
    evidenceState: "design-only",
    liveAuthorized: false,
    behavioralEfficacy: "Unknown",
    activeState: {
      snapshotId: "CTX-STATE-000",
      revision: 0,
      status: "accepted",
      entries: 0
    },
    episodes: {
      development: 12,
      holdoutCommitted: 0,
      holdoutMinimum: 24,
      holdoutStatus: "not-authored-not-sealed"
    },
    mutableBoundary: {
      allowed: ["durable_context_entries"],
      operations: ["add", "supersede", "retire"],
      forbidden: ["policy", "authority", "code", "schemas", "fixtures", "holdout", "graders", "thresholds", "runtime_controls", "approval_rules"]
    },
    conditions: [
      { id: "B0_STATELESS_RAW", contextMode: "none", updates: "none", role: "baseline" },
      { id: "B1_FROZEN_CONTEXT", contextMode: "full-frozen", updates: "none", role: "baseline" },
      { id: "B2_APPEND_ONLY", contextMode: "raw-history", updates: "append-only", role: "diagnostic" },
      { id: "B3_RETRIEVAL_ONLY", contextMode: "retrieved-active", updates: "none", role: "adoption-baseline" },
      { id: "B4_HUMAN_MAINTAINED", contextMode: "human-curated", updates: "human", role: "diagnostic-ceiling" },
      { id: "C1_GATED_EVOLVING", contextMode: "retrieved-candidate", updates: "codex-proposed-gated", role: "candidate" }
    ],
    stages: [
      { id: "smoke", split: "dev", episodes: 3, conditions: 3, trials: 1, runs: 9, decisionUse: "integration only", status: "designed-not-run" },
      { id: "pilot", split: "dev", episodes: 12, conditions: 4, trials: 3, runs: 144, decisionUse: "calibration and variance only", status: "designed-not-run" },
      { id: "full", split: "holdout", episodes: 24, conditions: 3, trials: 3, runs: 216, decisionUse: "human promotion review", status: "designed-not-run" }
    ],
    stateLayers: [
      { id: "L0", contents: "Human-owned policy and authority", writer: "Named human only", visibility: "All roles receive the applicable hash and rules" },
      { id: "L1", contents: "Frozen model, CLI, tools, and runtime", writer: "Evaluation owner", visibility: "Subject and harness" },
      { id: "L2", contents: "Evidence and claim ledgers", writer: "Governed research workflow", visibility: "Optimizer receives cited development evidence" },
      { id: "L3", contents: "Approved durable context", writer: "Atomic promotion gate", visibility: "Retrieval-only and evolving subjects" },
      { id: "L4", contents: "Candidate context branch", writer: "Codex may propose; harness validates", visibility: "Candidate condition only" },
      { id: "L5", contents: "Episode scratch and task context", writer: "Subject agent", visibility: "One isolated episode; discarded afterward" },
      { id: "L6", contents: "Private holdout and grader state", writer: "Evaluation owner", visibility: "Graders/harness only; never optimizer" },
      { id: "L7", contents: "Reports and dashboard projections", writer: "Deterministic builders", visibility: "Read-only derived view" }
    ],
    promotion: {
      candidate_condition: "C1_GATED_EVOLVING",
      adoption_baseline: "B3_RETRIEVAL_ONLY",
      eligible_stage: "full",
      minimum_task_delta_lcb95: 5,
      minimum_pairwise_win_lcb95: 0.5,
      minimum_family_delta: -3,
      minimum_context_precision: 0.8,
      maximum_stale_or_irrelevant_rate: 0.05,
      maximum_cost_ratio: 2,
      cost_exception_minimum_task_delta: 10,
      maximum_critical_gates: 0,
      human_approval_required: true,
      canary_required: true,
      rollback_test_required: true,
      status: "provisional-preregistration-defaults"
    },
    stopRules: [
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
  dynamicTechniques: [
    {
      id: "DP-001",
      name: "Dynamic Prompt Refinement Controls",
      category: "request-transformer",
      burden: "medium",
      summary: "Exposes request-specific context or preference refinements for user selection.",
      workflow: "Parse invariants → propose 3–5 editable refinements → user selects or edits → compile prompt → preservation check"
    },
    {
      id: "DP-002",
      name: "Rephrase-and-Respond (RaR)",
      category: "request-transformer",
      burden: "low",
      summary: "Rewrites or expands the question before response while retaining the original request.",
      workflow: "Extract invariants → rewrite → bidirectional intent check → execute with original and rewrite",
      firstComparison: true
    },
    {
      id: "DP-003",
      name: "Selective clarification (CLAM)",
      category: "request-transformer",
      burden: "medium",
      summary: "Detects material ambiguity and asks only when the answer is likely to change.",
      workflow: "Enumerate interpretations → estimate decision divergence → ask one targeted question or proceed → log regret",
      firstComparison: true
    },
    {
      id: "DP-004",
      name: "Future-turn clarification value",
      category: "request-transformer",
      burden: "high",
      summary: "Uses simulated downstream turns to estimate when clarification will matter.",
      workflow: "Predict downstream divergence and resolution value → compare with interaction cost → ask or proceed"
    },
    {
      id: "DP-005",
      name: "Constraint-led prompt compiler",
      category: "request-transformer",
      burden: "low",
      summary: "Compiles rough intent into a compact goal, context, constraints, output, and validation contract.",
      workflow: "Extract explicit requirements → classify unknowns → compile minimal prompt → round-trip preservation diff"
    },
    {
      id: "DP-006",
      name: "KATE",
      category: "retrieval-routing",
      burden: "medium",
      summary: "Retrieves semantically similar examples for each request.",
      workflow: "Retrieve → leakage, quality, and diversity filter → freeze k and order → compare zero-shot and random",
      firstComparison: true
    },
    {
      id: "DP-007",
      name: "EPR",
      category: "retrieval-routing",
      burden: "high",
      summary: "Learns an exemplar retriever from language-model likelihood labels.",
      workflow: "Build example bank → score pairs → train or reuse retriever → retrieve k → held-out test"
    },
    {
      id: "DP-008",
      name: "Universal Self-Adaptive Prompting",
      category: "retrieval-routing",
      burden: "high",
      summary: "Routes task type and creates pseudo-demonstrations from unlabeled examples.",
      workflow: "Classify task → sample cases → generate responses → quality and diversity filter → attach demonstrations"
    },
    {
      id: "DP-009",
      name: "Rewrite–Retrieve–Read",
      category: "retrieval-routing",
      burden: "medium",
      summary: "Rewrites user language into better retrieval queries before reading evidence.",
      workflow: "Freeze requirement ledger → generate queries → retrieve → answer from evidence → compare original-query baseline"
    },
    {
      id: "DP-010",
      name: "Adaptive-RAG routing",
      category: "retrieval-routing",
      burden: "medium",
      summary: "Routes requests to no retrieval, single retrieval, or iterative retrieval by complexity.",
      workflow: "Score complexity and evidence need → route → log confusion and cost → compare cheap and expensive policies"
    },
    {
      id: "DP-011",
      name: "Grader-backed iterative optimization",
      category: "offline-optimizer",
      burden: "medium",
      summary: "Rewrites prompts using labeled outputs, critiques, and narrow graders.",
      workflow: "Snapshot prompt, model, data, and graders → optimize → frozen holdout → invariant audit → version and rollback"
    },
    {
      id: "DP-012",
      name: "Automatic Prompt Engineer (APE)",
      category: "offline-optimizer",
      burden: "medium",
      summary: "Generates instruction candidates and selects them by task score.",
      workflow: "Generate N → reject requirement violations → score development set → select → untouched test",
      firstComparison: true
    },
    {
      id: "DP-013",
      name: "ProTeGi",
      category: "offline-optimizer",
      burden: "high",
      summary: "Uses failure critiques as textual gradients and searches a bounded edit beam.",
      workflow: "Sample errors → generate critiques → bounded edit beam → development selection → frozen test"
    },
    {
      id: "DP-014",
      name: "PRewrite",
      category: "offline-optimizer",
      burden: "high",
      summary: "Trains a prompt rewriter with downstream-task reinforcement learning.",
      workflow: "Curate prompt-task pairs → define reward and preservation penalties → train → held-out and shift tests"
    },
    {
      id: "DP-015",
      name: "MIPROv2",
      category: "offline-optimizer",
      burden: "high",
      summary: "Jointly optimizes instructions and demonstrations across multi-stage language-model programs.",
      workflow: "Freeze program graph → bootstrap demonstrations and proposals → capped search → component and end-to-end holdout"
    },
    {
      id: "DP-016",
      name: "GEPA",
      category: "offline-optimizer",
      burden: "high",
      summary: "Evolves prompts from trajectory reflection and retains Pareto-complementary lessons.",
      workflow: "Sample failures → structured reflection → mutation and crossover → Pareto select → holdout"
    },
    {
      id: "DP-017",
      name: "OPRO",
      category: "offline-optimizer",
      burden: "high",
      summary: "Prompts a model with previous candidates and scores to generate improved candidates.",
      workflow: "Freeze scorer and budget → iterate candidate-score history → invariant filter → untouched test"
    },
    {
      id: "DP-018",
      name: "PromptBreeder",
      category: "offline-optimizer",
      burden: "high",
      summary: "Evolves task prompts and the mutation prompts that produce them.",
      workflow: "Initialize populations → mutate prompts and mutators → fitness selection → preserve diversity → held-out test"
    },
    {
      id: "DP-019",
      name: "PromptAgent",
      category: "offline-optimizer",
      burden: "high",
      summary: "Uses strategic planning and search to navigate expert prompt edits.",
      workflow: "Define edit actions → search with task feedback → preserve requirements → budgeted selection → holdout"
    }
  ],
  skillCandidates: [
    { id: "T-001", family: "Outcome-first specification and ambiguity policy", skillForm: "professionalize-prompt", state: "Sourced; anchor evaluation blocked", falsifier: "A minimal direct specification matches usefulness with less effort and no added risk." },
    { id: "T-002", family: "Redundancy, contradiction, and obsolete-instruction detection", skillForm: "prompt-linter", state: "Specified; needs precision eval", falsifier: "The linter overcorrects valid constraints or fails to beat manual review." },
    { id: "T-003", family: "Surface-specific example selection", skillForm: "exemplar-curator", state: "Sourced; transfer-sensitive", falsifier: "Modern zero-shot baselines match examples or leakage and overfit erase gains." },
    { id: "T-004", family: "Model/product control calibration", skillForm: "internal professionalize-prompt model-profile gate", state: "Prototype challenger; behavior unscored", falsifier: "Prompt-level adaptation adds no value beyond settings or cannot stay current" },
    { id: "T-005", family: "Context relevance, ordering, retrieval, compaction, and budgeting", skillForm: "context-composer", state: "Sourced; priority candidate", falsifier: "An uncurated context baseline matches it across held-out tasks." },
    { id: "T-006", family: "Output schema plus semantic validation and repair", skillForm: "output-contract-engineer", state: "Sourced; priority candidate", falsifier: "Schema validity does not improve semantic success or repair adds regressions." },
    { id: "T-007", family: "Tool descriptions, schemas, response shaping, and errors", skillForm: "tool-contract-engineer", state: "Sourced; priority candidate", falsifier: "Tool linting does not improve success or increases tool-selection errors." },
    { id: "T-008", family: "Safe and reversible autonomy with confirmation gates", skillForm: "authority-boundary", state: "Specified; safety-critical", falsifier: "Policy fails to prevent unsafe actions or blocks ordinary in-scope work." },
    { id: "T-009", family: "Sequential, parallel, direct, and programmatic tool routing", skillForm: "orchestration-router", state: "Sourced; needs tool harness", falsifier: "Matched-budget direct execution is as good or more reliable." },
    { id: "T-010", family: "Decompose then compose", skillForm: "decomposition-planner", state: "Experimental outside paper tasks", falsifier: "Decomposition errors propagate or direct baselines match quality at lower cost." },
    { id: "T-011", family: "Executable reasoning with deterministic checks", skillForm: "code-backed-reasoner", state: "Experimental; bounded domains", falsifier: "Wrong-code risk or sandbox overhead outweighs accuracy gains." },
    { id: "T-012", family: "Independent verification with tools or isolated questions", skillForm: "independent-verifier", state: "Experimental; priority study", falsifier: "Verifier errors correlate with the generator or false corrections exceed threshold." },
    { id: "T-013", family: "Criterion-driven iterative refinement", skillForm: "refinement-loop", state: "Experimental; guarded", falsifier: "Intrinsic feedback degrades held-out reasoning or violates cost and stop rules." },
    { id: "T-014", family: "Baselines, fixtures, graders, holdouts, promotion, and rollback", skillForm: "prompt-eval-lab", state: "Sourced; enabling priority", falsifier: "The workflow cannot predict human usefulness or overhead blocks adoption." },
    { id: "T-015", family: "Sampling, aggregation, and deliberative search", skillForm: "deliberation-budgeter", state: "Experimental; cost-sensitive", falsifier: "A single stronger run matches results at lower cost and latency." },
    { id: "T-016", family: "Planner, generator, and evaluator long-run harness", skillForm: "long-run-harness", state: "Surface-specific", falsifier: "Stronger model-native execution makes the harness pure overhead." },
    { id: "T-017", family: "Multi-agent specialization, debate, and handoffs", skillForm: "dynamic-skill-router", state: "Experimental; low priority", falsifier: "A matched-token single agent wins or correlated errors persist." },
    { id: "T-018", family: "Execution-grounded, retrievable skill libraries", skillForm: "skill-library-operator", state: "Experimental; environment-specific", falsifier: "Skills fail to replay reliably, collide in identity, or fail transfer and safety tests." }
  ],
  ledgers: {
    claims: {
      count: 38,
      status: { "Grounded fact": 24, "Looks believable": 4, "Corroborated": 9, "Forecast/opinion": 1 },
      confidence: { high: 23, medium: 15 }
    },
    sources: {
      count: 55,
      type: { "research paper": 35, "official documentation": 11, "official engineering article": 4, "official help": 2, "direct artifact": 1, "direct observation": 1, "research preprint": 1 }
    },
    evalCases: { count: 15, status: { blocked: 1, designed: 13, deferred: 1 } },
    assumptions: { count: 8, status: { open: 8 } },
    changes: { count: 4, status: { validated: 1, "validated-design": 2, prototype: 1 } }
  },
  promotionRunway: [
    { id: "01", name: "Discover", state: "done", note: "19 dynamic techniques mapped" },
    { id: "02", name: "Source", state: "done", note: "55 sources registered" },
    { id: "03", name: "Specify", state: "done", note: "Frozen skill and comparators" },
    { id: "04", name: "Evaluate", state: "current", note: "Pilot pending preflight" },
    { id: "05", name: "Approve", state: "pending", note: "Named human review required" },
    { id: "06", name: "Promote", state: "pending", note: "No production skill authorization" }
  ]
};
