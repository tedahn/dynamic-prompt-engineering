#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDir, "../..");
const dashboardFile = path.join(root, "dashboard/data.js");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function readJson(relativePath) {
  return JSON.parse(read(relativePath));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const next = text[index + 1];
    if (character === '"') {
      if (quoted && next === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      row.push(value);
      value = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && next === "\n") index += 1;
      row.push(value);
      if (row.some((cell) => cell !== "")) rows.push(row);
      row = [];
      value = "";
    } else {
      value += character;
    }
  }
  if (value || row.length) {
    row.push(value);
    rows.push(row);
  }
  const headers = rows.shift() || [];
  return rows.map((cells) => Object.fromEntries(headers.map((header, index) => [header, cells[index] || ""])));
}

function parseJsonLines(text) {
  return text.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
}

function markdownRows(text, idPattern) {
  return text.split(/\r?\n/)
    .filter((line) => idPattern.test(line))
    .map((line) => line.split("|").slice(1, -1).map((cell) => cell.trim()));
}

function stripMarkdown(value) {
  return String(value || "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .trim();
}

function countBy(items, key) {
  return items.reduce((counts, item) => {
    const value = item[key];
    if (value) counts[value] = (counts[value] || 0) + 1;
    return counts;
  }, {});
}

const workflowNames = {
  B00_RAW_1CALL: "Raw request",
  B01_STATIC_MIN_1CALL: "Minimal specification",
  B02_SHAM_2CALL: "Sham transformation",
  B03_PRO_PROMPT_2CALL: "Prompt-only transform",
  B04_PRO_INLINE_1CALL: "Inline professionalization",
  B05_HUMAN_SPEC_UPPER: "Human-authored ceiling"
};

const workflowIsolation = {
  B00_RAW_1CALL: "The value already supplied by the base model and authorized context.",
  B01_STATIC_MIN_1CALL: "Whether a small static contract is sufficient without dynamic transformation.",
  B02_SHAM_2CALL: "Extra call/context effects without a meaningful rewrite.",
  B03_PRO_PROMPT_2CALL: "The transformed prompt handed to a fresh executor.",
  B04_PRO_INLINE_1CALL: "The default skill behavior users would actually experience.",
  B05_HUMAN_SPEC_UPPER: "A diagnostic upper comparator, not a deployment alternative."
};

const techniqueBurden = {
  "DP-001": "medium", "DP-002": "low", "DP-003": "medium", "DP-004": "high", "DP-005": "low",
  "DP-006": "medium", "DP-007": "high", "DP-008": "high", "DP-009": "medium", "DP-010": "medium",
  "DP-011": "medium", "DP-012": "medium", "DP-013": "high", "DP-014": "high", "DP-015": "high",
  "DP-016": "high", "DP-017": "high", "DP-018": "high", "DP-019": "high"
};

const firstComparisons = new Set(["DP-001", "DP-002", "DP-003", "DP-006", "DP-012"]);

function techniqueCategory(id) {
  const number = Number(id.slice(3));
  if (number <= 5) return "request-transformer";
  if (number <= 10) return "retrieval-routing";
  return "offline-optimizer";
}

function buildData() {
  const techniqueText = read("research/DYNAMIC_PROMPTING_TECHNIQUES.md");
  const taxonomyText = read("research/TECHNIQUE_TAXONOMY.md");
  const workflowRegistry = readJson("research/evaluations/professionalize-prompt/workflows/workflows-v1.json");
  const staticAudit = readJson("research/evaluations/professionalize-prompt/scores/static-design-audit-2026-07-28.json");
  const pilotSource = readJson("research/evaluations/professionalize-prompt/pilot-v2/experiments/EXP-PP-V2-PILOT.json");
  const pilotInfrastructure = readJson("research/evaluations/professionalize-prompt/pilot-v2/results/PREFLIGHT-INFRA-2026-07-29.json");
  const statefulLoopConfig = readJson("research/evaluations/codex-stateful-loop/config/loop-v1.json");
  const statefulLoopArchitecture = read("research/evaluations/codex-stateful-loop/ARCHITECTURE.md");
  const statefulLoopEpisodes = parseJsonLines(read("research/evaluations/codex-stateful-loop/fixtures/episodes-dev-v1.jsonl"));
  const statefulLoopSeed = readJson("research/evaluations/codex-stateful-loop/state/seed-state-v1.json");
  const statefulLoopHoldout = readJson("research/evaluations/codex-stateful-loop/fixtures/holdout-manifest-v1.json");
  const contextComposerFixtures = parseJsonLines(read("research/evaluations/context-composer/fixtures/fixtures-v1.jsonl"));
  const contextComposerSnapshot = readJson("research/evaluations/context-composer/results/mechanical-summary-2026-07-29.json");
  const fixtures = parseJsonLines(read("research/evaluations/professionalize-prompt/fixtures/fixtures-v1.jsonl"));
  const fixtureById = Object.fromEntries(fixtures.map((fixture) => [fixture.fixture_id, fixture]));
  const scoreRows = parseCsv(read("research/evaluations/professionalize-prompt/scores/score-ledger.csv"))
    .map((row) => ({ ...row, domain: fixtureById[row.fixture_id]?.domain || row.domain || "" }));
  const claims = parseCsv(read("research/ledgers/claims.csv"));
  const sources = parseCsv(read("research/ledgers/sources.csv"));
  const evalCases = parseCsv(read("research/ledgers/eval-cases.csv"));
  const assumptions = parseCsv(read("research/ledgers/assumptions-forecasts.csv"));
  const changes = parseCsv(read("research/ledgers/change-log.csv"));
  const asOf = techniqueText.match(/\*\*As of:\*\*\s*([^\n]+)/)?.[1]?.trim() || new Date().toISOString().slice(0, 10);

  const dynamicTechniques = markdownRows(techniqueText, /^\|\s*DP-\d+\s*\|/).map((cells) => ({
    id: cells[0],
    name: stripMarkdown(cells[1]),
    category: techniqueCategory(cells[0]),
    burden: techniqueBurden[cells[0]],
    summary: stripMarkdown(cells[2]),
    workflow: stripMarkdown(cells[3]),
    ...(firstComparisons.has(cells[0]) ? { firstComparison: true } : {})
  }));

  const skillCandidates = markdownRows(taxonomyText, /^\|\s*T-\d+\s*\|/).map((cells) => ({
    id: cells[0],
    family: stripMarkdown(cells[1]),
    skillForm: stripMarkdown(cells[2]),
    state: stripMarkdown(cells[4]),
    falsifier: stripMarkdown(cells[5])
  }));

  const workflows = workflowRegistry.workflows.map((workflow) => ({
    id: workflow.workflow_id,
    shortId: workflow.workflow_id.slice(0, 3),
    name: workflowNames[workflow.workflow_id],
    kind: workflow.kind,
    calls: workflow.calls,
    transformer: workflow.transformer,
    purpose: workflow.purpose,
    isolates: workflowIsolation[workflow.workflow_id],
    ...(workflow.workflow_id === workflowRegistry.adoption_baseline ? { adoptionBaseline: true } : {})
  }));

  const ablations = workflowRegistry.ablations.map((ablation) => ({
    id: ablation.workflow_id,
    remove: ablation.remove.replace(/^./, (character) => character.toUpperCase()),
    parent: ablation.parent,
    ...(ablation.negative_control ? { negativeControl: true } : {})
  }));

  const fixtureDomains = countBy(fixtures, "domain");
  const fixtureSplits = countBy(fixtures, "split");
  const stateLayers = markdownRows(statefulLoopArchitecture, /^\|\s*L\d+\s*\|/).map((cells) => ({
    id: cells[0],
    contents: stripMarkdown(cells[1]),
    writer: stripMarkdown(cells[2]),
    visibility: stripMarkdown(cells[3])
  }));
  const statefulLoopStages = Object.entries(statefulLoopConfig.stages).map(([stageId, stage]) => {
    const episodes = stage.episode_ids?.length ?? stage.minimum_episodes;
    const trials = stage.trials ?? stage.minimum_trials;
    const runs = stage.minimum_runs ?? episodes * stage.condition_ids.length * trials;
    return {
      id: stageId,
      split: stage.split,
      episodes,
      conditions: stage.condition_ids.length,
      trials,
      runs,
      decisionUse: stage.decision_use,
      status: "designed-not-run"
    };
  });

  return {
    schemaVersion: "1.0",
    meta: {
      asOf,
      generatedAt: new Date().toISOString().slice(0, 10),
      snapshotId: staticAudit.snapshot_id,
      bundleSha256: pilotSource.skill_bundle_sha256,
      classification: staticAudit.classification,
      adoptionBaseline: workflowRegistry.adoption_baseline
    },
    staticAudit: {
      assessmentType: staticAudit.assessment_type,
      auditedAt: staticAudit.audited_at,
      rubricId: staticAudit.rubric_id,
      designQuality: staticAudit.design_quality_subtotal.normalized_score,
      evidenceReadiness: staticAudit.evidence_readiness_score,
      behavioralEfficacy: staticAudit.behavioral_efficacy,
      note: staticAudit.notes
    },
    scoreLedger: { rows: scoreRows, recordCount: scoreRows.length, status: scoreRows.length ? "provisional" : "not-run" },
    fixtures: {
      count: fixtures.length,
      splits: fixtureSplits,
      modes: countBy(fixtures, "mode"),
      ambiguity: countBy(fixtures, "ambiguity"),
      domains: fixtureDomains
    },
    workflows,
    ablations,
    pilot: {
      experimentId: pilotSource.experiment_id,
      status: pilotSource.status,
      frozenArtifacts: Array.isArray(pilotSource.frozen_artifacts) ? "frozen" : pilotSource.frozen_artifacts.status,
      workflows: pilotSource.pilot.workflow_ids,
      fixtureIds: pilotSource.pilot.fixture_ids,
      domains: pilotSource.pilot.coverage.domains,
      trials: pilotSource.pilot.trials,
      executionCells: pilotSource.pilot.execution_cells,
      concurrency: pilotSource.pilot.concurrency,
      executionSeed: pilotSource.pilot.execution_seed,
      gradeSeed: pilotSource.pilot.grade_seed,
      modelAlias: pilotSource.target_surface.model_alias,
      reasoningEffort: pilotSource.target_surface.reasoning_effort,
      evidenceState: pilotSource.grading.evidence_state,
      humanReview: pilotSource.grading.human_review,
      boundary: `${pilotSource.execution_boundary.data}; network and external side effects forbidden`,
      preflightInfrastructure: {
        evidenceState: pilotInfrastructure.evidence_state,
        completedCells: pilotInfrastructure.preflight.completed_cells,
        scoredCells: pilotInfrastructure.scored.completed_cells,
        replacementApproval: pilotInfrastructure.replacement.approval
      }
    },
    statefulLoop: {
      processId: statefulLoopConfig.process_id,
      asOf: statefulLoopConfig.as_of,
      evidenceState: statefulLoopConfig.evidence_state,
      liveAuthorized: statefulLoopConfig.live_execution.authorized,
      behavioralEfficacy: "Unknown",
      activeState: {
        snapshotId: statefulLoopSeed.snapshot_id,
        revision: statefulLoopSeed.revision,
        status: statefulLoopSeed.status,
        entries: statefulLoopSeed.entries.length
      },
      episodes: {
        development: statefulLoopEpisodes.length,
        holdoutCommitted: statefulLoopHoldout.contents_committed ? statefulLoopHoldout.minimum_episode_count : 0,
        holdoutMinimum: statefulLoopHoldout.minimum_episode_count,
        holdoutStatus: statefulLoopHoldout.status
      },
      mutableBoundary: statefulLoopConfig.mutable_boundary,
      conditions: statefulLoopConfig.conditions.map((condition) => ({
        id: condition.condition_id,
        contextMode: condition.context_mode,
        updates: condition.updates,
        role: condition.role
      })),
      stages: statefulLoopStages,
      stateLayers,
      promotion: statefulLoopConfig.promotion_defaults,
      stopRules: statefulLoopConfig.stop_rules
    },
    contextComposer: {
      snapshotId: contextComposerSnapshot.snapshot_id,
      scope: contextComposerSnapshot.scope,
      behavioralEfficacy: contextComposerSnapshot.behavioral_efficacy,
      gateResult: contextComposerSnapshot.gate_result,
      fixtureCount: contextComposerFixtures.length,
      families: countBy(contextComposerFixtures, "family"),
      conditions: Object.entries(contextComposerSnapshot.conditions).map(([id, metrics]) => ({ id, ...metrics })),
      limitations: contextComposerSnapshot.limitations
    },
    dynamicTechniques,
    skillCandidates,
    ledgers: {
      claims: { count: claims.length, status: countBy(claims, "status"), confidence: countBy(claims, "confidence") },
      sources: { count: sources.length, type: countBy(sources, "source_type") },
      evalCases: { count: evalCases.length, status: countBy(evalCases, "status") },
      assumptions: { count: assumptions.length, status: countBy(assumptions, "status") },
      changes: { count: changes.length, status: countBy(changes, "status") }
    },
    promotionRunway: [
      { id: "01", name: "Discover", state: "done", note: `${dynamicTechniques.length} dynamic techniques mapped` },
      { id: "02", name: "Source", state: "done", note: `${sources.length} sources registered` },
      { id: "03", name: "Specify", state: "done", note: "Frozen skill and comparators" },
      { id: "04", name: "Evaluate", state: scoreRows.length ? "done" : "current", note: scoreRows.length ? `${scoreRows.length} rows awaiting review` : "Pilot pending preflight" },
      { id: "05", name: "Approve", state: "pending", note: "Named human review required" },
      { id: "06", name: "Promote", state: "pending", note: "No production skill authorization" }
    ]
  };
}

function loadCommittedData() {
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(dashboardFile, "utf8"), sandbox, { filename: dashboardFile });
  return sandbox.window.PROMPT_RESEARCH_DATA;
}

function checkData(expected, actual) {
  const checks = [
    ["snapshot ID", expected.meta.snapshotId, actual.meta.snapshotId],
    ["bundle SHA", expected.meta.bundleSha256, actual.meta.bundleSha256],
    ["workflow IDs", expected.workflows.map((item) => item.id).join(","), actual.workflows.map((item) => item.id).join(",")],
    ["ablation IDs", expected.ablations.map((item) => item.id).join(","), actual.ablations.map((item) => item.id).join(",")],
    ["score rows", expected.scoreLedger.rows.length, actual.scoreLedger.rows.length],
    ["fixtures", JSON.stringify(expected.fixtures), JSON.stringify(actual.fixtures)],
    ["dynamic technique IDs", expected.dynamicTechniques.map((item) => item.id).join(","), actual.dynamicTechniques.map((item) => item.id).join(",")],
    ["skill candidate IDs", expected.skillCandidates.map((item) => item.id).join(","), actual.skillCandidates.map((item) => item.id).join(",")],
    ["ledger counts", JSON.stringify(Object.fromEntries(Object.entries(expected.ledgers).map(([key, value]) => [key, value.count]))), JSON.stringify(Object.fromEntries(Object.entries(actual.ledgers).map(([key, value]) => [key, value.count])))],
    ["pilot state", `${expected.pilot.status}:${expected.pilot.executionCells}`, `${actual.pilot.status}:${actual.pilot.executionCells}`],
    ["stateful loop", JSON.stringify(expected.statefulLoop), JSON.stringify(actual.statefulLoop)],
    ["context composer", JSON.stringify(expected.contextComposer), JSON.stringify(actual.contextComposer)]
  ];
  const failures = checks.filter(([, expectedValue, actualValue]) => expectedValue !== actualValue);
  if (failures.length) {
    for (const [label, expectedValue, actualValue] of failures) {
      console.error(`${label}: expected ${expectedValue}; committed ${actualValue}`);
    }
    process.exitCode = 1;
    return;
  }
  console.log(`dashboard data check passed: ${checks.length} source-derived invariants`);
}

try {
  const built = buildData();
  if (process.argv.includes("--write")) {
    fs.writeFileSync(dashboardFile, `window.PROMPT_RESEARCH_DATA = ${JSON.stringify(built, null, 2)};\n`);
    console.log(`wrote ${path.relative(root, dashboardFile)}`);
  } else if (process.argv.includes("--check")) {
    checkData(built, loadCommittedData());
  } else {
    console.log(JSON.stringify({
      snapshotId: built.meta.snapshotId,
      techniques: built.dynamicTechniques.length,
      candidates: built.skillCandidates.length,
      workflows: built.workflows.length,
      fixtures: built.fixtures.count,
      scoreRows: built.scoreLedger.rows.length,
      pilotStatus: built.pilot.status
    }));
  }
} catch (error) {
  console.error(`dashboard data build failed: ${error.message}`);
  process.exitCode = 1;
}
