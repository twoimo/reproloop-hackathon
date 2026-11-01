import { cohortInfo, classifyAttachment, emptyRealState, inspectRow, loadCaseDocument, rowChoices, show } from "./adapter.js";
import { recordedDocument, loadRecordedMedia } from "./recorded-demo.js";
import sampleText from "./fixtures/synthetic-illustration.json" with { type: "json" };

const state = {
  loaded: emptyRealState(),
  source: "default",
  view: "intake",
  beat: 0,
  caseId: null,
  documentLoadId: 0,
  bundledLoadId: 0,
  bundledSlotIds: { one: 0, two: 0, video: 0 },
  savedStep: 3,
  previewUrls: { one: null, two: null, video: null },
  previewOrigins: { one: null, two: null, video: null },
};

const beats = [
  ["0 to 18 seconds", "Show a self-owned synthetic recording of Cancel after a rename preset. Say the stored title should have stayed. The sample stays synthetic."],
  ["18 to 38 seconds", "Point at the file hash and the plan denominator. The model text is untrusted. The oracle line stays separate."],
  ["38 to 75 seconds", "Describe a fresh screen grounding on another layout. This page has no emulator and does not play a device."],
  ["75 to 100 seconds", "Read before and after only if a trusted backend later fills them. A model done line is not success."],
  ["100 to 130 seconds", "A no-model export replay needs a new run id and zero model calls. Missing export stays missing."],
  ["130 to 158 seconds", "The fixed build is a developer-supplied, AI-assisted control. Do not call a file claim a confirmation."],
  ["158 to 180 seconds", "Read the selected cohort and its file-claimed counts. Keep older cohorts separate. This viewer does not compute or confirm a score."],
];

const views = ["intake", "cases", "evidence", "demo"];

function text(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function addRow(parent, name, value) {
  const row = document.createElement("div");
  row.className = "pair";
  const key = document.createElement("p");
  key.className = "pair-key";
  key.textContent = name;
  const val = document.createElement("p");
  val.className = "pair-value";
  val.textContent = show(value);
  row.append(key, val);
  parent.append(row);
}

function clearPreviewSlot(slot) {
  const stage = document.getElementById(`preview-stage-${slot}`);
  if (state.previewUrls[slot]) URL.revokeObjectURL(state.previewUrls[slot]);
  state.previewUrls[slot] = null;
  state.previewOrigins[slot] = null;
  for (const child of Array.from(stage.children)) {
    if (child.tagName === "VIDEO") child.pause();
    child.removeAttribute("src");
  }
  clear(stage);
  text(`preview-line-${slot}`, `No local ${slot === "video" ? "video" : "image"} is attached.`);
}

function revokePreview() {
  state.bundledLoadId += 1;
  for (const slot of ["one", "two", "video"]) clearPreviewSlot(slot);
  for (const id of ["image-file", "image-file-two", "video-file"]) {
    document.getElementById(id).value = "";
  }
}

function selectCase(caseId) {
  const next = caseId || null;
  if (next !== state.caseId) revokePreview();
  state.caseId = next;
}

function render() {
  const doc = state.loaded.ok ? state.loaded.document : null;
  const synthetic = Boolean(doc && doc.mode === "synthetic");
  const imported = ["local-file", "recorded-demo"].includes(state.source) && state.loaded.ok;
  text("recorded-demo", state.source === "recorded-demo" ? "Restart recorded example" : "Explore recorded run");
  const shell = document.getElementById("app-shell");
  if (shell) shell.setAttribute("data-loaded", String(state.source !== "default" && state.loaded.ok));
  text("media-mode", state.source === "recorded-demo" ? "Recorded evidence. No new model or device calls." : "Local files only. No model or device controls.");
  text("mode-line", synthetic
    ? "Synthetic sample. Not a pilot."
    : imported
      ? state.source === "recorded-demo" ? "Recorded example. No new execution." : "Imported file. Not backend-verified."
      : "Real state: not run.");
  text("trust-line", "Trust: unverified. This page does not issue a verdict.");
  text("page-title", synthetic ? "Synthetic sample open" : state.source === "recorded-demo" && imported ? "Recorded FINAL controls" : imported ? "Local file loaded" : "No real cases loaded");
  text("page-lead", synthetic
    ? "Synthetic illustration. Counts are file claims, not real executions."
    : imported
      ? "The import is read-only. Score fields stay empty for every cohort."
      : "Start with a saved run. This viewer does not execute a device or call a model.");
  const pilot = doc ? cohortInfo(doc) : null;
  text("cohort-line", pilot ? `Cohort: ${pilot.id} / ${pilot.split} / ${pilot.condition}. Imported counts are file claims, not a backend verdict.` : "No active cohort. No imported result is shown.");
  text("planned", pilot ? pilot.planned_case_ids.join(", ") : "No active cohort");
  text("attempted", show(pilot?.attempted));
  text("complete", show(pilot?.complete));
  text("unknown", show(pilot?.unknown));
  text("not-run", show(pilot ? (pilot.not_run_ids ? pilot.not_run_ids.length : pilot.planned_case_ids.length - pilot.attempted) : null));
  text("excluded", show(pilot?.excluded));
  text("pairs", show(pilot?.valid_export_pairs));
  text("calls", doc ? `${doc.meta_calls} meta, ${doc.android_runs} android, ${doc.video_calls} video, ${doc.cua_calls} cua` : "0");
  renderCases(doc);
  renderChoices(doc);
  renderEvidence(doc);
  renderDemo();
  renderRecordedActions(doc);
  for (const name of views) {
    const panel = document.getElementById(`view-${name}`);
    const button = document.querySelector(`[data-view="${name}"]`);
    const on = state.view === name;
    panel.hidden = !on;
    button.setAttribute("aria-current", on ? "true" : "false");
  }
  const errors = document.getElementById("errors");
  clear(errors);
  if (!state.loaded.ok) {
    for (const message of state.loaded.errors) {
      const item = document.createElement("li");
      item.textContent = message;
      errors.append(item);
    }
  }
}

function renderCases(doc) {
  const list = document.getElementById("case-list");
  clear(list);
  const rows = doc && Array.isArray(doc.cases) ? doc.cases : [];
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "Case list is empty. Planned ids are not results.";
    list.append(empty);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${show(row.case_id)} / ${show(row.variant)} / file claim ${show(row.file_claim && row.file_claim.verdict)}`;
    button.addEventListener("click", () => openCase(row.case_id));
    item.append(button);
    list.append(item);
  }
}

function renderChoices(doc) {
  const select = document.getElementById("case-select");
  const previous = state.caseId;
  clear(select);
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = "No case row";
  select.append(blank);
  const choices = rowChoices(doc);
  for (const choice of choices) {
    const option = document.createElement("option");
    option.value = choice.id;
    option.textContent = choice.illustration ? `${choice.id} illustration` : choice.id;
    select.append(option);
  }
  const ids = choices.map((choice) => choice.id);
  if (previous && !ids.includes(previous)) state.caseId = null;
  select.value = state.caseId || "";
}

function renderEvidence(doc) {
  const host = document.getElementById("evidence-body");
  const nodes = document.getElementById("node-list");
  clear(host);
  clear(nodes);
  const viewed = inspectRow(doc, state.caseId);
  const recorded = state.source === "recorded-demo" && state.loaded.ok;
  text("comparison-family", recorded ? "F01 / Cancel persistence" : "Read-only file / unverified");
  text("comparison-heading", recorded ? "One Cancel. Two controls." : "Inspect the selected case.");
  text("comparison-expectation", recorded ? "Cancel must not save the edit" : "Task and oracle text are file claims.");
  if (!viewed.found) {
    const empty = document.createElement("p");
    empty.textContent = "No evidence row is selected.";
    host.append(empty);
    return;
  }
  addRow(host, "Cohort", viewed.cohort_id);
  addRow(host, "Split", viewed.split);
  addRow(host, "Condition", viewed.condition);
  addRow(host, "Count scope", cohortInfo(doc).note);
  addRow(host, "Row class", viewed.illustration ? "Illustration, not a cohort result" : `${viewed.split} case, unverified file claim`);
  addRow(host, "Case", viewed.case_id);
  addRow(host, "Variant", viewed.variant);
  addRow(host, "Family", viewed.bug_family);
  addRow(host, "Media hash", viewed.media_sha256);
  addRow(host, "Capture size", viewed.capture ? `${show(viewed.capture.width)} by ${show(viewed.capture.height)}` : null);
  addRow(host, "Node count", viewed.capture && viewed.capture.node_count);
  addRow(host, "Capture serial", viewed.capture && viewed.capture.serial);
  addRow(host, "Reset verified", viewed.reset && viewed.reset.verified);
  addRow(host, "Reset reason", viewed.reset && viewed.reset.reason);
  addRow(host, "Source ids", viewed.source_ids.length ? viewed.source_ids.join(", ") : null);
  addRow(host, "Unknown", viewed.unknown.length ? viewed.unknown.join(", ") : null);
  addRow(host, "Models", viewed.models.length ? viewed.models.map((item) => `${show(item.provider)} ${show(item.name)} ${show(item.status)}`).join("; ") : null);
  addRow(host, "Faulty failure", viewed.faulty && viewed.faulty.failure_observed);
  addRow(host, "Fixed failure", viewed.fixed && viewed.fixed.failure_observed);
  addRow(host, "File claim", viewed.file_claim && viewed.file_claim.verdict);
  addRow(host, "Cost", viewed.cost_usd);
  addRow(host, "Latency", viewed.latency_ms);
  const intents = document.createElement("ol");
  const steps = viewed.task_steps.length ? viewed.task_steps : viewed.intents;
  for (const [index, intent] of steps.entries()) {
    const item = document.createElement("li");
    item.textContent = `Step ${index + 1}: ${show(intent.visible_text || intent.text)}`;
    intents.append(item);
  }
  host.append(intents);
  const captureNodes = viewed.capture && Array.isArray(viewed.capture.nodes) ? viewed.capture.nodes : [];
  if (!captureNodes.length) {
    const empty = document.createElement("li");
    empty.textContent = "No capture nodes are in the file.";
    nodes.append(empty);
    return;
  }
  for (const node of captureNodes) {
    const item = document.createElement("li");
    const bounds = Array.isArray(node.bounds) ? node.bounds.join(" ") : "bounds not recorded";
    item.textContent = `${show(node.resource_id)} ${show(node.text)} ${bounds}`;
    nodes.append(item);
  }
}

function renderDemo() {
  const [when, line] = beats[state.beat];
  text("beat-when", when);
  text("beat-line", line);
  text("beat-index", `${state.beat + 1} of ${beats.length}`);
}

function renderRecordedActions(doc) {
  const list = document.getElementById("action-list");
  if (!list) return;
  clear(list);
  const active = state.source === "recorded-demo" && state.loaded.ok;
  const sequence = active && state.caseId === "FINAL-C";
  const row = inspectRow(doc, state.caseId);
  const steps = row.found ? row.task_steps : [];
  for (const [index, step] of steps.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = show(step.visible_text);
    button.disabled = !sequence;
    button.setAttribute("aria-pressed", String(sequence && index === state.savedStep));
    button.addEventListener("click", () => changeSavedStep(index));
    const item = document.createElement("li");
    item.setAttribute("aria-current", sequence && index === state.savedStep ? "step" : "false");
    item.append(button);
    list.append(item);
  }
  for (const [id, disabled] of [["step-prev", !sequence || state.savedStep === 0], ["step-next", !sequence || state.savedStep === 3]]) {
    const button = document.getElementById(id);
    if (button) button.disabled = disabled;
  }
  text("walkthrough-step-label", sequence ? `Saved step ${state.savedStep + 1} of 4. Transitions omitted.` : active ? state.caseId ? "Recorded end states. No intermediate sequence for this layout." : "No case row is selected." : "Choose the recorded run to inspect saved actions.");
  text("compare-note", sequence && state.savedStep < 3
    ? "Intermediate saved states only. Final oracle claims below refer to completed controls, not this frame."
    : active && !state.caseId ? "Choose a case to inspect its recorded controls."
    : active ? "Saved control captures. The fixed build is developer supplied. This viewer does not verify a result."
    : "Attach the two local control images. Byte matches are not source attestation.");
}

async function openCase(caseId) {
  // A terminal-step reset is a new media identity even for the same case.
  if (state.source === "recorded-demo" && state.savedStep !== 3) revokePreview();
  selectCase(caseId);
  state.savedStep = 3;
  setView("evidence");
  if (state.source === "recorded-demo" && state.loaded.ok) await loadRecordedCase();
}

function cancelBundledReads(slot) {
  if (!["one", "two", "video"].includes(slot)) return;
  state.bundledSlotIds[slot] += 1;
  if (!state.previewUrls[slot]) text(`preview-line-${slot}`, `No local ${slot === "video" ? "video" : "image"} is attached.`);
}

async function loadRecordedCase() {
  if (state.source !== "recorded-demo" || !state.loaded.ok || !state.caseId) return;
  const identity = { id: ++state.bundledLoadId, caseId: state.caseId, step: state.savedStep };
  const current = () => state.source === "recorded-demo" && state.loaded.ok && state.bundledLoadId === identity.id && state.caseId === identity.caseId && state.savedStep === identity.step;
  await Promise.allSettled(["one", "two", "video"].map(async (slot) => {
    // Same-case reloads may retry missing bundled media, but never replace a manual attachment.
    if (state.previewOrigins[slot] === "manual") return;
    const slotId = state.bundledSlotIds[slot];
    const currentSlot = () => current() && state.bundledSlotIds[slot] === slotId && state.previewOrigins[slot] !== "manual";
    text(`preview-line-${slot}`, "Loading saved local media. Not live execution.");
    try {
      const result = await loadRecordedMedia(identity.caseId, slot, identity.step);
      if (currentSlot()) {
        await attachSlot(slot, result.file, slot === "video" ? "video" : "image", result.expectedHash, currentSlot);
      }
    } catch {
      if (currentSlot()) {
        text(`preview-line-${slot}`, "Saved media unavailable in this copy. Choose local files or a media-complete viewer bundle.");
      }
    }
  }));
}

async function changeSavedStep(index) {
  if (state.source !== "recorded-demo" || state.caseId !== "FINAL-C" || !Number.isInteger(index) || index < 0 || index > 3) return;
  revokePreview();
  state.savedStep = index;
  render();
  await loadRecordedCase();
}

function setView(name) {
  if (!views.includes(name)) return;
  state.view = name;
  render();
  const heading = document.querySelector(`#view-${name} h2`);
  if (heading) heading.focus();
}

function applyText(textValue, source) {
  state.documentLoadId += 1;
  revokePreview();
  state.caseId = null;
  const loaded = loadCaseDocument(textValue);
  if (!loaded.ok) {
    state.loaded = loaded;
    state.view = "intake";
    render();
    return;
  }
  state.loaded = loaded;
  state.source = source;
  state.caseId = rowChoices(loaded.document)[0]?.id || null;
  render();
}

async function attachSlot(slot, file, expectedKind, bundledExpectedHash = null, readCurrent = () => true) {
  if (!["one", "two", "video"].includes(slot)) return;
  clearPreviewSlot(slot);
  const decision = classifyAttachment(file);
  if (!decision.ok || decision.kind !== expectedKind) {
    text(`preview-line-${slot}`, decision.reason || "This slot requires a different media type.");
    return;
  }
  const url = URL.createObjectURL(file);
  state.previewUrls[slot] = url;
  state.previewOrigins[slot] = bundledExpectedHash ? "recorded" : "manual";
  const current = () => state.previewUrls[slot] === url && readCurrent();
  const stage = document.getElementById(`preview-stage-${slot}`);
  const media = document.createElement(expectedKind === "image" ? "img" : "video");
  if (expectedKind === "image") media.alt = decision.name;
  else {
    media.muted = true;
    media.volume = 0;
    media.controls = true;
    media.preload = "metadata";
  }
  media.src = url;
  stage.append(media);
  text(`preview-line-${slot}`, `Local ${decision.kind}: ${decision.name}. Computing byte hash; not attestation.`);
  try {
    const bytes = await file.arrayBuffer();
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), x => x.toString(16).padStart(2, "0")).join("");
    if (!current()) return;
    const row = rowChoices(state.loaded.document).find(choice => choice.id === state.caseId)?.row;
    const claim = slot === "one" ? row?.png_claims?.faulty : slot === "two" ? row?.png_claims?.fixed : row?.media?.sha256;
    const expected = bundledExpectedHash || (typeof claim === "string" ? claim : claim?.sha256);
    const intermediateManualImage = !bundledExpectedHash && slot !== "video" && state.source === "recorded-demo" && state.savedStep !== 3;
    const claimName = bundledExpectedHash ? "saved-frame claim" : intermediateManualImage ? "imported terminal-control claim (not the selected saved step)" : "imported claim";
    const comparison = expected ? (hash === expected ? `Bytes match the ${claimName}.` : `Bytes DO NOT match the ${claimName}.`) : "No imported hash is available for comparison.";
    text(`preview-line-${slot}`, `${decision.name} SHA-256 ${hash}. ${comparison} Not source attestation.`);
  } catch {
    if (current()) text(`preview-line-${slot}`, `${decision.name}. Byte hash unavailable; unverified.`);
  }
}

function boot() {
  const recordedButton = document.getElementById("recorded-demo");
  if (recordedButton) recordedButton.disabled = false;
  document.getElementById("recorded-demo")?.addEventListener("click", async () => {
    applyText(JSON.stringify(recordedDocument), "recorded-demo");
    selectCase("FINAL-C");
    state.savedStep = 3;
    setView("evidence");
    await loadRecordedCase();
  });
  document.getElementById("step-prev")?.addEventListener("click", () => changeSavedStep(state.savedStep - 1));
  document.getElementById("step-next")?.addEventListener("click", () => changeSavedStep(state.savedStep + 1));
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.getAttribute("data-view")));
  });
  document.getElementById("file").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    event.target.value = "";
    const loadId = ++state.documentLoadId;
    revokePreview();
    state.caseId = null;
    const errorState = (message) => {
      state.caseId = null;
      state.loaded = { ok: false, errors: [message], trust: "UNVERIFIED", document: null };
      state.view = "intake";
      render();
    };
    if (file.size > 200000) {
      errorState("File is over 200000 bytes.");
      return;
    }
    errorState("Reading local JSON; no document is active.");
    let content;
    try {
      content = await file.text();
    } catch {
      if (loadId === state.documentLoadId) errorState("Local JSON could not be read. No document is active.");
      return;
    }
    if (loadId !== state.documentLoadId) return;
    try {
      applyText(content, "local-file");
      if (state.loaded.ok) setView("evidence");
    } catch {
      revokePreview();
      errorState("Local JSON could not be displayed. No document is active.");
    }
  });
  document.getElementById("image-file").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (file) { cancelBundledReads("one"); return attachSlot("one", file, "image"); }
  });
  document.getElementById("image-file-two").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (file) { cancelBundledReads("two"); return attachSlot("two", file, "image"); }
  });
  document.getElementById("video-file").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (file) { cancelBundledReads("video"); return attachSlot("video", file, "video"); }
  });
  document.getElementById("clear-preview").addEventListener("click", revokePreview);
  document.getElementById("case-select").addEventListener("change", (event) => openCase(event.target.value));
  document.getElementById("demo").addEventListener("click", () => {
    applyText(JSON.stringify(sampleText), "synthetic");
    setView("demo");
  });
  document.getElementById("clear").addEventListener("click", () => {
    document.getElementById("file").value = "";
    state.documentLoadId += 1;
    revokePreview();
    state.loaded = emptyRealState();
    state.source = "default";
    state.caseId = null;
    state.beat = 0;
    setView("intake");
  });
  document.getElementById("beat-next").addEventListener("click", () => {
    state.beat = (state.beat + 1) % beats.length;
    render();
  });
  document.getElementById("beat-prev").addEventListener("click", () => {
    state.beat = (state.beat + beats.length - 1) % beats.length;
    render();
  });
  render();
}

boot();
