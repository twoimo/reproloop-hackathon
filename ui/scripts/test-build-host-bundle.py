#!/usr/bin/env python3
import json
import importlib.util
import os
from unittest.mock import patch
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("build-host-bundle.py")


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, bytes):
        path.write_bytes(obj)
    else:
        path.write_text(json.dumps(obj), encoding="utf-8")


def fake_root(root: Path) -> None:
    png = b"\x89PNG\r\n\x1a\nfake"
    xml = """<?xml version="1.0"?><hierarchy rotation="0"><node resource-id="lab.app:id/cancel" text="Cancel" clickable="true" bounds="[1,2][3,4]"/></hierarchy>"""
    import hashlib
    png_sha = hashlib.sha256(png).hexdigest()
    xml_sha = hashlib.sha256(xml.encode()).hexdigest()
    write(root / "evidence" / f"{png_sha}.png", png)
    write(root / "evidence" / f"{xml_sha}.xml", xml.encode())
    capture = {
        "run_id": "RUN-FAULTY", "sequence": 2, "width": 20, "height": 40,
        "png_sha256": png_sha, "xml_sha256": xml_sha, "atomic": False, "coherent": True,
        "png_path": "/" + "Users/hidden/should-not-pass.png", "serial": "emulator-1",
    }
    write(root / "evidence" / "capture.capture.json", capture)
    fixed_capture = dict(capture, run_id="RUN-FIXED", sequence=3)
    write(root / "evidence" / "fixed.capture.json", fixed_capture)
    replay = {
        "oracle_run": {
            "run_id": "RUN-FAULTY", "build_sha256": "a" * 64, "oracle_log_sha256": "b" * 64,
            "preconditions_verified": True, "completed": True, "goal_reached": True,
            "failure_observed": True,
        },
        "model_calls": 0,
        "reset_receipt_sha256": "c" * 64,
        "trace_sha256": "d" * 64,
        "run_proof": {"reset_snapshot": {"expectation": {"fixture": {"layout_variant": "A"}}}},
        "evidencepaths": ["/" + "Users/hidden/trace.json"],
    }
    fixed = json.loads(json.dumps(replay))
    fixed["oracle_run"]["run_id"] = "RUN-FIXED"
    fixed["oracle_run"]["failure_observed"] = False
    fixed["oracle_run"]["build_sha256"] = "e" * 64
    write(root / "faulty-replay.json", replay)
    write(root / "fixed-replay.json", fixed)
    write(root / "summary.json", {
        "case_id": "DEV-01", "not_a_pilot_result": True, "model_calls": 0, "video_calls": 0,
        "completed_runs": 2, "wall_seconds": 1.5, "mode": "NATIVE_AVD_NO_LLM",
        "condition": "B1_AUTHOR_SPECIFIED_SEMANTIC_BASELINE",
        "pair_verdict": "NOT_JUDGED_RAW_BINDER_REQUIRED", "pair_binding_valid": False,
    })
    write(root / "intent.json", {"case_id": "DEV-01", "meta_calls": 0, "video_calls": 0, "script_sha256": "f" * 64})
    write(root / "author-semantic-script.json", {"steps": [{"visible_text": "Press Cancel"}]})
    write(root / "binding-report.json", {
        "valid": True,
        "collected_pair": {"decision": {
            "verdict": "reproduced_oracle_and_control_confirmed",
            "reason": "reported only",
            "case_manifest_sha256": "1" * 64,
        }},
        "proof": {
            "basis": "host origin assumed, not attested",
            "files_checked": 55,
            "bytes_checked": 10,
            "faulty": {"source_sha256": {"replay.py": "2" * 64}, "serial": "emulator-9", "owner_id": "secret"},
            "fixed": {"source_sha256": {"replay.py": "2" * 64}},
        },
    })


class BundleTests(unittest.TestCase):
    def test_fake_root_omits_private_fields_and_keeps_scores_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "case"
            out = Path(tmp).resolve() / "out.json"
            fake_root(root)
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("/Users", text)
            self.assertNotIn("emulator-", text)
            self.assertNotIn("secret", text)
            data = json.loads(text)
            self.assertEqual(data["schema"], "reproloop.evidence.v1")
            self.assertEqual(data["evidence_level"], "HOST_OBSERVED")
            self.assertEqual(data["meta_calls"], 0)
            self.assertEqual(data["video_calls"], 0)
            self.assertEqual(data["pilot"]["attempted"], 0)
            self.assertEqual(data["cases"], [])
            self.assertIsNone(data["pilot"]["valid_export_pairs"])
            self.assertEqual(data["illustration"]["case_id"], "DEV-01")
            self.assertEqual(data["illustration"]["variant"], "A")
            self.assertTrue(data["illustration"]["not_a_pilot_row"])
            self.assertEqual(data["illustration"]["faulty"]["failure_observed"], True)
            self.assertEqual(data["illustration"]["fixed"]["failure_observed"], False)
            self.assertEqual(data["illustration"]["capture"]["node_count"], 1)
            scope = data["illustration"]["pair_report"]["scope"]
            self.assertEqual(scope["replay_json_files"], 2)
            self.assertFalse(scope["binder_matches_referenced_scope"])
            self.assertNotIn("integrity", " ".join(data["illustration"]["unknown"]))
            self.assertEqual(data["pilot"]["unknown"], 0)
            self.assertEqual(data["pilot"]["not_run_ids"], ["P01", "P02", "P03", "P04", "P05"])

    def test_producer_output_roundtrips_through_real_console_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp).resolve() / "case", Path(tmp).resolve() / "import.json"
            fake_root(root)
            made = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            adapter = json.dumps((SCRIPT.parent.parent / "adapter.js").as_uri())
            check = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {loadCaseDocument,inspectRow,rowChoices} from ADAPTER;
const raw=readFileSync(0,'utf8'), loaded=loadCaseDocument(raw);
assert.equal(loaded.ok,true,loaded.errors.join(' '));
assert.equal(loaded.trust,'UNVERIFIED');
const doc=loaded.document, row=inspectRow(doc,'DEV-01');
assert.equal(doc.pilot.attempted,0);assert.equal(doc.pilot.valid_export_pairs,null);
assert.equal(doc.cases.length,0);assert.equal(row.found,true);
assert.equal(row.illustration,true);assert.equal(row.pilot_row,false);
assert.equal(row.task_steps[0].visible_text,'Press Cancel');
assert.equal(row.faulty.failure_observed,true);assert.equal(row.fixed.failure_observed,false);
assert.equal(rowChoices(doc).length,1);
// Negative controls detect both independently reproduced old defects.
const wrongRow=structuredClone(doc);wrongRow.cases=[wrongRow.illustration];wrongRow.illustration=null;
assert.equal(loadCaseDocument(JSON.stringify(wrongRow)).ok,false);
const wrongSteps=structuredClone(doc);wrongSteps.illustration.task_steps=['Press Cancel'];
assert.equal(loadCaseDocument(JSON.stringify(wrongSteps)).ok,false);
""".replace("ADAPTER", adapter)
            checked = subprocess.run(["node", "--input-type=module", "-e", check], input=out.read_text(), capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_tampered_capture_rejects_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp).resolve() / "case", Path(tmp).resolve() / "import.json"
            fake_root(root)
            next((root / "evidence").glob("*.png")).write_bytes(b"changed")
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("blob name does not match bytes", result.stderr)
            self.assertFalse(out.exists())

    def test_mismatched_case_identity_rejects_without_creating_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp).resolve() / "case", Path(tmp).resolve() / "import.json"
            fake_root(root)
            write(root / "intent.json", {"case_id": "another-case"})
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("case ids differ", result.stderr)
            self.assertFalse(out.exists())

    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root, out = base / "case", base / "result.json"
            fake_root(root)
            out.write_bytes(b"existing bytes must survive")
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(out.read_bytes(), b"existing bytes must survive")

    def test_new_output_inside_source_case_is_rejected_without_tree_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "case"
            fake_root(root)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(root / "new-export.json")], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_destination_symlink_cannot_overwrite_its_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root, out, victim = base / "case", base / "result.json", base / "victim.json"
            fake_root(root)
            victim.write_bytes(b"target must survive")
            out.symlink_to(victim)
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertTrue(out.is_symlink())
            self.assertEqual(victim.read_bytes(), b"target must survive")

    def test_symlink_output_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root, real, alias = base / "case", base / "real", base / "alias"
            fake_root(root)
            real.mkdir()
            alias.symlink_to(real, target_is_directory=True)
            result = subprocess.run([sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(alias / "result.json")], capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(list(real.iterdir()), [])

    def test_concurrent_creators_have_one_complete_private_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root, out = base / "case", base / "result.json"
            fake_root(root)
            command = [sys.executable, str(SCRIPT), "--case-root", str(root), "--out", str(out)]
            processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
            for process in processes:
                process.communicate(timeout=10)
            self.assertEqual(sorted(process.returncode for process in processes), [0, 2])
            self.assertEqual(json.loads(out.read_text())["illustration"]["case_id"], "DEV-01")
            self.assertEqual(out.stat().st_mode & 0o777, 0o600)
            self.assertEqual({p.name for p in base.iterdir()}, {"case", "result.json"})

    def test_staging_failure_leaves_no_final_or_partial_output(self):
        spec = importlib.util.spec_from_file_location("writer_failure", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root, out = base / "case", base / "result.json"
            fake_root(root)
            with patch.object(module.os, "fsync", side_effect=OSError("injected before commit")):
                with self.assertRaises(OSError):
                    module.write_new_document(root, out, {"example": "data"})
            self.assertEqual({p.name for p in base.iterdir()}, {"case"})

    def test_script_does_not_hardcode_live_measurements(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for banned in ("2.397", "21.754", "405156", "63.634"):
            self.assertNotIn(banned, source)
        self.assertNotRegex(source, r"emulator-\d{4,6}")


if __name__ == "__main__":
    unittest.main()
