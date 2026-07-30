(function () {
  "use strict";

  const data = window.PROMPT_RESEARCH_DATA;
  if (!data) {
    document.body.innerHTML = '<main class="view"><h1>Dashboard data unavailable.</h1><p>Rebuild <code>dashboard/data.js</code> from the repository sources.</p></main>';
    return;
  }

  const byId = (id) => document.getElementById(id);
  const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const humanize = (value) => String(value ?? "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  function bind(name, value) {
    all(`[data-bind="${name}"]`).forEach((node) => {
      node.textContent = value;
    });
  }

  function initializeBindings() {
    const scoreRows = data.scoreLedger.rows.length;
    bind("as-of", data.meta.asOf);
    bind("snapshot-short", data.meta.snapshotId.replace("professionalize-prompt@", ""));
    bind("score-rows", scoreRows);
    bind("pilot-status", data.pilot.status);
    bind("pilot-status-short", data.pilot.status.includes("pending-preflight") ? "Pending preflight" : humanize(data.pilot.status));
    bind("dynamic-techniques", data.dynamicTechniques.length);
    bind("skill-candidates", data.skillCandidates.length);
    bind("workflows", data.workflows.length);
    bind("fixtures", data.fixtures.count);
    bind("sources", data.ledgers.sources.count);
    bind("fixture-dev", data.fixtures.splits.dev);
    bind("fixture-holdout", data.fixtures.splits.holdout);
    bind("behavioral-efficacy", scoreRows ? "Provisional results available" : "Unknown");
  }

  function activateView(name) {
    const allowed = new Set(["overview", "workflows", "evaluations", "techniques"]);
    const viewName = allowed.has(name) ? name : "overview";
    all("[data-view]").forEach((view) => {
      const active = view.dataset.view === viewName;
      view.hidden = !active;
      view.classList.toggle("view--active", active);
    });
    all("[data-view-link]").forEach((link) => {
      if (link.dataset.viewLink === viewName) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.title = `${humanize(viewName)} · Prompt Research Observatory`;
    window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }

  function initializeNavigation() {
    const route = () => activateView(window.location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", route);
    route();
  }

  function renderRunway() {
    byId("promotion-runway").innerHTML = data.promotionRunway.map((step) => `
      <li class="is-${escapeHtml(step.state)}">
        <span class="runway-marker" aria-hidden="true"></span>
        <span class="runway-step">${escapeHtml(step.id)}</span>
        <strong>${escapeHtml(step.name)}</strong>
        <p>${escapeHtml(step.note)}</p>
      </li>
    `).join("");
  }

  function renderScoreBars() {
    const scores = [
      { label: "Design quality", note: "Static rubric", value: data.staticAudit.designQuality, css: "" },
      { label: "Evidence readiness", note: "Static review", value: data.staticAudit.evidenceReadiness, css: "score-fill--readiness" },
      { label: "Behavioral efficacy", note: "Held-out outcomes", value: null, css: "" }
    ];
    byId("score-bars").innerHTML = scores.map((score) => `
      <div class="score-row">
        <div class="score-row__label"><strong>${escapeHtml(score.label)}</strong><span>${escapeHtml(score.note)}</span></div>
        <div class="score-track ${score.value === null ? "score-track--unknown" : ""}" aria-hidden="true">
          ${score.value === null ? "" : `<div class="score-fill ${score.css}" style="width:${score.value}%"></div>`}
        </div>
        <span class="score-row__value ${score.value === null ? "is-unknown" : ""}">${score.value === null ? "Unknown" : score.value.toFixed(1)}</span>
      </div>
    `).join("");
  }

  function workflowResult(workflowId) {
    const rows = data.scoreLedger.rows.filter((row) => row.workflow_id === workflowId);
    if (!rows.length) return { label: "Not run", detail: "No official behavioral rows exist for this workflow." };
    const values = rows.map((row) => Number(row.outcome_score)).filter(Number.isFinite);
    const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    return {
      label: mean === null ? `${rows.length} records` : `${mean.toFixed(2)} provisional mean`,
      detail: "Behavioral records exist, but remain provisional until the required review gate is complete."
    };
  }

  function selectWorkflow(id) {
    const workflow = data.workflows.find((item) => item.id === id);
    if (!workflow) return;
    all(".workflow-node").forEach((node) => {
      node.classList.toggle("is-selected", node.dataset.workflowId === id);
      node.setAttribute("aria-pressed", node.dataset.workflowId === id ? "true" : "false");
    });
    const result = workflowResult(id);
    byId("workflow-inspector").innerHTML = `
      <p class="eyebrow">${escapeHtml(workflow.shortId)} · ${escapeHtml(humanize(workflow.kind))}</p>
      <h2>${escapeHtml(workflow.name)}</h2>
      <p>${escapeHtml(workflow.purpose)}</p>
      <div class="inspector-meta">
        <div><span>Calls</span><strong>${workflow.calls}</strong></div>
        <div><span>Result</span><strong>${escapeHtml(result.label)}</strong></div>
        <div><span>Transformer</span><strong>${escapeHtml(workflow.transformer)}</strong></div>
        <div><span>Role</span><strong>${workflow.adoptionBaseline ? "Adoption baseline" : escapeHtml(humanize(workflow.kind))}</strong></div>
      </div>
      <p><strong>What it isolates:</strong> ${escapeHtml(workflow.isolates)}</p>
      <div class="inspector-callout">${escapeHtml(result.detail)}</div>
    `;
  }

  function renderWorkflows() {
    const rail = byId("workflow-rail");
    rail.innerHTML = data.workflows.map((workflow) => `
      <button class="workflow-node" type="button" data-workflow-id="${escapeHtml(workflow.id)}" data-workflow-kind="${escapeHtml(workflow.kind)}" aria-pressed="false">
        <span class="workflow-node__id">${escapeHtml(workflow.shortId)}</span>
        <span class="workflow-node__name">${escapeHtml(workflow.name)}${workflow.adoptionBaseline ? " · baseline" : ""}</span>
        <span class="workflow-node__purpose">${escapeHtml(workflow.purpose)}</span>
        <span class="workflow-node__arrow" aria-hidden="true">→</span>
      </button>
    `).join("");
    all(".workflow-node", rail).forEach((node) => node.addEventListener("click", () => selectWorkflow(node.dataset.workflowId)));

    all("[data-workflow-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        const filter = button.dataset.workflowFilter;
        all("[data-workflow-filter]").forEach((item) => {
          const active = item === button;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", String(active));
        });
        all(".workflow-node", rail).forEach((node) => {
          node.hidden = filter !== "all" && node.dataset.workflowKind !== filter;
        });
        const first = all(".workflow-node", rail).find((node) => !node.hidden);
        if (first) selectWorkflow(first.dataset.workflowId);
      });
    });
    selectWorkflow(data.meta.adoptionBaseline);
  }

  function renderAblations() {
    const parent = data.workflows.find((workflow) => workflow.id === "B04_PRO_INLINE_1CALL");
    byId("ablation-tree").innerHTML = `
      <article class="ablation-node ablation-node--control">
        <span>${escapeHtml(parent.shortId)} · parent</span>
        <strong>${escapeHtml(parent.name)}</strong>
        <small>Full mechanism</small>
      </article>
      ${data.ablations.map((item) => `
        <article class="ablation-node">
          <span>${escapeHtml(item.id.replace(/_.+$/, ""))}${item.negativeControl ? " · negative control" : ""}</span>
          <strong>Remove ${escapeHtml(item.remove)}</strong>
          <small>Designed · no behavioral rows</small>
        </article>
      `).join("")}
    `;
  }

  function mean(values) {
    const numeric = values.map(Number).filter(Number.isFinite);
    return numeric.length ? numeric.reduce((sum, value) => sum + value, 0) / numeric.length : null;
  }

  function renderOutcomeMatrix() {
    const domains = Object.keys(data.fixtures.domains);
    const rows = data.workflows.filter((workflow) => workflow.kind !== "diagnostic-ceiling");
    const hasScores = data.scoreLedger.rows.length > 0;
    byId("matrix-state").textContent = hasScores ? "Provisional data" : "Awaiting runs";
    byId("outcome-matrix").innerHTML = `
      <table class="outcome-table">
        <caption class="visually-hidden">Mean outcome score by workflow and domain</caption>
        <thead><tr><th scope="col">Workflow</th>${domains.map((domain) => `<th scope="col">${escapeHtml(humanize(domain))}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((workflow) => `
            <tr>
              <th scope="row">${escapeHtml(workflow.shortId)} · ${escapeHtml(workflow.name)}</th>
              ${domains.map((domain) => {
                const records = data.scoreLedger.rows.filter((row) => row.workflow_id === workflow.id && row.domain === domain);
                const score = mean(records.map((record) => record.outcome_score));
                return score === null
                  ? '<td class="matrix-cell--pending" aria-label="Not run">—</td>'
                  : `<td class="matrix-cell--scored" style="--heat:${Math.max(10, Math.min(100, score * 10))}%">${score.toFixed(2)}</td>`;
              }).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  function renderFixtureCoverage() {
    const dev = data.fixtures.splits.dev / data.fixtures.count * 100;
    const holdout = data.fixtures.splits.holdout / data.fixtures.count * 100;
    byId("fixture-dev-bar").style.width = `${dev}%`;
    byId("fixture-holdout-bar").style.width = `${holdout}%`;
    byId("domain-list").innerHTML = Object.entries(data.fixtures.domains).map(([domain, count]) => `
      <div class="domain-row"><span>${escapeHtml(humanize(domain))}</span><strong>${count}</strong></div>
    `).join("");
  }

  function renderPilot() {
    const facts = [
      ["Experiment", data.pilot.experimentId],
      ["Workflows", data.pilot.workflows.length],
      ["Fixtures", data.pilot.fixtureIds.length],
      ["Trials each", data.pilot.trials],
      ["Execution cells", data.pilot.executionCells],
      ["Model alias", data.pilot.modelAlias],
      ["Reasoning", data.pilot.reasoningEffort],
      ["Preflight evidence", `${data.pilot.preflightInfrastructure.completedCells} discarded · ${data.pilot.preflightInfrastructure.scoredCells} scored`],
      ["Replacement gate", data.pilot.preflightInfrastructure.replacementApproval],
      ["Data boundary", "Synthetic only"]
    ];
    byId("pilot-facts").innerHTML = facts.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
    const sequence = [
      { id: "01", name: "Freeze", note: "Artifacts and expected plan hash" },
      { id: "02", name: "Preflight", note: "Replacement approval required", current: true },
      { id: "03", name: "Execute", note: "45 blinded scored cells" },
      { id: "04", name: "Grade", note: "Two provisional model graders" },
      { id: "05", name: "Review", note: "Human gate before final score" }
    ];
    byId("pilot-sequence").innerHTML = sequence.map((step) => `
      <li class="${step.current ? "is-current" : ""}"><span>${step.id}</span><strong>${escapeHtml(step.name)}</strong><small>${escapeHtml(step.note)}</small></li>
    `).join("");
  }

  function renderStatefulLoop() {
    const loop = data.statefulLoop;
    if (!loop) return;

    const cycle = [
      { id: "01", name: "Observe", note: `${loop.episodes.development} development episodes` },
      { id: "02", name: "Propose", note: "One context delta" },
      { id: "03", name: "Validate", note: "Schema · provenance · leakage" },
      { id: "04", name: "Evaluate", note: "Isolated and blinded" },
      { id: "05", name: "Approve", note: "Named human only" },
      { id: "06", name: "Canary", note: "Monitor or roll back" }
    ];
    byId("state-loop-cycle").innerHTML = cycle.map((step) => `
      <div class="cycle-step">
        <span>${step.id}</span>
        <strong>${escapeHtml(step.name)}</strong>
        <small>${escapeHtml(step.note)}</small>
      </div>
    `).join("");

    byId("state-loop-status").textContent = loop.liveAuthorized
      ? humanize(loop.evidenceState)
      : `${humanize(loop.evidenceState)} · live run blocked`;
    byId("state-loop-boundary").textContent = `${loop.mutableBoundary.operations.map(humanize).join(" · ")}. ${loop.mutableBoundary.forbidden.length} protected surfaces remain immutable.`;
    byId("state-loop-snapshot").innerHTML = `
      <span>Active snapshot</span>
      <strong>${escapeHtml(loop.activeState.snapshotId)}</strong>
      <small>Revision ${loop.activeState.revision} · ${loop.activeState.entries} entries · ${escapeHtml(humanize(loop.activeState.status))}</small>
    `;

    byId("state-loop-stages").innerHTML = loop.stages.map((stage, index) => `
      <article class="loop-stage${stage.id === "full" ? " loop-stage--holdout" : ""}">
        <div class="loop-stage__index">0${index + 1}</div>
        <div>
          <span>${escapeHtml(humanize(stage.id))} · ${escapeHtml(humanize(stage.split))}</span>
          <strong>${stage.runs >= 216 ? "≥" : ""}${stage.runs} runs</strong>
          <small>${stage.episodes >= 24 ? "≥" : ""}${stage.episodes} episodes × ${stage.conditions} policies × ${stage.trials >= 3 && stage.id === "full" ? "≥" : ""}${stage.trials} trials</small>
          <p>${escapeHtml(humanize(stage.decisionUse))}</p>
        </div>
      </article>
    `).join("");

    byId("state-loop-conditions").innerHTML = loop.conditions.map((condition) => {
      const emphasized = condition.role === "candidate" || condition.role === "adoption-baseline";
      return `
        <article class="loop-condition${emphasized ? ` loop-condition--${escapeHtml(condition.role)}` : ""}">
          <div>
            <code>${escapeHtml(condition.id)}</code>
            <span>${escapeHtml(humanize(condition.role))}</span>
          </div>
          <p>${escapeHtml(humanize(condition.contextMode))}</p>
          <small>Updates: ${escapeHtml(humanize(condition.updates))}</small>
        </article>
      `;
    }).join("");

    byId("state-loop-layers").innerHTML = loop.stateLayers.map((layer) => `
      <article class="state-layer">
        <span>${escapeHtml(layer.id)}</span>
        <div><strong>${escapeHtml(layer.contents)}</strong><small>Writer: ${escapeHtml(layer.writer)}</small></div>
        <p>${escapeHtml(layer.visibility)}</p>
      </article>
    `).join("");
  }

  function renderContextComposer() {
    const composer = data.contextComposer;
    if (!composer) return;
    byId("context-composer-status").textContent = `${humanize(composer.gateResult)} · behavioral unknown`;
    byId("context-composer-scope").textContent = `${composer.fixtureCount} synthetic fixture families · ${composer.negativeSecurityCases} negative security cases · ${composer.scope}.`;
    byId("context-composer-conditions").innerHTML = composer.conditions.map((condition) => `
      <article class="loop-condition${condition.id.startsWith("C") ? " loop-condition--candidate" : ""}">
        <div><code>${escapeHtml(condition.id)}</code><span>${condition.critical_failures} critical · ${condition.stale_failures} stale</span></div>
        <p>Recall ${condition.required_recall_macro.toFixed(2)} · precision ${condition.precision_macro.toFixed(2)}</p>
        <small>Route ${(condition.route_accuracy * 100).toFixed(0)}% · ordering failures ${condition.ordering_failures}</small>
      </article>
    `).join("");
    byId("context-composer-limit").textContent = composer.limitations[composer.limitations.length - 1];
  }

  const categoryLabels = {
    "request-transformer": "Request transformers",
    "retrieval-routing": "Retrieval & routing",
    "offline-optimizer": "Scored optimizers"
  };

  function openTechniqueDetail(technique) {
    let detail = byId("technique-detail");
    if (!detail) {
      detail = document.createElement("div");
      detail.id = "technique-detail";
      detail.className = "technique-detail";
      byId("technique-columns").insertAdjacentElement("afterend", detail);
    }
    detail.hidden = false;
    detail.innerHTML = `
      <div><span class="eyebrow">${escapeHtml(technique.id)} · ${escapeHtml(humanize(technique.burden))} burden</span><strong>${escapeHtml(technique.name)}</strong></div>
      <div><p>${escapeHtml(technique.summary)}</p><p><strong>Reproducible workflow:</strong> ${escapeHtml(technique.workflow)}</p></div>
      <button type="button" aria-label="Close technique details">×</button>
    `;
    detail.querySelector("button").addEventListener("click", () => {
      detail.hidden = true;
    });
  }

  function renderTechniques() {
    const columns = byId("technique-columns");
    columns.innerHTML = Object.entries(categoryLabels).map(([category, label]) => {
      const techniques = data.dynamicTechniques.filter((item) => item.category === category);
      return `
        <section class="technique-column" data-technique-column="${escapeHtml(category)}">
          <h3 class="technique-column__title">${escapeHtml(label)} <span>${techniques.length}</span></h3>
          ${["high", "medium", "low"].map((burden) => `
            <div class="burden-band" data-burden="${burden}">
              <span class="burden-band__label">${humanize(burden)}</span>
              ${techniques.filter((item) => item.burden === burden).map((item) => `
                <button class="technique-chip" type="button" data-technique-id="${escapeHtml(item.id)}" data-technique-category="${escapeHtml(item.category)}" data-search="${escapeHtml(`${item.name} ${item.summary} ${item.workflow}`.toLowerCase())}">
                  <span class="technique-chip__id">${escapeHtml(item.id)}${item.firstComparison ? " · first" : ""}</span>
                  <span class="technique-chip__name">${escapeHtml(item.name)}</span>
                </button>
              `).join("")}
            </div>
          `).join("")}
        </section>
      `;
    }).join("");

    all(".technique-chip", columns).forEach((chip) => {
      chip.addEventListener("click", () => openTechniqueDetail(data.dynamicTechniques.find((item) => item.id === chip.dataset.techniqueId)));
    });

    let activeFilter = "all";
    const applyFilters = () => {
      const query = byId("technique-search").value.trim().toLowerCase();
      all(".technique-chip", columns).forEach((chip) => {
        const familyMatch = activeFilter === "all" || chip.dataset.techniqueCategory === activeFilter;
        const queryMatch = !query || chip.dataset.search.includes(query) || chip.dataset.techniqueId.toLowerCase().includes(query);
        chip.hidden = !(familyMatch && queryMatch);
      });
      all(".technique-column", columns).forEach((column) => {
        const visible = all(".technique-chip", column).some((chip) => !chip.hidden);
        column.classList.toggle("is-empty", !visible);
      });
    };

    all("[data-technique-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        activeFilter = button.dataset.techniqueFilter;
        all("[data-technique-filter]").forEach((item) => {
          const active = item === button;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", String(active));
        });
        applyFilters();
      });
    });
    byId("technique-search").addEventListener("input", applyFilters);
  }

  function renderCandidates() {
    byId("candidate-list").innerHTML = data.skillCandidates.map((candidate) => `
      <article class="candidate-row">
        <span class="candidate-row__id">${escapeHtml(candidate.id)}</span>
        <strong>${escapeHtml(candidate.family)}</strong>
        <code>${escapeHtml(candidate.skillForm)}</code>
        <p><strong>${escapeHtml(candidate.state)}.</strong> Falsifier: ${escapeHtml(candidate.falsifier)}</p>
      </article>
    `).join("");
  }

  function renderLedgers() {
    const items = [
      [data.ledgers.claims.count, "Claims", `${data.ledgers.claims.status["Grounded fact"]} grounded facts`],
      [data.ledgers.sources.count, "Sources", `${data.ledgers.sources.type["research paper"]} research papers`],
      [data.ledgers.evalCases.count, "Evaluation cases", `${data.ledgers.evalCases.status.designed} designed`],
      [data.ledgers.assumptions.count, "Assumptions", `${data.ledgers.assumptions.status.open} open`],
      [data.ledgers.changes.count, "Recorded changes", "Validated records"]
    ];
    byId("ledger-grid").innerHTML = items.map(([count, label, note]) => `
      <article class="ledger-item"><strong>${count}</strong><span>${escapeHtml(label)}</span><small>${escapeHtml(note)}</small></article>
    `).join("");
  }

  function initialize() {
    initializeBindings();
    initializeNavigation();
    renderRunway();
    renderScoreBars();
    renderWorkflows();
    renderAblations();
    renderOutcomeMatrix();
    renderFixtureCoverage();
    renderPilot();
    renderStatefulLoop();
    renderContextComposer();
    renderTechniques();
    renderCandidates();
    renderLedgers();
  }

  initialize();
}());
