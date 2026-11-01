/**
 * Read-only evidence adapter. Does not judge, fetch, or trust a file.
 * Parent backend may later set trust to backend_validated. This module never does.
 */
export const SCHEMA = "reproloop.evidence.v1";
export const COHORT_SCHEMA = "reproloop.evidence.v2";

const BANNED_KEY = new Set(["__proto__", "prototype", "constructor"]);

export function loadCaseDocument(text) {
  if (typeof text !== "string") {
    return fail(["Document must be a string."]);
  }
  let data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return fail([`JSON parse failed: ${error.message}`]);
  }
  if (!isPlain(data)) return fail(["Root must be a JSON object."]);
  const errors = [];
  if (![SCHEMA, COHORT_SCHEMA].includes(data.schema)) errors.push(`schema must be ${SCHEMA} or ${COHORT_SCHEMA}.`);
  if (data.evidence_level !== "SYNTHETIC_MOCK_TESTED" && data.evidence_level !== "HOST_OBSERVED") {
    errors.push("evidence_level must be SYNTHETIC_MOCK_TESTED or HOST_OBSERVED.");
  }
  if (data.mode !== "synthetic" && data.mode !== "real") {
    errors.push("mode must be synthetic or real.");
  }
  for (const key of ["meta_calls", "android_runs", "video_calls", "cua_calls"]) {
    if (!isCount(data[key])) errors.push(`${key} must be an integer from 0 to 1000000.`);
  }
  scanValues(data, "$", errors);
  const v2 = data.schema === COHORT_SCHEMA;
  const scope = v2 ? data.cohort : data.pilot;
  const scopeName = v2 ? "cohort" : "pilot";
  if (v2 && data.pilot != null) errors.push("v2 must not mix cohort and pilot denominators.");
  if (!v2 && data.cohort != null) errors.push("v1 must not carry a second cohort denominator.");
  if (!isPlain(scope)) errors.push(`${scopeName} object is required.`);
  else {
    if (v2) {
      if (!isShortText(scope.id)) errors.push("cohort.id is required.");
      if (!["DEV", "PILOT", "FINAL"].includes(scope.split)) errors.push("cohort.split must be DEV, PILOT or FINAL.");
      if (!isShortText(scope.condition)) errors.push("cohort.condition is required.");
    }
    const ids = scope.planned_case_ids;
    const validIds = Array.isArray(ids) && ids.length > 0 && ids.length <= 64
      && ids.every(isShortText) && new Set(ids).size === ids.length;
    if (!validIds || (!v2 && ids.length !== 5)) {
      errors.push(`${scopeName}.planned_case_ids must list ${v2 ? "1 to 64 unique" : "exactly 5 unique"} short ids.`);
    }
    const countKeys = ["attempted", "complete", "unknown", "excluded"];
    for (const key of countKeys) {
      if (!isCount(scope[key])) errors.push(`${scopeName}.${key} must be an integer count.`);
    }
    if (validIds && countKeys.every(key => isCount(scope[key]))) checkCohortCounts(scope, scopeName, errors);
    for (const key of ["valid_export_pairs", "fixed_failure_signals", "invalid_confirmations"]) {
      if (scope[key] !== null) errors.push(`${scopeName}.${key} must stay null until a trusted backend writes a result.`);
    }
  }
  const cases = Array.isArray(data.cases) ? data.cases : null;
  if (!cases) errors.push("cases must be an array, empty when nothing has run.");
  else cases.forEach((row, index) => checkRunRow(row, `cases[${index}]`, errors));
  if (data.illustration != null) checkIllustration(data.illustration, errors);
  const rowIds = cases ? cases.filter(isPlain).map(row => row.case_id) : [];
  if (new Set(rowIds).size !== rowIds.length) errors.push("Case row ids must be unique within the cohort.");
  if (data.illustration && rowIds.includes(data.illustration.case_id)) errors.push("Illustration id must not collide with a case row.");
  if (isPlain(scope) && Array.isArray(scope.planned_case_ids) && rowIds.some(id => !scope.planned_case_ids.includes(id))) {
    errors.push("Case row ids must belong to this cohort plan.");
  }
  if (errors.length) return fail(errors);
  return {
    ok: true,
    errors: [],
    trust: "UNVERIFIED",
    document: data,
  };
}

export function emptyRealState() {
  return {
    ok: true,
    errors: [],
    trust: "UNVERIFIED",
    document: {
      schema: SCHEMA,
      evidence_level: "HOST_OBSERVED",
      mode: "real",
      meta_calls: 0,
      android_runs: 0,
      video_calls: 0,
      cua_calls: 0,
      pilot: {
        planned_case_ids: ["P01", "P02", "P03", "P04", "P05"],
        attempted: 0,
        complete: 0,
        unknown: 0,
        excluded: 0,
        not_run_ids: ["P01", "P02", "P03", "P04", "P05"],
        valid_export_pairs: null,
        fixed_failure_signals: null,
        invalid_confirmations: null,
        note: "Real pilot has not run. The five ids are the plan denominator, not results.",
      },
      cases: [],
      illustration: null,
    },
  };
}

function checkCohortCounts(pilot, scopeName, errors) {
  const planned = pilot.planned_case_ids.length;
  const { attempted, complete, excluded, unknown } = pilot;
  if (attempted > planned) errors.push(`${scopeName}.attempted cannot exceed planned ids.`);
  if (complete + excluded + unknown !== attempted) {
    errors.push(`${scopeName}.complete, excluded, and unknown must partition attempted.`);
  }
  if (unknown > attempted || complete > attempted || excluded > attempted) {
    errors.push(`${scopeName} outcome counts must be subsets of attempted.`);
  }
  const notRun = planned - attempted;
  if (pilot.not_run != null && pilot.not_run !== notRun) {
    errors.push(`${scopeName}.not_run must equal planned minus attempted.`);
  }
  if (pilot.not_run_ids == null) return;
  if (!Array.isArray(pilot.not_run_ids) || pilot.not_run_ids.length !== notRun) {
    errors.push(`${scopeName}.not_run_ids must list each planned id that was not attempted.`);
    return;
  }
  if (new Set(pilot.not_run_ids).size !== pilot.not_run_ids.length) {
    errors.push(`${scopeName}.not_run_ids must not repeat an id.`);
  }
  if (pilot.not_run_ids.some((id) => !pilot.planned_case_ids.includes(id))) {
    errors.push(`${scopeName}.not_run_ids must be planned ids.`);
  }
}

function checkIllustration(row, errors) {
  if (!isPlain(row)) {
    errors.push("illustration must be an object.");
    return;
  }
  if (row.not_a_pilot_row !== true) errors.push("illustration.not_a_pilot_row must be true.");
  checkRunRow(row, "illustration", errors);
}

function checkRunRow(row, path, errors) {
  if (!isPlain(row)) {
    errors.push(`${path} must be an object.`);
    return;
  }
  if (!isShortText(row.case_id)) errors.push(`${path}.case_id is required.`);
  if (row.file_claim != null && !isPlain(row.file_claim)) {
    errors.push(`${path}.file_claim must be an object or null.`);
  }
  for (const [key, limit] of [["models", 8], ["intents", 24], ["task_steps", 24]]) {
    if (row[key] == null) continue;
    if (!Array.isArray(row[key]) || row[key].length > limit || !row[key].every(isPlain)) {
      errors.push(`${path}.${key} must be a bounded array of objects.`);
    }
  }
  if (isPlain(row.capture) && row.capture.nodes != null
      && (!Array.isArray(row.capture.nodes) || row.capture.nodes.length > 64 || !row.capture.nodes.every(isPlain))) {
    errors.push(`${path}.capture.nodes must be a bounded array of objects.`);
  }
  if (Array.isArray(row.unknown) && row.unknown.length > 32) {
    errors.push(`${path}.unknown exceeds 32.`);
  }
}

function scanValues(value, path, errors, depth = 0) {
  if (depth > 24) {
    errors.push("Document nesting exceeds 24 levels.");
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 64) errors.push(`${path} exceeds 64 items.`);
    value.forEach((item, index) => scanValues(item, `${path}[${index}]`, errors, depth + 1));
    return;
  }
  if (!isPlain(value)) {
    if (typeof value === "string") checkString(value, path, errors);
    return;
  }
  for (const key of Object.keys(value)) {
    if (BANNED_KEY.has(key)) errors.push(`${path} contains a forbidden key.`);
    else scanValues(value[key], `${path}.${key}`, errors, depth + 1);
  }
}

function checkString(value, path, errors) {
  if (value.length > 4000) errors.push(`${path} exceeds 4000 characters.`);
  const trimmed = value.trim();
  const lower = trimmed.toLowerCase();
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) {
    errors.push(`${path} contains a control character.`);
  }
  if (lower.startsWith("javascript:") || lower.startsWith("data:") || lower.startsWith("file:") || lower.startsWith("blob:")) {
    errors.push(`${path} uses a forbidden URL scheme.`);
  }
  if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith("//")) {
    errors.push(`${path} must not carry an external URL.`);
  }
  // A parent path segment is an escape; an ellipsis in ordinary task text is not.
  if (/(^|[\/\s])\.\.(?=\/|$)/.test(trimmed) || trimmed.includes("\\") || /%2e%2e/i.test(trimmed)) {
    errors.push(`${path} looks like a path escape.`);
  }
}

function fail(errors) {
  return { ok: false, errors, trust: "UNVERIFIED", document: null };
}

function isPlain(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isCount(value) {
  return Number.isInteger(value) && value >= 0 && value <= 1000000;
}

function isShortText(value) {
  return typeof value === "string" && value.trim() === value && value.length > 0 && value.length <= 80;
}

export function cohortInfo(document) {
  if (document?.schema === COHORT_SCHEMA) return document.cohort;
  return { ...document?.pilot, id: "legacy-pilot", split: "PILOT", condition: "Legacy v1 import" };
}

export function rowChoices(document) {
  if (!document) return [];
  const choices = [];
  for (const row of document.cases || []) {
    choices.push({ id: row.case_id, pilot_row: cohortInfo(document).split === "PILOT", illustration: false, row });
  }
  if (document.illustration && document.illustration.case_id) {
    choices.push({ id: document.illustration.case_id, pilot_row: false, illustration: true, row: document.illustration });
  }
  return choices;
}

export function inspectRow(document, caseId) {
  const choice = rowChoices(document).find((item) => item.id === caseId) || null;
  if (!choice) return { found: false, trust: "UNVERIFIED" };
  const row = choice.row;
  return {
    found: true,
    trust: "UNVERIFIED",
    pilot_row: choice.pilot_row,
    illustration: choice.illustration,
    cohort_id: cohortInfo(document).id,
    split: cohortInfo(document).split,
    condition: cohortInfo(document).condition,
    case_id: row.case_id,
    variant: row.variant ?? null,
    bug_family: row.bug_family ?? null,
    media_sha256: row.media ? row.media.sha256 ?? null : null,
    intents: Array.isArray(row.intents) ? row.intents : [],
    capture: normalizeCapture(row.capture),
    reset: normalizeReset(row.reset),
    source_ids: shortList(row.source_ids),
    unknown: shortList(row.unknown),
    models: Array.isArray(row.models) ? row.models.slice(0, 8) : [],
    faulty: row.faulty || null,
    fixed: row.fixed || null,
    file_claim: row.file_claim || null,
    cost_usd: row.cost_usd ?? null,
    latency_ms: row.latency_ms ?? null,
    task_steps: Array.isArray(row.task_steps) ? row.task_steps.slice(0, 24) : [],
    pair_report: isPlain(row.pair_report) ? row.pair_report : null,
    png_claims: isPlain(row.png_claims) ? row.png_claims : null,
  };
}

export function classifyAttachment(file) {
  if (!file || typeof file.size !== "number" || typeof file.type !== "string") {
    return { ok: false, reason: "No local file was selected." };
  }
  const kind = file.type.startsWith("image/") ? "image" : file.type.startsWith("video/") ? "video" : null;
  if (!kind) return { ok: false, reason: "Only a local image or video can be previewed." };
  const limit = kind === "image" ? 8000000 : 40000000;
  if (file.size <= 0) return { ok: false, reason: "The local file is empty." };
  if (file.size > limit) return { ok: false, reason: "The local file is over the preview limit." };
  const name = String(file.name || "local file").replace(/[\u0000-\u001f]/g, "").slice(0, 120);
  return { ok: true, kind, name, size: file.size, type: file.type };
}

function normalizeCapture(capture) {
  if (!isPlain(capture)) return null;
  return {
    width: integerOrNull(capture.width, 1, 16384),
    height: integerOrNull(capture.height, 1, 16384),
    node_count: integerOrNull(capture.node_count, 0, 128),
    duration_s: typeof capture.duration_s === "number" ? capture.duration_s : null,
    serial: isShortText(capture.serial) ? capture.serial : null,
    nodes: Array.isArray(capture.nodes) ? capture.nodes.slice(0, 128) : [],
  };
}

function normalizeReset(reset) {
  if (!isPlain(reset)) return null;
  return {
    verified: typeof reset.verified === "boolean" ? reset.verified : null,
    reason: typeof reset.reason === "string" ? reset.reason : null,
  };
}

function shortList(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === "string").slice(0, 32);
}

function integerOrNull(value, low, high) {
  return Number.isInteger(value) && value >= low && value <= high ? value : null;
}

export function show(value) {
  if (value == null || value === "") return "not recorded";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return "unsupported value";
}
