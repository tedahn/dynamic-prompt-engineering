import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const dashboardDir = path.resolve(testDir, "..");
const html = fs.readFileSync(path.join(dashboardDir, "index.html"), "utf8");
const css = fs.readFileSync(path.join(dashboardDir, "styles.css"), "utf8");
const app = fs.readFileSync(path.join(dashboardDir, "app.js"), "utf8");
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(dashboardDir, "data.js"), "utf8"), sandbox);
const data = sandbox.window.PROMPT_RESEARCH_DATA;

test("dashboard snapshot preserves the frozen evaluation identity", () => {
  assert.equal(data.meta.snapshotId, "professionalize-prompt@2026-07-28-eec246d1");
  assert.equal(data.meta.adoptionBaseline, "B01_STATIC_MIN_1CALL");
  assert.equal(data.workflows.find((workflow) => workflow.adoptionBaseline).id, data.meta.adoptionBaseline);
});

test("dashboard renders missing behavioral evidence as unknown", () => {
  assert.equal(data.scoreLedger.rows.length, 0);
  assert.match(data.staticAudit.behavioralEfficacy, /Unknown/i);
  assert.match(html, /A blank result is a result state/);
  assert.match(app, /score-track--unknown/);
});

test("dashboard preserves the discarded preflight infrastructure boundary", () => {
  assert.equal(data.pilot.frozenArtifacts, "frozen");
  assert.equal(data.pilot.preflightInfrastructure.completedCells, 3);
  assert.equal(data.pilot.preflightInfrastructure.scoredCells, 0);
  assert.match(data.pilot.preflightInfrastructure.replacementApproval, /pending/i);
});

test("dashboard covers current research registries", () => {
  assert.equal(data.dynamicTechniques.length, 19);
  assert.equal(data.skillCandidates.length, 20);
  assert.equal(data.workflows.length, 6);
  assert.equal(data.ablations.length, 7);
  assert.equal(data.fixtures.count, 45);
  assert.deepEqual({ ...data.fixtures.splits }, { dev: 30, holdout: 15 });
});

test("stateful loop keeps design evidence separate from behavioral results", () => {
  assert.equal(data.statefulLoop.evidenceState, "design-only");
  assert.equal(data.statefulLoop.liveAuthorized, false);
  assert.match(data.statefulLoop.behavioralEfficacy, /Unknown/i);
  assert.deepEqual(Array.from(data.statefulLoop.stages, (stage) => stage.runs), [9, 144, 216]);
  assert.equal(data.statefulLoop.episodes.development, 12);
  assert.equal(data.statefulLoop.episodes.holdoutCommitted, 0);
  assert.equal(data.statefulLoop.episodes.holdoutMinimum, 24);
});

test("stateful loop visualizes a frozen baseline, gated candidate, and human gate", () => {
  const byId = Object.fromEntries(Array.from(data.statefulLoop.conditions, (condition) => [condition.id, condition]));
  assert.equal(byId.B3_RETRIEVAL_ONLY.role, "adoption-baseline");
  assert.equal(byId.C1_GATED_EVOLVING.role, "candidate");
  assert.equal(data.statefulLoop.promotion.human_approval_required, true);
  assert.equal(data.statefulLoop.stateLayers.length, 8);
  assert.match(html, /id="state-loop-cycle"/);
  assert.match(html, /State evolves\. Authority does not\./);
  assert.match(app, /function renderStatefulLoop/);
  assert.match(css, /\.loop-condition--candidate/);
});

test("context composer visualizes mechanical scores without claiming behavioral efficacy", () => {
  assert.equal(data.contextComposer.fixtureCount, 12);
  assert.equal(data.contextComposer.negativeSecurityCases, 4);
  assert.equal(data.contextComposer.behavioralEfficacy, null);
  assert.equal(data.contextComposer.conditions.length, 5);
  assert.equal(data.contextComposer.conditions.find((item) => item.id === "C1_COMPOSED").critical_failures, 0);
  assert.match(html, /Safer packets, behavioral outcome unknown/);
  assert.match(html, /skills\/context-composer\/SKILL\.md/);
  assert.match(app, /function renderContextComposer/);
  assert.match(app, /negative security cases/);
});

test("dashboard provides semantic views and accessibility affordances", () => {
  for (const view of ["overview", "workflows", "evaluations", "techniques"]) {
    assert.match(html, new RegExp(`data-view="${view}"`));
  }
  assert.match(html, /class="skip-link"/);
  assert.match(html, /aria-live="polite"/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /:focus-visible/);
});

test("future score rows have a matrix rendering path", () => {
  assert.match(app, /outcome_score/);
  assert.match(app, /matrix-cell--scored/);
  assert.match(app, /Provisional results available/);
});
