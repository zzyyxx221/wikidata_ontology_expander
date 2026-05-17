const sampleData = {
  changes: [
    {
      action: "enrich_existing",
      entity_type: "Product",
      label: "Lithium-ion battery",
      wikidata_id: "Q2294",
      confidence: 0.86,
      module: "product",
      parent: "Battery",
      field: null,
      value: null,
      evidence: [
        { source: "label", detail: "exact label match: Lithium-ion battery", weight: 0.42 },
        { source: "gate", detail: "gate properties: P31, P279", weight: 0.16 },
        { source: "indicator", detail: "module terms: battery, product", weight: 0.12 }
      ],
      review_required: false
    },
    {
      action: "add_relation",
      entity_type: "Product",
      label: "Lithium-ion battery",
      wikidata_id: "Q2294",
      confidence: 0.74,
      module: "product",
      parent: "Battery",
      field: "manufacturer",
      value: "Panasonic (Q53247)",
      evidence: [
        { source: "relation", detail: "manufacturer from Wikidata P176", weight: 0.2 }
      ],
      review_required: true
    },
    {
      action: "enrich_property",
      entity_type: "Enterprise",
      label: "Tesla, Inc.",
      wikidata_id: "Q478214",
      confidence: 0.79,
      module: "enterprise",
      parent: null,
      field: "officialWebsite",
      value: "https://www.tesla.com/",
      evidence: [
        { source: "property", detail: "official website (P856)", weight: 0.18 }
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
  entityTypeInput: document.querySelector("#entityTypeInput"),
  moduleInput: document.querySelector("#moduleInput"),
  fieldInput: document.querySelector("#fieldInput"),
  parentInput: document.querySelector("#parentInput"),
  valueInput: document.querySelector("#valueInput"),
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
      change.wikidata_id,
      change.action,
      change.module,
      change.field,
      change.value
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
      <div class="change-meta">${escapeHtml(change.action || "-")} · ${escapeHtml(change.entity_type || "-")} · ${formatConfidence(change.confidence)}</div>
      <div class="change-field">${escapeHtml(change.field || change.wikidata_id || "-")}</div>
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
  els.detailSubhead.textContent = `${change.wikidata_id || "-"} · ${statusLabel(change.decision)}`;
  els.confidenceBadge.textContent = formatConfidence(change.confidence);
  els.entityTypeInput.value = change.entity_type || "";
  els.moduleInput.value = change.module || "";
  els.fieldInput.value = change.field || "";
  els.parentInput.value = change.parent || "";
  els.valueInput.value = change.value || "";
  els.notesInput.value = change.reviewer_notes || "";

  els.evidenceList.innerHTML = "";
  const evidence = change.evidence || [];
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
  change.entity_type = els.entityTypeInput.value.trim();
  change.module = els.moduleInput.value.trim() || null;
  change.field = els.fieldInput.value.trim() || null;
  change.parent = els.parentInput.value.trim() || null;
  change.value = els.valueInput.value.trim() || null;
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
