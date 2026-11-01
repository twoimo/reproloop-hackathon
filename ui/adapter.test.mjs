import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { classifyAttachment, emptyRealState, inspectRow, loadCaseDocument, rowChoices } from "./adapter.js";

const sample = readFileSync(new URL("./fixtures/synthetic-illustration.json", import.meta.url), "utf8");

test("default real state is not a pilot result", () => {
  const state = emptyRealState();
  assert.equal(state.trust, "UNVERIFIED");
  assert.equal(state.document.mode, "real");
  assert.equal(state.document.cases.length, 0);
  assert.equal(state.document.pilot.attempted, 0);
  assert.equal(state.document.pilot.unknown, 0);
  assert.equal(state.document.pilot.not_run_ids.length, 5);
  assert.equal(state.document.pilot.valid_export_pairs, null);
  assert.equal(state.document.android_runs, 0);
});

test("synthetic fixture stays unverified and uncounted", () => {
  const loaded = loadCaseDocument(sample);
  assert.equal(loaded.ok, true, loaded.errors.join(" "));
  assert.equal(loaded.trust, "UNVERIFIED");
  assert.equal(loaded.document.mode, "synthetic");
  assert.equal(loaded.document.meta_calls, 0);
  assert.equal(loaded.document.android_runs, 0);
  assert.equal(loaded.document.pilot.complete, 0);
  assert.equal(loaded.document.illustration.not_a_pilot_row, true);
  assert.equal(loaded.document.illustration.file_claim.verdict, null);
  assert.equal(JSON.stringify(loaded.document).includes("3/5"), false);
});

test("rejects external urls, schemes and path escapes", () => {
  const base = JSON.parse(sample);
  for (const bad of ["https://example.test/a", "javascript:alert(1)", "../secret", "\\\\share", "file:///etc/passwd"]) {
    const copy = structuredClone(base);
    copy.illustration.media.label = bad;
    const loaded = loadCaseDocument(JSON.stringify(copy));
    assert.equal(loaded.ok, false, bad);
    assert.equal(loaded.trust, "UNVERIFIED");
  }
});

test("unknown outcomes partition attempted and not-run stays separate", () => {
  const base = JSON.parse(sample);
  base.pilot.unknown = 5;
  assert.equal(loadCaseDocument(JSON.stringify(base)).ok, false);
  const started = JSON.parse(sample);
  started.pilot.attempted = 5;
  started.pilot.complete = 3;
  started.pilot.excluded = 1;
  started.pilot.unknown = 1;
  delete started.pilot.not_run_ids;
  assert.equal(loadCaseDocument(JSON.stringify(started)).ok, true);
  const doubled = JSON.parse(sample);
  doubled.pilot.attempted = 5;
  doubled.pilot.complete = 4;
  doubled.pilot.excluded = 2;
  doubled.pilot.unknown = 0;
  delete doubled.pilot.not_run_ids;
  assert.equal(loadCaseDocument(JSON.stringify(doubled)).ok, false);
});

test("rejects a scored pilot field and a non-object root", () => {
  const scored = JSON.parse(sample);
  scored.pilot.valid_export_pairs = "3/5";
  assert.equal(loadCaseDocument(JSON.stringify(scored)).ok, false);
  assert.equal(loadCaseDocument("[]").ok, false);
  assert.equal(loadCaseDocument("{").ok, false);
});

test("page script does not write html or fetch", () => {
  const source = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  for (const banned of ["innerHTML", "insertAdjacentHTML", "document.write", "eval(", "fetch("]) {
    assert.equal(source.includes(banned), false, banned);
  }
});

test("host observed capture stays unverified and unscored", () => {
  const doc = emptyRealState().document;
  doc.evidence_level = "HOST_OBSERVED";
  doc.cases = [{
    case_id: "P01",
    variant: "A",
    capture: { width: 720, height: 1280, node_count: 1, nodes: [{ resource_id: "lab.app:id/cancel", text: "Cancel", bounds: [1, 2, 3, 4] }] },
    reset: { verified: null, reason: "not in this file" },
    source_ids: ["local-file"],
    unknown: ["oracle log bytes"],
    models: [{ provider: "meta", name: "muse-spark-1.3", status: "not recorded" }],
    file_claim: { verdict: null },
  }];
  const loaded = loadCaseDocument(JSON.stringify(doc));
  assert.equal(loaded.ok, true, loaded.errors.join(" "));
  assert.equal(loaded.trust, "UNVERIFIED");
  assert.equal(loaded.document.pilot.valid_export_pairs, null);
  assert.equal(loaded.document.pilot.attempted, 0);
  const viewed = inspectRow(loaded.document, "P01");
  assert.equal(viewed.found, true);
  assert.equal(viewed.pilot_row, true);
  assert.equal(viewed.capture.width, 720);
  assert.equal(viewed.trust, "UNVERIFIED");
  assert.deepEqual(rowChoices(loaded.document).map((item) => item.id), ["P01"]);
});

test("local attachment policy rejects urls and non media", () => {
  assert.equal(classifyAttachment({ size: 10, type: "text/plain", name: "notes.txt" }).ok, false);
  assert.equal(classifyAttachment({ size: 10, type: "image/png", name: "shot.png" }).ok, true);
  assert.equal(classifyAttachment({ size: 8000001, type: "image/png", name: "big.png" }).ok, false);
  assert.equal(classifyAttachment({ size: 20, type: "video/mp4", name: "clip.mp4" }).kind, "video");
});

test("viewer source does not hardcode live host timings", () => {
  const source = readFileSync(new URL("./app.js", import.meta.url), "utf8")
    + readFileSync(new URL("./index.html", import.meta.url), "utf8");
  for (const banned of ["2.397", "21.754", "3/5"]) {
    assert.equal(source.includes(banned), false, banned);
  }
  assert.doesNotMatch(source, /emulator-\d{4,6}/);
  assert.equal(source.includes("revokeObjectURL"), true);
  assert.equal(source.includes("createObjectURL"), true);
});

test("stylesheet names the eight widths", () => {
  const css = readFileSync(new URL("./console.css", import.meta.url), "utf8");
  for (const width of [320, 375, 414, 768, 1024, 1280, 1440, 1920]) {
    assert.equal(css.includes(`${width}px`), true, String(width));
  }
  assert.match(css, /^\/\* Hallmark /);
  assert.match(css, /overflow-x:\s*clip/);
  assert.doesNotMatch(css, /transition:\s*all/);
  assert.doesNotMatch(css, /100vw/);
});

test("local media hashes wrap within each comparison column", () => {
  const css = readFileSync(new URL("./console.css", import.meta.url), "utf8");
  assert.match(css, /#preview-line-one, #preview-line-two, #preview-line-video\s*\{\s*overflow-wrap:\s*anywhere/);
});

function finalDocument() {
  const document = emptyRealState().document;
  document.schema = "reproloop.evidence.v2";
  document.cohort = { ...document.pilot, id: "native-v4obs1-final", split: "FINAL", condition: "B3_NATIVE_VIDEO_SAMPLED_CONTEXT_V4_OBS1",
    planned_case_ids: ["FINAL-A", "FINAL-B", "FINAL-C"], attempted: 3, complete: 3, not_run_ids: [] };
  delete document.pilot;
  document.cases = document.cohort.planned_case_ids.map(case_id => ({case_id, file_claim: {verdict: "SUCCESS"}}));
  return document;
}
test("FINAL three-case import does not become a five-case pilot or trusted result", () => {
  const loaded = loadCaseDocument(JSON.stringify(finalDocument()));
  assert.equal(loaded.ok, true, loaded.errors.join(" "));
  assert.equal(loaded.trust, "UNVERIFIED");
  assert.equal(loaded.document.pilot, undefined);
  assert.equal(loaded.document.cohort.planned_case_ids.length, 3);
  assert.equal(loaded.document.cohort.valid_export_pairs, null);
  const row = inspectRow(loaded.document, "FINAL-C");
  assert.equal(row.split, "FINAL");
  assert.equal(row.cohort_id, "native-v4obs1-final");
  assert.equal(row.pilot_row, false);
  assert.equal(row.illustration, false);
  assert.equal(row.file_claim.verdict, "SUCCESS");
  assert.equal(row.trust, "UNVERIFIED");
});
test("v1 stays five-case only and neither version accepts a second denominator", () => {
  const v2 = finalDocument();v2.pilot = emptyRealState().document.pilot;
  assert.equal(loadCaseDocument(JSON.stringify(v2)).ok, false);
  const v1 = emptyRealState().document;v1.cohort = finalDocument().cohort;
  assert.equal(loadCaseDocument(JSON.stringify(v1)).ok, false);
  delete v1.cohort;v1.pilot.planned_case_ids = ["P01", "P02", "P03"];
  assert.equal(loadCaseDocument(JSON.stringify(v1)).ok, false);
});
test("missing or malformed plan ids are rejected without throwing", () => {
  for (const schema of ["reproloop.evidence.v1", "reproloop.evidence.v2"]) {
    for (const ids of [undefined, null, 3, {}, "P01", [], [null], ["P01", "P01"]]) {
      const document = schema.endsWith("v1") ? emptyRealState().document : finalDocument();
      (document.pilot || document.cohort).planned_case_ids = ids;
      const loaded = loadCaseDocument(JSON.stringify(document));
      assert.equal(loaded.ok, false, `${schema} ${JSON.stringify(ids)}`);
    }
  }
});
test("duplicate rows, illustration collisions and foreign-cohort rows reject", () => {
  const duplicate = finalDocument();duplicate.cases.push(duplicate.cases[0]);
  assert.equal(loadCaseDocument(JSON.stringify(duplicate)).ok, false);
  const foreign = finalDocument();foreign.cases[0].case_id = "P01";
  assert.equal(loadCaseDocument(JSON.stringify(foreign)).ok, false);
  const collision = finalDocument();collision.illustration = {...collision.cases[0], not_a_pilot_row: true};
  assert.equal(loadCaseDocument(JSON.stringify(collision)).ok, false);
});
test("cohort identity and split must be explicit; scores remain null", () => {
  for (const [key, value] of [["id", ""], ["condition", null], ["split", "WHATEVER"], ["valid_export_pairs", 3], ["fixed_failure_signals", 0], ["invalid_confirmations", 0]]) {
    const document = finalDocument();document.cohort[key] = value;
    assert.equal(loadCaseDocument(JSON.stringify(document)).ok, false, key);
  }
});
test("partial FINAL counts preserve not-run separately from unknown", () => {
  const document = finalDocument();
  Object.assign(document.cohort, {attempted: 2, complete: 1, unknown: 1, not_run_ids: ["FINAL-C"]});
  assert.equal(loadCaseDocument(JSON.stringify(document)).ok, true);
  document.cohort.unknown = 2;
  assert.equal(loadCaseDocument(JSON.stringify(document)).ok, false);
});
test("oversized nesting is an input error, not a stack crash", () => {
  const document = finalDocument();let nested = document;
  for (let index = 0; index < 100; index += 1) {nested.extra = {};nested = nested.extra;}
  const loaded = loadCaseDocument(JSON.stringify(document));
  assert.equal(loaded.ok, false);
  assert.match(loaded.errors.join(" "), /nesting/);
});

test("rendered collections reject null, primitive and non-array members", () => {
  for (const key of ["models", "intents", "task_steps", "nodes"]) {
    for (const bad of [[null], ["text"], [4], [[]], {}]) {
      const document = finalDocument();
      if (key === "nodes") document.cases[0].capture = {nodes: bad};
      else document.cases[0][key] = bad;
      const loaded = loadCaseDocument(JSON.stringify(document));
      assert.equal(loaded.ok, false, `${key}: ${JSON.stringify(bad)}`);
    }
  }
});


test('ordinary task ellipses are accepted without relaxing actual path and URL rejection', () => {
  for (const text of ['Tap ... then Cancel', 'Wait.. then inspect the title', 'Rename a..b without saving']) {
    const document = JSON.parse(sample);document.illustration.intents[0].text = text;
    const loaded = loadCaseDocument(JSON.stringify(document));
    assert.equal(loaded.ok, true, loaded.errors.join(' '));assert.equal(loaded.trust, 'UNVERIFIED');
    assert.equal(loaded.document.pilot.valid_export_pairs, null);
  }
  for (const path of ['..', '../secret', 'nested/../secret', 'read ../secret', '%2e%2e/secret', 'x\\y', 'https://outside.test/a', '//outside.test/a', 'data:text/plain,no']) {
    const document = JSON.parse(sample);document.illustration.media.label = path;
    const loaded = loadCaseDocument(JSON.stringify(document));assert.equal(loaded.ok, false, path);
    assert.equal(loaded.document, null);assert.equal(loaded.trust, 'UNVERIFIED');
  }
});
