#!/usr/bin/env python3
"""Build a reproloop.evidence.v1 JSON from a B1 case root. Stdlib only.

The saved non-pilot record uses v1 illustration, never the pilot cases array.
The output is a file the UI can import. Import stays unverified. This script
does not attest host origin and does not write unless --out is set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = "reproloop.evidence.v1"
DROP_KEYS = {
    "serial", "owner_id", "boot_id", "host_boot_id", "observer", "avd_name",
    "png_path", "xml_path", "evidencepaths", "token", "safety_token",
}
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be an object")
    return data


def parse_bounds(value: str | None) -> list[int] | None:
    if not value:
        return None
    match = BOUNDS.fullmatch(value.strip())
    if not match:
        return None
    return [int(part) for part in match.groups()]


def nodes_from_xml(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    nodes = []
    for element in root.iter("node"):
        resource = element.attrib.get("resource-id") or ""
        short = resource.split("/")[-1] if resource else None
        nodes.append({
            "resource_id": short,
            "text": element.attrib.get("text") or "",
            "clickable": element.attrib.get("clickable") == "true",
            "bounds": parse_bounds(element.attrib.get("bounds")),
        })
    return nodes


def last_capture(evidence: Path, run_id: str) -> dict:
    chosen = None
    for path in evidence.glob("*.capture.json"):
        data = read_json(path)
        if data.get("run_id") != run_id:
            continue
        sequence = data.get("sequence")
        if not isinstance(sequence, int):
            continue
        if chosen is None or sequence >= chosen["sequence"]:
            chosen = data
    if chosen is None:
        raise ValueError(f"no capture for {run_id}")
    return chosen


def verify_blob(evidence: Path, digest: str, suffix: str) -> None:
    path = evidence / f"{digest}{suffix}"
    if not path.is_file():
        raise ValueError(f"missing {suffix} blob {digest}")
    actual = sha256_bytes(path.read_bytes())
    if actual != digest:
        raise ValueError(f"blob name does not match bytes for {suffix}")


def side(replay: dict, binding_side: dict, evidence: Path) -> dict:
    oracle = replay["oracle_run"]
    capture = last_capture(evidence, oracle["run_id"])
    xml_sha = capture.get("xml_sha256")
    png_sha = capture.get("png_sha256")
    if not isinstance(xml_sha, str) or not isinstance(png_sha, str):
        raise ValueError("capture is missing xml or png sha")
    verify_blob(evidence, xml_sha, ".xml")
    verify_blob(evidence, png_sha, ".png")
    nodes = nodes_from_xml(evidence / f"{xml_sha}.xml")
    return {
        "run_id": oracle["run_id"],
        "build_sha256": oracle["build_sha256"],
        "oracle_log_sha256": oracle["oracle_log_sha256"],
        "reset_verified": oracle["preconditions_verified"] is True,
        "no_llm": replay.get("model_calls") == 0,
        "workflow_complete": oracle["completed"] is True and oracle["goal_reached"] is True,
        "failure_observed": oracle["failure_observed"],
        "reset_sha256": replay["reset_receipt_sha256"],
        "trace_sha256": replay["trace_sha256"],
        "capture": {
            "width": capture.get("width"),
            "height": capture.get("height"),
            "node_count": len(nodes),
            "sequence": capture.get("sequence"),
            "atomic": capture.get("atomic"),
            "coherent": capture.get("coherent"),
            "png_sha256": png_sha,
            "xml_sha256": xml_sha,
            "nodes": nodes,
        },
        "source_sha256": {
            key: value for key, value in (binding_side.get("source_sha256") or {}).items()
            if isinstance(key, str) and isinstance(value, str) and len(value) == 64
        },
    }


def scope_report(case_root: Path, binder_files, binder_bytes) -> dict:
    evidence = []
    replays = []
    extra = []
    for path in sorted(case_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(case_root).as_posix()
        size = path.stat().st_size
        if rel.startswith("evidence/"):
            evidence.append((rel, size))
        elif rel in ("faulty-replay.json", "fixed-replay.json"):
            replays.append((rel, size))
        else:
            extra.append((path.name, size))
    referenced_files = len(evidence) + len(replays)
    referenced_bytes = sum(size for _, size in evidence) + sum(size for _, size in replays)
    extra_bytes = sum(size for _, size in extra)
    return {
        "binder_files_checked": binder_files,
        "binder_bytes_checked": binder_bytes,
        "referenced_evidence_files": len(evidence),
        "referenced_evidence_bytes": sum(size for _, size in evidence),
        "replay_json_files": len(replays),
        "replay_json_bytes": sum(size for _, size in replays),
        "referenced_scope_files": referenced_files,
        "referenced_scope_bytes": referenced_bytes,
        "binder_matches_referenced_scope": binder_files == referenced_files and binder_bytes == referenced_bytes,
        "extra_top_files": [{"name": name, "bytes": size} for name, size in extra],
        "extra_top_bytes": extra_bytes,
        "folder_files": referenced_files + len(extra),
        "folder_bytes": referenced_bytes + extra_bytes,
        "scope_note": "Binder scope is referenced evidence plus the two replay JSON files. Folder scope adds the other top metadata files. These are different denominators, not a byte-integrity failure when the binder matches the referenced scope.",
    }


def tree_digest(root: Path) -> tuple[str, int, int]:
    lines = []
    count = 0
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        count += 1
        total += len(data)
        rel = path.relative_to(root).as_posix()
        lines.append(f"{sha256_bytes(data)} {len(data)} {rel}")
    digest = sha256_bytes("\n".join(lines).encode("utf-8"))
    return digest, count, total


def forbidden(value, path="$") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in DROP_KEYS:
                found.append(f"{path}.{key}")
            found.extend(forbidden(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(forbidden(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        if value.startswith("/") or "\\Users" in value or "/Users/" in value or "emulator-" in value:
            found.append(path)
        if ".." in value:
            found.append(path)
    return found


def build(case_root: Path) -> dict:
    summary = read_json(case_root / "summary.json")
    intent = read_json(case_root / "intent.json")
    script = read_json(case_root / "author-semantic-script.json")
    binding = read_json(case_root / "binding-report.json")
    faulty = read_json(case_root / "faulty-replay.json")
    fixed = read_json(case_root / "fixed-replay.json")
    if summary.get("case_id") != intent.get("case_id"):
        raise ValueError("summary and intent case ids differ")
    if summary.get("not_a_pilot_result") is not True:
        raise ValueError("refusing a root that is not marked not_a_pilot_result")
    evidence = case_root / "evidence"
    faulty_side = side(faulty, binding["proof"]["faulty"], evidence)
    fixed_side = side(fixed, binding["proof"]["fixed"], evidence)
    decision = binding["collected_pair"]["decision"]
    digest, files, nbytes = tree_digest(case_root)
    binder_files = binding["proof"].get("files_checked")
    binder_bytes = binding["proof"].get("bytes_checked")
    unknown = [
        "host origin is assumed by the binder, not attested here",
        "capture and read coherence is not atomic",
        "saved journal producer authenticity is outside the binder",
    ]
    scope = scope_report(case_root, binder_files, binder_bytes)
    if not scope["binder_matches_referenced_scope"]:
        unknown.append("binder file count does not match referenced evidence plus replay JSON")
    steps = [{"visible_text": step.get("visible_text")} for step in script.get("steps") or [] if isinstance(step, dict)]
    fixture = faulty["run_proof"]["reset_snapshot"]["expectation"]["fixture"]
    wall = summary.get("wall_seconds")
    model_calls = summary.get("model_calls")
    if model_calls is None:
        model_calls = intent.get("meta_calls")
    video_calls = summary.get("video_calls", intent.get("video_calls"))
    return {
        "schema": SCHEMA,
        "evidence_level": "HOST_OBSERVED",
        "mode": "real",
        "meta_calls": model_calls,
        "android_runs": summary.get("completed_runs"),
        "video_calls": video_calls,
        "cua_calls": model_calls if summary.get("mode") == "NATIVE_AVD_NO_LLM" else None,
        "pilot": {
            "planned_case_ids": ["P01", "P02", "P03", "P04", "P05"],
            "attempted": 0,
            "complete": 0,
            "unknown": 0,
            "not_run_ids": ["P01", "P02", "P03", "P04", "P05"],
            "excluded": 0,
            "valid_export_pairs": None,
            "fixed_failure_signals": None,
            "invalid_confirmations": None,
            "note": "DEV case is not a pilot row. M1 is not run.",
        },
        "cases": [],
        "illustration": {
            "case_id": summary["case_id"],
            "variant": fixture.get("layout_variant"),
            "bug_family": faulty["oracle_run"].get("oracle_name"),
            "not_a_pilot_row": True,
            "condition": summary.get("condition"),
            "media": {"sha256": None, "label": "No video is in this baseline."},
            "intents": [{"t": None, "text": step["visible_text"]} for step in steps],
            "task_steps": steps,
            "faulty": {
                "run_id": faulty_side["run_id"],
                "build_sha256": faulty_side["build_sha256"],
                "reset_verified": faulty_side["reset_verified"],
                "no_llm": faulty_side["no_llm"],
                "workflow_complete": faulty_side["workflow_complete"],
                "failure_observed": faulty_side["failure_observed"],
            },
            "fixed": {
                "run_id": fixed_side["run_id"],
                "build_sha256": fixed_side["build_sha256"],
                "reset_verified": fixed_side["reset_verified"],
                "no_llm": fixed_side["no_llm"],
                "workflow_complete": fixed_side["workflow_complete"],
                "failure_observed": fixed_side["failure_observed"],
            },
            "reset": {
                "verified": faulty_side["reset_verified"] and fixed_side["reset_verified"],
                "reason": "Reset receipts exist for both runs. This is not a new reset.",
            },
            "capture": faulty_side["capture"],
            "fixed_capture": fixed_side["capture"],
            "png_claims": {
                "faulty": faulty_side["capture"]["png_sha256"],
                "fixed": fixed_side["capture"]["png_sha256"],
            },
            "source_ids": [
                intent.get("script_sha256"),
                decision.get("case_manifest_sha256"),
                faulty_side["build_sha256"],
                fixed_side["build_sha256"],
                faulty_side["trace_sha256"],
                fixed_side["trace_sha256"],
            ],
            "models": [],
            "file_claim": {
                "verdict": decision.get("verdict"),
                "reason": "Binder reported a verdict. Summary still says the raw binder was required. Not attestation.",
            },
            "pair_report": {
                "condition": summary.get("condition"),
                "author_specified": summary.get("condition") == "B1_AUTHOR_SPECIFIED_SEMANTIC_BASELINE",
                "summary_pair_verdict": summary.get("pair_verdict"),
                "summary_pair_binding_valid": summary.get("pair_binding_valid"),
                "binder_valid": binding.get("valid"),
                "binder_verdict": decision.get("verdict"),
                "binder_reason": decision.get("reason"),
                "why_not_attestation": binding["proof"].get("basis"),
                "binder_files_checked": binder_files,
                "binder_bytes_checked": binder_bytes,
                "scope": scope,
                "generator_files_read": files,
                "generator_bytes_read": nbytes,
                "generator_tree_digest": digest,
                "loaded_scope_meta_calls": model_calls,
                "loaded_scope_note": "meta_calls is this loaded case scope, not an account total.",
            },
            "cost_usd": None,
            "latency_ms": round(wall * 1000) if isinstance(wall, (int, float)) else None,
            "unknown": unknown,
        },
    }


def write_new_document(root: Path, out: Path, document: dict) -> None:
    """Trusted stable local filesystem; stage fully, then exclusive hard-link."""
    out = out.absolute()
    source = root.resolve()
    if out == source or source in out.parents:
        raise ValueError("output must be outside the read-only case root")
    if out.parent.resolve() != out.parent:
        raise ValueError("output parent must not contain symlinks or path aliases")
    if out.exists() or out.is_symlink():
        raise ValueError("output already exists; inspect it before choosing a new path")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".console-", suffix=".partial", dir=out.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Like the existing source-candidate builder: never replace a winner,
        # existing evidence or a symlink, including a late concurrent create.
        os.link(temporary, out)
    finally:
        os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.case_root)
    if not root.is_dir():
        print("case root is not a directory", file=sys.stderr)
        return 2
    try:
        document = build(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"bundle build failed: {exc}", file=sys.stderr)
        return 2
    problems = forbidden(document)
    if document.get("cua_calls") is None or problems:
        print("refusing output with missing scope or forbidden fields", file=sys.stderr)
        return 2
    try:
        write_new_document(root, Path(args.out), document)
    except (OSError, ValueError):
        print("output creation refused or failed; inspect the destination before any retry", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
