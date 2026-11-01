"""Developer self-improvement loop controller with strict split and regression gates.

This is a disciplined scientific comparison gate, NOT an automatic optimizer that
learns held-out test answers.

Enforces:
1. Tuning/iteration is restricted strictly to split == 'DEV'. Attempting iterative
   tuning on 'PILOT' or 'FINAL' raises PermissionError.
2. Same-workload pairing: baseline and candidate must cover the exact same
   (case_id, repeat_index) pairs for the split, with all planned repeats 1..R present
   (no best-of-N cherry-picking).
3. One explicit change and hypothesis per proposal.
4. Zero invalid pair confirmations (M3 == 0), zero fixed-control failure signals
   (M2 == 0), and zero regressions on previously passing DEV pairs before adopting a change.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Literal

from .ledger import ExperimentAttemptRecord, evaluate_pair_from_attempts
from .splits import SplitManifest, build_frozen_splits
from .stats import exact_paired_mcnemar

_EXAMPLES_DIR = str(Path(__file__).resolve().parents[1] / "examples")
if _EXAMPLES_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLES_DIR)

from repro_oracle import Verdict, valid_digest, valid_name  # noqa: E402


@dataclass(frozen=True)
class OptimizationProposal:
    proposal_id: str
    hypothesis: str
    changed_component_id: str
    base_version_sha256: str
    candidate_version_sha256: str
    target_split: Literal["DEV", "PILOT", "FINAL"] = "DEV"
    is_tuning_iteration: bool = True

    def validate(self) -> None:
        for label, val in (
            ("proposal_id", self.proposal_id),
            ("changed_component_id", self.changed_component_id),
        ):
            if not valid_name(val, 120):
                raise ValueError(f"invalid {label}: {val!r}")
        if not valid_name(self.hypothesis, 500):
            raise ValueError("hypothesis must be a non-empty stripped string <= 500 chars")
        if not valid_digest(self.base_version_sha256) or not valid_digest(self.candidate_version_sha256):
            raise ValueError("base and candidate version digests must be 64-char lowercase hex")
        if self.base_version_sha256 == self.candidate_version_sha256:
            raise ValueError("candidate_version_sha256 must differ from base_version_sha256")
        if type(self.is_tuning_iteration) is not bool:
            raise ValueError("is_tuning_iteration must be exact bool")
        if self.target_split not in ("DEV", "PILOT", "FINAL"):
            raise ValueError(f"invalid target_split: {self.target_split!r}")
        if self.is_tuning_iteration and self.target_split != "DEV":
            raise PermissionError(
                f"Iterative tuning is forbidden on frozen split {self.target_split!r}; "
                "tune only on 'DEV' and freeze versions before running PILOT/FINAL."
            )


@dataclass(frozen=True)
class PairedComparisonResult:
    proposal_id: str
    split: str
    total_pairs: int
    base_valid_pairs: int
    candidate_valid_pairs: int
    gained_pairs: tuple[tuple[str, int], ...]
    regressed_pairs: tuple[tuple[str, int], ...]
    candidate_fixed_signals: int
    candidate_invalid_confirmations: int
    mcnemar_exact_p_two_sided: float
    decision: Literal["ADOPT_CANDIDATE", "REJECT_REGRESSION", "REJECT_SAFETY_GATE", "HOLD_NO_GAIN"]
    reason: str


def evaluate_improvement_step(
    proposal: OptimizationProposal,
    base_records: list[ExperimentAttemptRecord],
    candidate_records: list[ExperimentAttemptRecord],
    *,
    expected_repeats: int = 1,
    manifest: SplitManifest | None = None,
) -> PairedComparisonResult:
    """Compare baseline vs. candidate records on matched (case_id, repeat_index) workloads."""
    if type(proposal) is not OptimizationProposal:
        raise ValueError("typed OptimizationProposal required")
    proposal.validate()
    if type(expected_repeats) is not int or not 1 <= expected_repeats <= 20:
        raise ValueError("expected_repeats must be int in 1..20")
    if not isinstance(base_records, list) or not isinstance(candidate_records, list):
        raise ValueError("base_records and candidate_records must be lists")

    m = build_frozen_splits() if manifest is None else manifest
    planned_cases = m.planned_case_ids(proposal.target_split)
    expected_keys = {(cid, r) for cid in planned_cases for r in range(1, expected_repeats + 1)}

    def index_records(records: list[ExperimentAttemptRecord], side_label: str) -> dict[tuple[str, int], tuple[ExperimentAttemptRecord, bool, bool, bool]]:
        indexed: dict[tuple[str, int], tuple[ExperimentAttemptRecord, bool, bool, bool]] = {}
        for rec in records:
            if type(rec) is not ExperimentAttemptRecord:
                raise ValueError(f"{side_label}: typed ExperimentAttemptRecord required")
            if rec.split != proposal.target_split:
                raise ValueError(f"{side_label}: record split {rec.split!r} != proposal split {proposal.target_split!r}")
            key = (rec.case_id, rec.repeat_index)
            if key in indexed:
                raise ValueError(f"{side_label}: duplicate (case_id, repeat_index)={key}")
            cp = evaluate_pair_from_attempts(rec, m)
            row = cp.row
            ev_valid = bool(
                row.export_created
                and row.faulty_complete
                and row.faulty_failure is True
                and row.fixed_complete
                and row.fixed_failure is False
                and row.pair_binding_valid
                and row.pair_verdict is Verdict.CONFIRMED
            )
            fixed_pos = bool(row.fixed_complete and row.fixed_failure is True)
            invalid_conf = bool(row.pair_verdict is Verdict.CONFIRMED and not ev_valid)
            indexed[key] = (rec, ev_valid, fixed_pos, invalid_conf)
        if set(indexed.keys()) != expected_keys:
            missing = sorted(expected_keys - set(indexed.keys()))
            extra = sorted(set(indexed.keys()) - expected_keys)
            raise ValueError(
                f"{side_label}: cherry-picked or incomplete workload keys (missing={missing}, extra={extra})"
            )
        return indexed

    base_map = index_records(base_records, "base")
    cand_map = index_records(candidate_records, "candidate")

    gained: list[tuple[str, int]] = []
    regressed: list[tuple[str, int]] = []
    base_valid = 0
    cand_valid = 0
    cand_fixed_signals = 0
    cand_invalid_confs = 0

    for key in sorted(expected_keys):
        b_rec, b_ok, _, _ = base_map[key]
        c_rec, c_ok, c_fpos, c_inv = cand_map[key]
        # Verify matched workload identity (same task, fixture, and APK builds)
        if (
            b_rec.task_sha256 != c_rec.task_sha256
            or b_rec.fixture_sha256 != c_rec.fixture_sha256
            or b_rec.faulty_build_sha256 != c_rec.faulty_build_sha256
            or b_rec.repaired_build_sha256 != c_rec.repaired_build_sha256
        ):
            raise ValueError(f"unmatched workload or build digests at {key}")

        base_valid += int(b_ok)
        cand_valid += int(c_ok)
        cand_fixed_signals += int(c_fpos)
        cand_invalid_confs += int(c_inv)
        if c_ok and not b_ok:
            gained.append(key)
        elif b_ok and not c_ok:
            regressed.append(key)

    mcnemar = exact_paired_mcnemar(len(regressed), len(gained))

    if cand_invalid_confs > 0 or cand_fixed_signals > 0:
        decision: Literal["ADOPT_CANDIDATE", "REJECT_REGRESSION", "REJECT_SAFETY_GATE", "HOLD_NO_GAIN"] = "REJECT_SAFETY_GATE"
        reason = (
            f"Candidate violated safety gate (invalid_confirmations={cand_invalid_confs}, "
            f"fixed_failure_signals={cand_fixed_signals})."
        )
    elif regressed:
        decision = "REJECT_REGRESSION"
        reason = f"Candidate regressed on {len(regressed)} previously passing pair(s): {regressed}."
    elif len(gained) > 0:
        decision = "ADOPT_CANDIDATE"
        reason = f"Candidate gained {len(gained)} valid pair(s) with 0 regressions and 0 safety violations."
    else:
        decision = "HOLD_NO_GAIN"
        reason = "Candidate showed 0 net pair gains over baseline on matched workload."

    return PairedComparisonResult(
        proposal_id=proposal.proposal_id,
        split=proposal.target_split,
        total_pairs=len(expected_keys),
        base_valid_pairs=base_valid,
        candidate_valid_pairs=cand_valid,
        gained_pairs=tuple(gained),
        regressed_pairs=tuple(regressed),
        candidate_fixed_signals=cand_fixed_signals,
        candidate_invalid_confirmations=cand_invalid_confs,
        mcnemar_exact_p_two_sided=mcnemar["exact_p_two_sided"],
        decision=decision,
        reason=reason,
    )
