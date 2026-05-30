const sampleData = {
  changes: [
    {
      action: "add_category_gate",
      entity_type: "Product",
      label: "battery",
      confidence: 0.78,
      domain: "product",
      module: null,
      parent: null,
      field: "instanceOf",
      value: "instance of",
      target_type: "gate_type",
      support: 3,
      source_entity_ids: ["Q123", "Q999", "Q1000"],
      examples: ["Lithium-ion battery -> instance of -> battery"],
      evidence: [
        { source: "unclassified", detail: "candidate could not be routed into any existing category", weight: 0.2 },
        { source: "gate_statement", detail: "P31 / instance of", weight: 0.35 }
      ],
      review_required: false
    },
    {
      action: "add_module",
      entity_type: "Product",
      label: "manufacturer_relations",
      confidence: 0.72,
      domain: "product",
      module: "manufacturer_relations",
      parent: null,
      field: "manufacturer",
      value: "manufacturer",
      target_type: "relational",
      support: 2,
      source_entity_ids: ["Q123", "Q1000"],
      examples: ["Lithium-ion battery -> manufacturer_relations -> manufacturer"],
      evidence: [
        { source: "module_gap", detail: "candidate matched a category but no existing module", weight: 0.18 },
        { source: "statement", detail: "P176 / manufacturer", weight: 0.18 }
      ],
      review_required: true
    },
    {
      action: "add_concept",
      entity_type: "Technology",
      label: "photolithography",
      confidence: 0.81,
      domain: "technology",
      module: "technology_relations",
      parent: "manufacturing process",
      field: null,
      value: null,
      target_type: null,
      support: 1,
      source_entity_ids: ["Q183907"],
      examples: ["photolithography (Q183907)"],
      evidence: [
        { source: "category_gate_label", detail: "gate labels: manufacturing process", weight: 0.16 }
      ],
      review_required: false
    },
    {
      action: "add_property_type",
      entity_type: "Enterprise",
      label: "Enterprise",
      confidence: 0.88,
      domain: "enterprise",
      module: "common_properties",
      parent: null,
      field: "officialWebsite",
      value: "official website",
      target_type: "url",
      support: 2,
      source_entity_ids: ["Q900006", "Q900007"],
      examples: ["ASML Holding -> officialWebsite -> https://www.asml.com/"],
      evidence: [
        { source: "statement", detail: "P856 / official website", weight: 0.18 }
      ],
      review_required: false
    },
    {
      action: "add_relation_type",
      entity_type: "Product",
      label: "Product",
      confidence: 0.9,
      domain: "product",
      module: "supply_relations",
      parent: null,
      field: "manufacturer",
      value: "manufacturer",
      target_type: "Enterprise",
      support: 4,
      source_entity_ids: ["Q123", "Q999", "Q1000", "Q2000"],
      examples: ["Lithium-ion battery -> manufacturer -> Panasonic"],
      evidence: [
        { source: "statement", detail: "P176 / manufacturer", weight: 0.18 }
      ],
      review_required: false
    }
  ]
};

const state = {
  changes: [],
  selectedId: null,
  filters: {
    search: "",
    action: "",
    status: "",
    confidence: 0
  }
};

const els = {
  fileInput: document.querySelector("#fileInput"),
  loadSampleBtn: document.querySelector("#loadSampleBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  datasetMeta: document.querySelector("#datasetMeta"),
  totalCount: document.querySelector("#totalCount"),
  acceptedCount: document.querySelector("#acceptedCount"),
  rejectedCount: document.querySelector("#rejectedCount"),
  pendingCount: document.querySelector("#pendingCount"),
  avgConfidence: document.querySelector("#avgConfidence"),
  searchInput: document.querySelector("#searchInput"),
  actionFilter: document.querySelector("#actionFilter"),
  statusFilter: document.querySelector("#statusFilter"),
  confidenceFilter: document.querySelector("#confidenceFilter"),
  confidenceValue: document.querySelector("#confidenceValue"),
  changeList: document.querySelector("#changeList"),
  emptyState: document.querySelector("#emptyState"),
  detailView: document.querySelector("#detailView"),
  detailAction: document.querySelector("#detailAction"),
  detailLabel: document.querySelector("#detailLabel"),
  detailSubhead: document.querySelector("#detailSubhead"),
  confidenceBadge: document.querySelector("#confidenceBadge"),
  domainInput: document.querySelector("#domainInput"),
  entityTypeInput: document.querySelector("#entityTypeInput"),
  moduleInput: document.querySelector("#moduleInput"),
  fieldInput: document.querySelector("#fieldInput"),
  parentInput: document.querySelector("#parentInput"),
  targetTypeInput: document.querySelector("#targetTypeInput"),
  supportInput: document.querySelector("#supportInput"),
  valueInput: document.querySelector("#valueInput"),
  sourceIdsInput: document.querySelector("#sourceIdsInput"),
  exampleList: document.querySelector("#exampleList"),
  evidenceList: document.querySelector("#evidenceList"),
  notesInput: document.querySelector("#notesInput"),
  acceptBtn: document.querySelector("#acceptBtn"),
  reviewBtn: document.querySelector("#reviewBtn"),
  rejectBtn: document.querySelector("#rejectBtn"),
  resetBtn: document.querySelector("#resetBtn")
};

function normalizeChange(change, index) {
  return {
    id: change.id || `change-${index + 1}`,
    decision: change.decision || "pending",
    reviewer_notes: change.reviewer_notes || "",
    original: structuredClone(change),
    ...change
  };
}

function loadData(data, sourceName) {
  const changes = Array.isArray(data) ? data : data.changes || [];
  state.changes = changes.map(normalizeChange);
  state.selectedId = state.changes[0]?.id || null;
  state.filters = { search: "", action: "", status: "", confidence: 0 };
  els.searchInput.value = "";
  els.actionFilter.value = "";
  els.statusFilter.value = "";
  els.confidenceFilter.value = "0";
  els.confidenceValue.textContent = "0.00";
  els.datasetMeta.textContent = `${sourceName} - ${state.changes.length} 条变更`;
  populateActionFilter();
  render();
}

function populateActionFilter() {
  const actions = [...new Set(state.changes.map((change) => change.action).filter(Boolean))].sort();
  els.actionFilter.innerHTML = '<option value="">全部动作</option>';
  for (const action of actions) {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = action;
    els.actionFilter.append(option);
  }
}

function render() {
  renderSummary();
  renderList();
  renderDetail();
}

function renderSummary() {
  const total = state.changes.length;
  const accepted = state.changes.filter((change) => change.decision === "accepted").length;
  const rejected = state.changes.filter((change) => change.decision === "rejected").length;
  const pending = state.changes.filter((change) => change.decision === "pending" || change.decision === "needs_review").length;
  const avg = total
    ? state.changes.reduce((sum, change) => sum + Number(change.confidence || 0), 0) / total
    : 0;
  els.totalCount.textContent = total;
  els.acceptedCount.textContent = accepted;
  els.rejectedCount.textContent = rejected;
  els.pendingCount.textContent = pending;
  els.avgConfidence.textContent = avg.toFixed(2);
}

function getFilteredChanges() {
  const query = state.filters.search.trim().toLowerCase();
  return state.changes.filter((change) => {
    const searchable = [
      change.label,
      change.entity_type,
      change.domain,
      change.action,
      change.module,
      change.field,
      change.value,
      change.target_type,
      ...(change.source_entity_ids || []),
      ...(change.examples || [])
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    const matchesSearch = !query || searchable.includes(query);
    const matchesAction = !state.filters.action || change.action === state.filters.action;
    const matchesStatus = !state.filters.status || change.decision === state.filters.status;
    const matchesConfidence = Number(change.confidence || 0) >= state.filters.confidence;
    return matchesSearch && matchesAction && matchesStatus && matchesConfidence;
  });
}

function renderList() {
  const filtered = getFilteredChanges();
  els.changeList.innerHTML = "";
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<h2>没有匹配项</h2><p>调整筛选条件后继续审查。</p>";
    els.changeList.append(empty);
    return;
  }

  for (const change of filtered) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `change-item ${change.id === state.selectedId ? "active" : ""}`;
    item.dataset.id = change.id;
    item.innerHTML = `
      <div class="change-main">
        <span class="change-title">${escapeHtml(change.label || "-")}</span>
        <span class="status ${change.decision}">${statusLabel(change.decision)}</span>
      </div>
      <div class="change-meta">${escapeHtml(change.action || "-")} · ${escapeHtml(change.domain || "-")} · ${escapeHtml(change.entity_type || "-")} · ${formatConfidence(change.confidence)}</div>
      <div class="change-field">${escapeHtml(change.field || change.target_type || sourceSummary(change) || "-")}</div>
    `;
    item.addEventListener("click", () => {
      saveDetailEdits();
      state.selectedId = change.id;
      render();
    });
    els.changeList.append(item);
  }
}

function renderDetail() {
  const change = selectedChange();
  if (!change) {
    els.emptyState.classList.remove("hidden");
    els.detailView.classList.add("hidden");
    return;
  }

  els.emptyState.classList.add("hidden");
  els.detailView.classList.remove("hidden");
  els.detailAction.textContent = change.action || "-";
  els.detailLabel.textContent = change.label || "-";
  els.detailSubhead.textContent = `${change.domain || "-"} · ${sourceSummary(change) || "no sources"} · ${statusLabel(change.decision)}`;
  els.confidenceBadge.textContent = formatConfidence(change.confidence);
  els.domainInput.value = change.domain || "";
  els.entityTypeInput.value = change.entity_type || "";
  els.moduleInput.value = change.module || "";
  els.fieldInput.value = change.field || "";
  els.parentInput.value = change.parent || "";
  els.targetTypeInput.value = change.target_type || "";
  els.supportInput.value = Number(change.support || 0);
  els.valueInput.value = change.value || "";
  els.sourceIdsInput.value = (change.source_entity_ids || []).join("\n");
  els.notesInput.value = change.reviewer_notes || "";

  renderExamples(change.examples || []);
  renderEvidence(change.evidence || []);
}

function renderExamples(examples) {
  els.exampleList.innerHTML = "";
  if (!examples.length) {
    const row = document.createElement("div");
    row.className = "evidence-item";
    row.innerHTML = '<span class="evidence-source">无</span><span class="evidence-detail">该提案没有附带示例。</span><span class="evidence-weight">-</span>';
    els.exampleList.append(row);
    return;
  }

  for (const example of examples) {
    const row = document.createElement("div");
    row.className = "evidence-item";
    row.innerHTML = `
      <span class="evidence-source">example</span>
      <span class="evidence-detail">${escapeHtml(example)}</span>
      <span class="evidence-weight">-</span>
    `;
    els.exampleList.append(row);
  }
}

function renderEvidence(evidence) {
  els.evidenceList.innerHTML = "";
  if (!evidence.length) {
    const row = document.createElement("div");
    row.className = "evidence-item";
    row.innerHTML = '<span class="evidence-source">无</span><span class="evidence-detail">该变更没有附带证据。</span><span class="evidence-weight">0.00</span>';
    els.evidenceList.append(row);
    return;
  }

  for (const item of evidence) {
    const row = document.createElement("div");
    row.className = "evidence-item";
    row.innerHTML = `
      <span class="evidence-source">${escapeHtml(item.source || "-")}</span>
      <span class="evidence-detail">${escapeHtml(item.detail || "-")}</span>
      <span class="evidence-weight">${formatConfidence(item.weight)}</span>
    `;
    els.evidenceList.append(row);
  }
}

function selectedChange() {
  return state.changes.find((change) => change.id === state.selectedId);
}

function saveDetailEdits() {
  const change = selectedChange();
  if (!change || els.detailView.classList.contains("hidden")) {
    return;
  }
  change.domain = els.domainInput.value.trim() || null;
  change.entity_type = els.entityTypeInput.value.trim();
  change.module = els.moduleInput.value.trim() || null;
  change.field = els.fieldInput.value.trim() || null;
  change.parent = els.parentInput.value.trim() || null;
  change.target_type = els.targetTypeInput.value.trim() || null;
  change.support = Number(els.supportInput.value || 0);
  change.value = els.valueInput.value.trim() || null;
  change.source_entity_ids = els.sourceIdsInput.value
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
  change.reviewer_notes = els.notesInput.value.trim();
}

function setDecision(decision) {
  saveDetailEdits();
  const change = selectedChange();
  if (!change) {
    return;
  }
  change.decision = decision;
  change.reviewed_at = new Date().toISOString();
  render();
}

function resetSelected() {
  const change = selectedChange();
  if (!change) {
    return;
  }
  const restored = normalizeChange(change.original, Number(change.id.replace("change-", "")) - 1 || 0);
  const index = state.changes.findIndex((item) => item.id === change.id);
  state.changes[index] = { ...restored, id: change.id, original: change.original };
  render();
}

function exportReview() {
  saveDetailEdits();
  const payload = {
    reviewed_at: new Date().toISOString(),
    summary: {
      total: state.changes.length,
      accepted: state.changes.filter((change) => change.decision === "accepted").length,
      rejected: state.changes.filter((change) => change.decision === "rejected").length,
      needs_review: state.changes.filter((change) => change.decision === "needs_review").length,
      pending: state.changes.filter((change) => change.decision === "pending").length
    },
    changes: state.changes.map(({ original, ...change }) => change)
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "reviewed_changeset.json";
  link.click();
  URL.revokeObjectURL(url);
}

function statusLabel(status) {
  return {
    pending: "待处理",
    accepted: "已接受",
    rejected: "已拒绝",
    needs_review: "需复核"
  }[status] || status || "待处理";
}

function formatConfidence(value) {
  return Number(value || 0).toFixed(2);
}

function sourceSummary(change) {
  const ids = change.source_entity_ids || [];
  if (!ids.length) {
    return "";
  }
  if (ids.length === 1) {
    return ids[0];
  }
  return `${ids.length} sources`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.fileInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  const text = await file.text();
  loadData(JSON.parse(text), file.name);
});

els.loadSampleBtn.addEventListener("click", () => loadData(sampleData, "示例数据"));
els.exportBtn.addEventListener("click", exportReview);
els.searchInput.addEventListener("input", (event) => {
  saveDetailEdits();
  state.filters.search = event.target.value;
  render();
});
els.actionFilter.addEventListener("change", (event) => {
  saveDetailEdits();
  state.filters.action = event.target.value;
  render();
});
els.statusFilter.addEventListener("change", (event) => {
  saveDetailEdits();
  state.filters.status = event.target.value;
  render();
});
els.confidenceFilter.addEventListener("input", (event) => {
  saveDetailEdits();
  state.filters.confidence = Number(event.target.value);
  els.confidenceValue.textContent = state.filters.confidence.toFixed(2);
  render();
});
els.acceptBtn.addEventListener("click", () => setDecision("accepted"));
els.reviewBtn.addEventListener("click", () => setDecision("needs_review"));
els.rejectBtn.addEventListener("click", () => setDecision("rejected"));
els.resetBtn.addEventListener("click", resetSelected);

loadData(sampleData, "示例数据");
