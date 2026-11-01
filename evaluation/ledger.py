"""Structured immutable JSONL experiment ledger and validator-bound aggregator.

Reuses the reviewed baseline validators directly:
- examples/repro_oracle.py (CaseSpec, OracleRun, Verdict, valid_name, valid_digest, judge_release)
- examples/replay_contracts.py (CollectedPair, collect_pair)
- examples/evaluation_metrics.py (EvaluationRow, summarize)
- examples/meta_protocol.py (estimate_usd)

Enforces:
- Denominator diary tracking: planned, attempted, complete, excluded, unknown.
- Missing token/cost/latency fields remain explicit "UNKNOWN" (never 0 or byte-estimated).
- Self-reported model JSON / VLM visual judgments / SAM masks are rejected as oracle sources.
- Append-only hash-chained JSONL records with duplicate attempt rejection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Literal

from .splits import (
    FAULT_FAMILY_ID,
    PACKAGE_NAME,
    NativeScenario,
    NativeSplitManifest,
    SplitManifest,
    build_frozen_splits,
    get_native_scenario,
    get_scenario,
)

_EXAMPLES_DIR = str(Path(__file__).resolve().parents[1] / "examples")
if _EXAMPLES_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLES_DIR)

from evaluation_metrics import EvaluationRow, summarize  # noqa: E402
from meta_protocol import estimate_usd  # noqa: E402
from replay_contracts import CollectedPair, collect_pair  # noqa: E402
from repro_oracle import (  # noqa: E402
    CaseSpec,
    OracleRun,
    Verdict,
    valid_digest,
    valid_name,
)

VALID_STATUSES = ("planned", "attempted", "complete", "excluded", "unknown")
VALID_EVIDENCE_MODES = ("SYNTHETIC", "HOST_INSTRUMENTED", "NATIVE_AVD_NO_LLM", "LIVE_META_API")
TRUSTED_ORACLE_SOURCES = ("SYNTHETIC_FIXTURE_HARNESS", "ANDROID_DEBUG_READBACK_BRIDGE", "NONE_NOT_RUN")
FORBIDDEN_ORACLE_SOURCES = ("MODEL_JSON_OUTPUT", "SCREENSHOT_VLM_JUDGE", "SAM_MASK_SIMILARITY")
GENESIS_PREV_SHA256 = "0" * 64


def _opt_int_or_unknown(value: object, field_name: str, maximum: int = 10**9) -> int | Literal["UNKNOWN"]:
    if value == "UNKNOWN":
        return "UNKNOWN"
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{field_name} must be exact non-negative int or 'UNKNOWN', got {value!r}")
    return value


def _opt_usd_or_unknown(value: object, field_name: str) -> str:
    if value == "UNKNOWN":
        return "UNKNOWN"
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical decimal string or 'UNKNOWN'")
    try:
        dec = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal string for {field_name}: {value!r}") from exc
    if not dec.is_finite() or dec < Decimal("0") or dec > Decimal("10000"):
        raise ValueError(f"out-of-range decimal for {field_name}: {value!r}")
    return str(dec)


@dataclass(frozen=True)
class AttemptMetrics:
    input_tokens: int | Literal["UNKNOWN"] = "UNKNOWN"
    cached_tokens: int | Literal["UNKNOWN"] = "UNKNOWN"
    output_tokens: int | Literal["UNKNOWN"] = "UNKNOWN"
    reasoning_tokens: int | Literal["UNKNOWN"] = "UNKNOWN"
    video_frames_processed: int | Literal["UNKNOWN"] = "UNKNOWN"
    cua_calls: int | Literal["UNKNOWN"] = "UNKNOWN"
    driver_actions: int | Literal["UNKNOWN"] = "UNKNOWN"
    wall_latency_ms: int | Literal["UNKNOWN"] = "UNKNOWN"
    estimated_cost_usd: str = "UNKNOWN"

    def validate(self) -> None:
        in_tok = _opt_int_or_unknown(self.input_tokens, "input_tokens")
        cache_tok = _opt_int_or_unknown(self.cached_tokens, "cached_tokens")
        out_tok = _opt_int_or_unknown(self.output_tokens, "output_tokens")
        _opt_int_or_unknown(self.reasoning_tokens, "reasoning_tokens")
        _opt_int_or_unknown(self.video_frames_processed, "video_frames_processed")
        _opt_int_or_unknown(self.cua_calls, "cua_calls", 1000)
        _opt_int_or_unknown(self.driver_actions, "driver_actions", 10000)
        _opt_int_or_unknown(self.wall_latency_ms, "wall_latency_ms", 3600 * 1000)
        cost_str = _opt_usd_or_unknown(self.estimated_cost_usd, "estimated_cost_usd")

        if type(in_tok) is int and type(cache_tok) is int and cache_tok > in_tok:
            raise ValueError("cached_tokens cannot exceed input_tokens")
        # If cost is provided, all three token counts must be known ints and match estimate_usd
        if cost_str != "UNKNOWN":
            if not (type(in_tok) is int and type(cache_tok) is int and type(out_tok) is int):
                raise ValueError(
                    "estimated_cost_usd cannot be set when input/cached/output tokens are 'UNKNOWN' "
                    "(never estimate cost from byte counts)"
                )
            expected = estimate_usd(in_tok, cache_tok, out_tok)
            if Decimal(cost_str) != expected:
                raise ValueError(f"estimated_cost_usd {cost_str} != exact Spark 1.3 formula {expected}")


@dataclass(frozen=True)
class RunSideEvidence:
    run_id: str | None
    build_sha256: str
    reset_receipt_sha256: str | None
    oracle_log_sha256: str | None
    trusted_oracle_source: str
    completed: bool
    preconditions_verified: bool
    goal_reached: bool
    failure_observed: bool | None
    visual_match: bool = False

    def validate(self, expected_build_sha256: str) -> None:
        if not valid_digest(self.build_sha256) or self.build_sha256 != expected_build_sha256:
            raise ValueError("RunSideEvidence build_sha256 mismatch")
        if type(self.trusted_oracle_source) is not str:
            raise ValueError("trusted_oracle_source must be str")
        if self.trusted_oracle_source in FORBIDDEN_ORACLE_SOURCES:
            raise ValueError(
                f"untrusted self-reported oracle source forbidden: {self.trusted_oracle_source!r}"
            )
        if self.trusted_oracle_source not in TRUSTED_ORACLE_SOURCES:
            raise ValueError(f"unknown oracle source: {self.trusted_oracle_source!r}")
        for flag_name, flag_val in (
            ("completed", self.completed),
            ("preconditions_verified", self.preconditions_verified),
            ("goal_reached", self.goal_reached),
            ("visual_match", self.visual_match),
        ):
            if type(flag_val) is not bool:
                raise ValueError(f"{flag_name} must be exact bool")
        if self.failure_observed is not None and type(self.failure_observed) is not bool:
            raise ValueError("failure_observed must be bool or None")

        if self.run_id is not None and not valid_name(self.run_id, 128):
            raise ValueError("invalid run_id")
        if self.reset_receipt_sha256 is not None and not valid_digest(self.reset_receipt_sha256):
            raise ValueError("invalid reset_receipt_sha256")
        if self.oracle_log_sha256 is not None and not valid_digest(self.oracle_log_sha256):
            raise ValueError("invalid oracle_log_sha256")

        if self.completed or self.preconditions_verified or self.goal_reached or self.failure_observed is not None:
            if (
                self.run_id is None
                or self.reset_receipt_sha256 is None
                or self.oracle_log_sha256 is None
                or self.trusted_oracle_source == "NONE_NOT_RUN"
            ):
                raise ValueError(
                    "active run evidence requires run_id, reset_receipt_sha256, oracle_log_sha256, "
                    "and an active trusted_oracle_source"
                )

    def to_oracle_run(self, spec: CaseSpec, generation: int) -> OracleRun | None:
        if self.run_id is None or self.oracle_log_sha256 is None:
            return None
        return OracleRun(
            run_id=self.run_id,
            case_id=spec.case_id,
            task_sha256=spec.task_sha256,
            fixture_sha256=spec.fixture_sha256,
            build_sha256=self.build_sha256,
            oracle_name=spec.oracle_name,
            oracle_log_sha256=self.oracle_log_sha256,
            completed=self.completed,
            preconditions_verified=self.preconditions_verified,
            goal_reached=self.goal_reached,
            failure_observed=self.failure_observed,
            generation=generation,
            visual_match=self.visual_match,
        )


@dataclass(frozen=True)
class ExperimentAttemptRecord:
    experiment_id: str
    attempt_id: str
    case_id: str
    split: str
    variant: str
    condition_id: str  # e.g., 'B0_coord', 'B1_semantic', 'B3_spark_cua'
    repeat_index: int
    status: str  # 'planned' | 'attempted' | 'complete' | 'excluded' | 'unknown'
    reason_code: str
    evidence_mode: str  # 'SYNTHETIC' | 'HOST_INSTRUMENTED' | 'NATIVE_AVD_NO_LLM' | 'LIVE_META_API'
    source_commit_sha256: str
    model_id: str
    prompt_version_sha256: str
    exporter_version: str
    media_sha256: str
    task_sha256: str
    fixture_sha256: str
    faulty_build_sha256: str
    repaired_build_sha256: str
    generation: int
    export_created: bool
    export_script_sha256: str | None
    no_llm_replay_verified: bool
    faulty_evidence: RunSideEvidence
    repaired_evidence: RunSideEvidence
    metrics: AttemptMetrics

    def validate(self, manifest: SplitManifest | NativeSplitManifest | None = None) -> CollectedPair:
        m = build_frozen_splits() if manifest is None else manifest
        if isinstance(m, NativeSplitManifest):
            scenario = get_native_scenario(self.case_id, m)
            scen_variant = scenario.layout_variant
        else:
            scenario = get_scenario(self.case_id, m)
            scen_variant = scenario.variant
        if self.split != scenario.split or self.variant != scen_variant:
            raise ValueError(f"split/variant mismatch against frozen manifest for {self.case_id}")
        if self.task_sha256 != scenario.task_sha256 or self.fixture_sha256 != scenario.fixture_sha256:
            raise ValueError(f"task/fixture digest mismatch against frozen manifest for {self.case_id}")

        for label, val in (
            ("experiment_id", self.experiment_id),
            ("attempt_id", self.attempt_id),
            ("condition_id", self.condition_id),
            ("reason_code", self.reason_code),
            ("model_id", self.model_id),
            ("exporter_version", self.exporter_version),
        ):
            if not valid_name(val, 120):
                raise ValueError(f"invalid {label}: {val!r}")

        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")
        if self.evidence_mode not in VALID_EVIDENCE_MODES:
            raise ValueError(f"invalid evidence_mode: {self.evidence_mode!r}")
        if type(self.repeat_index) is not int or not 1 <= self.repeat_index <= 100:
            raise ValueError(f"invalid repeat_index: {self.repeat_index!r}")
        if type(self.generation) is not int or not 1 <= self.generation <= 2**63 - 1:
            raise ValueError(f"invalid generation: {self.generation!r}")
        if type(self.export_created) is not bool or type(self.no_llm_replay_verified) is not bool:
            raise ValueError("export_created and no_llm_replay_verified must be exact bool")

        for digest_label, digest_val in (
            ("source_commit_sha256", self.source_commit_sha256),
            ("prompt_version_sha256", self.prompt_version_sha256),
            ("media_sha256", self.media_sha256),
            ("faulty_build_sha256", self.faulty_build_sha256),
            ("repaired_build_sha256", self.repaired_build_sha256),
        ):
            if not valid_digest(digest_val):
                raise ValueError(f"invalid {digest_label}: {digest_val!r}")
        if self.faulty_build_sha256 == self.repaired_build_sha256:
            raise ValueError("faulty_build_sha256 and repaired_build_sha256 must be distinct")

        if self.export_created:
            if self.export_script_sha256 is None or not valid_digest(self.export_script_sha256):
                raise ValueError("export_created=True requires valid 64-hex export_script_sha256")
        else:
            if self.export_script_sha256 is not None:
                raise ValueError("export_created=False must have export_script_sha256=None")
            if self.no_llm_replay_verified:
                raise ValueError("no_llm_replay_verified cannot be True when export_created=False")

        if type(self.faulty_evidence) is not RunSideEvidence or type(self.repaired_evidence) is not RunSideEvidence:
            raise ValueError("typed RunSideEvidence required")
        self.faulty_evidence.validate(self.faulty_build_sha256)
        self.repaired_evidence.validate(self.repaired_build_sha256)

        if type(self.metrics) is not AttemptMetrics:
            raise ValueError("typed AttemptMetrics required")
        self.metrics.validate()

        if self.evidence_mode == "SYNTHETIC":
            if (
                self.faulty_evidence.trusted_oracle_source == "ANDROID_DEBUG_READBACK_BRIDGE"
                or self.repaired_evidence.trusted_oracle_source == "ANDROID_DEBUG_READBACK_BRIDGE"
            ):
                raise ValueError("SYNTHETIC mode cannot claim ANDROID_DEBUG_READBACK_BRIDGE")

        if self.status in ("planned", "excluded"):
            if self.faulty_evidence.completed or self.repaired_evidence.completed:
                raise ValueError(f"status={self.status!r} cannot mark runs completed=True")

        spec = scenario.to_case_spec(self.faulty_build_sha256, self.repaired_build_sha256)
        faulty_run = self.faulty_evidence.to_oracle_run(spec, self.generation)
        repaired_run = self.repaired_evidence.to_oracle_run(spec, self.generation)

        # Pair binding requires export script hash, both fresh reset receipts, distinct reset receipts,
        # and verified no-LLM replay.
        pair_binding_valid = bool(
            self.status == "complete"
            and self.export_created
            and self.export_script_sha256 is not None
            and self.no_llm_replay_verified
            and self.faulty_evidence.reset_receipt_sha256 is not None
            and self.repaired_evidence.reset_receipt_sha256 is not None
            and self.faulty_evidence.reset_receipt_sha256 != self.repaired_evidence.reset_receipt_sha256
        )

        return collect_pair(
            spec,
            faulty_run,
            repaired_run,
            self.generation,
            export_created=self.export_created,
            pair_binding_valid=pair_binding_valid,
        )


def evaluate_pair_from_attempts(
    record: ExperimentAttemptRecord,
    manifest: SplitManifest | NativeSplitManifest | None = None,
) -> CollectedPair:
    """Validate an ExperimentAttemptRecord and compute its CollectedPair via replay_contracts.collect_pair."""
    if type(record) is not ExperimentAttemptRecord:
        raise ValueError("typed ExperimentAttemptRecord required")
    return record.validate(manifest)


def summarize_split_ledger(
    records: list[ExperimentAttemptRecord],
    *,
    split: Literal["DEV", "PILOT", "FINAL"],
    condition_id: str,
    repeat_index: int = 1,
    manifest: SplitManifest | NativeSplitManifest | None = None,
) -> dict:
    """Aggregate a split's canonical attempt records using evaluation_metrics.summarize()."""
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    m = build_frozen_splits() if manifest is None else manifest
    planned_ids = m.planned_case_ids(split)

    filtered = [
        r for r in records
        if r.split == split and r.condition_id == condition_id and r.repeat_index == repeat_index
    ]
    seen_cases: set[str] = set()
    rows: list[EvaluationRow] = []
    diary = {"planned": len(planned_ids), "attempted": 0, "complete": 0, "excluded": 0, "unknown": 0}
    evidence_modes: set[str] = set()

    for rec in filtered:
        if type(rec) is not ExperimentAttemptRecord:
            raise ValueError("typed ExperimentAttemptRecord required")
        if rec.case_id in seen_cases:
            raise ValueError(f"duplicate record for case_id={rec.case_id} in split={split}, repeat={repeat_index}")
        seen_cases.add(rec.case_id)
        cp = rec.validate(m)
        rows.append(cp.row)
        evidence_modes.add(rec.evidence_mode)

        if rec.status in ("attempted", "complete", "unknown"):
            diary["attempted"] += 1
        if rec.status == "complete":
            diary["complete"] += 1
        elif rec.status == "excluded":
            diary["excluded"] += 1
        elif rec.status == "unknown":
            diary["unknown"] += 1

    if seen_cases != set(planned_ids):
        missing = sorted(set(planned_ids) - seen_cases)
        raise ValueError(f"missing planned case rows in split={split}: {missing}")

    metrics_summary = summarize(rows, planned_ids)
    all_synthetic = (evidence_modes == {"SYNTHETIC"})
    live_pilot_runs = sum(1 for r in filtered if r.evidence_mode in ("NATIVE_AVD_NO_LLM", "LIVE_META_API") and r.status == "complete")

    return {
        "split": split,
        "condition_id": condition_id,
        "repeat_index": repeat_index,
        "evidence_modes": sorted(evidence_modes),
        "is_synthetic_only": all_synthetic,
        "actual_live_pilot_runs": live_pilot_runs,
        "denominator_diary": diary,
        "metrics": metrics_summary,
    }


class ExperimentLedger:
    """Append-only hash-chained JSONL experiment ledger."""

    def __init__(self, path: str | Path, manifest: SplitManifest | NativeSplitManifest | None = None):
        self.path = Path(path)
        self.manifest = build_frozen_splits() if manifest is None else manifest

    @staticmethod
    def _serialize_record(record: ExperimentAttemptRecord, cp: CollectedPair, prev_sha256: str) -> dict:
        body = {
            "schema_version": 1,
            "prev_line_sha256": prev_sha256,
            "record": asdict(record),
            "derived_pair": {
                "verdict": str(cp.decision.verdict),
                "reason": cp.decision.reason,
                "case_manifest_sha256": cp.decision.case_manifest_sha256,
                "row": {
                    "case_id": cp.row.case_id,
                    "export_created": cp.row.export_created,
                    "faulty_complete": cp.row.faulty_complete,
                    "faulty_failure": cp.row.faulty_failure,
                    "fixed_complete": cp.row.fixed_complete,
                    "fixed_failure": cp.row.fixed_failure,
                    "pair_binding_valid": cp.row.pair_binding_valid,
                    "pair_verdict": str(cp.row.pair_verdict),
                },
            },
        }
        line_digest = sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
        ).hexdigest()
        return {**body, "line_sha256": line_digest}

    def append(self, record: ExperimentAttemptRecord) -> dict:
        if type(record) is not ExperimentAttemptRecord:
            raise ValueError("typed ExperimentAttemptRecord required")
        cp = record.validate(self.manifest)
        existing_entries = self.read_and_verify() if self.path.exists() else []
        key = (record.experiment_id, record.case_id, record.condition_id, record.repeat_index, record.attempt_id)
        for entry in existing_entries:
            r = entry["record"]
            old_key = (r["experiment_id"], r["case_id"], r["condition_id"], r["repeat_index"], r["attempt_id"])
            if old_key == key:
                raise ValueError(f"duplicate attempt key in ledger: {key}")

        prev_sha = existing_entries[-1]["line_sha256"] if existing_entries else GENESIS_PREV_SHA256
        envelope = self._serialize_record(record, cp, prev_sha)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n")
        return envelope

    def read_and_verify(self) -> list[dict]:
        if not self.path.exists():
            raise FileNotFoundError(f"ledger file does not exist: {self.path}")
        entries: list[dict] = []
        seen_keys: set[tuple] = set()
        expected_prev = GENESIS_PREV_SHA256

        for line_no, raw_line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw_line.strip():
                raise ValueError(f"blank line in JSONL ledger at line {line_no}")
            obj = json.loads(raw_line)
            if not isinstance(obj, dict) or set(obj) != {"schema_version", "prev_line_sha256", "record", "derived_pair", "line_sha256"}:
                raise ValueError(f"malformed ledger envelope at line {line_no}")
            if obj["prev_line_sha256"] != expected_prev:
                raise ValueError(f"broken hash chain at line {line_no}")
            rec_dict = obj["record"]
            rec = ExperimentAttemptRecord(
                experiment_id=rec_dict["experiment_id"],
                attempt_id=rec_dict["attempt_id"],
                case_id=rec_dict["case_id"],
                split=rec_dict["split"],
                variant=rec_dict["variant"],
                condition_id=rec_dict["condition_id"],
                repeat_index=rec_dict["repeat_index"],
                status=rec_dict["status"],
                reason_code=rec_dict["reason_code"],
                evidence_mode=rec_dict["evidence_mode"],
                source_commit_sha256=rec_dict["source_commit_sha256"],
                model_id=rec_dict["model_id"],
                prompt_version_sha256=rec_dict["prompt_version_sha256"],
                exporter_version=rec_dict["exporter_version"],
                media_sha256=rec_dict["media_sha256"],
                task_sha256=rec_dict["task_sha256"],
                fixture_sha256=rec_dict["fixture_sha256"],
                faulty_build_sha256=rec_dict["faulty_build_sha256"],
                repaired_build_sha256=rec_dict["repaired_build_sha256"],
                generation=rec_dict["generation"],
                export_created=rec_dict["export_created"],
                export_script_sha256=rec_dict["export_script_sha256"],
                no_llm_replay_verified=rec_dict["no_llm_replay_verified"],
                faulty_evidence=RunSideEvidence(**rec_dict["faulty_evidence"]),
                repaired_evidence=RunSideEvidence(**rec_dict["repaired_evidence"]),
                metrics=AttemptMetrics(**rec_dict["metrics"]),
            )
            cp = rec.validate(self.manifest)
            recomputed = self._serialize_record(rec, cp, expected_prev)
            if obj["line_sha256"] != recomputed["line_sha256"] or obj["derived_pair"] != recomputed["derived_pair"]:
                raise ValueError(f"tampered ledger record or derived_pair at line {line_no}")
            key = (rec.experiment_id, rec.case_id, rec.condition_id, rec.repeat_index, rec.attempt_id)
            if key in seen_keys:
                raise ValueError(f"duplicate attempt key at line {line_no}: {key}")
            seen_keys.add(key)
            expected_prev = obj["line_sha256"]
            entries.append(obj)
        return entries
