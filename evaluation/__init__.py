"""ReproLoop evaluation, mathematical modeling, benchmarking, and formal verification package.

Scope: evaluation/** only. Zero network, model, browser, or Android device calls.
Reuses reviewed baseline validators from examples/{repro_oracle,replay_contracts,evaluation_metrics,meta_protocol}.py.
"""
from __future__ import annotations

from .splits import (
    PACKAGE_NAME,
    FAULT_FAMILY_ID,
    NATIVE_CANDIDATE_PRESET,
    NATIVE_INTERACTION_ACTIONS,
    NATIVE_EVENT_SEQUENCE,
    ScenarioSpec,
    SplitManifest,
    NativeScenario,
    NativeSplitManifest,
    deterministic_int_seed,
    build_frozen_splits,
    verify_split_integrity,
    get_scenario,
    build_frozen_splits_v2,
    verify_split_integrity_v2,
    get_native_scenario,
)
from .ledger import (
    VALID_STATUSES,
    VALID_EVIDENCE_MODES,
    TRUSTED_ORACLE_SOURCES,
    FORBIDDEN_ORACLE_SOURCES,
    AttemptMetrics,
    ExperimentAttemptRecord,
    ExperimentLedger,
    evaluate_pair_from_attempts,
    summarize_split_ledger,
)
from .improvement_loop import (
    OptimizationProposal,
    PairedComparisonResult,
    evaluate_improvement_step,
)
from .stats import (
    wilson_score_interval,
    clopper_pearson_interval,
    exact_paired_mcnemar,
    summarize_timings_ns,
)
from .complexity_bench import (
    theoretical_cua_tokens,
    theoretical_hierarchy_ops,
    amdahl_end_to_end_bound,
    run_microbenchmarks,
)
from .formal_model import (
    ProtocolState,
    ModelCheckResult,
    check_protocol_model,
    run_mutation_sensitivity_suite,
)

__all__ = [
    "PACKAGE_NAME",
    "FAULT_FAMILY_ID",
    "NATIVE_CANDIDATE_PRESET",
    "NATIVE_INTERACTION_ACTIONS",
    "NATIVE_EVENT_SEQUENCE",
    "ScenarioSpec",
    "SplitManifest",
    "NativeScenario",
    "NativeSplitManifest",
    "deterministic_int_seed",
    "build_frozen_splits",
    "verify_split_integrity",
    "get_scenario",
    "build_frozen_splits_v2",
    "verify_split_integrity_v2",
    "get_native_scenario",
    "VALID_STATUSES",
    "VALID_EVIDENCE_MODES",
    "TRUSTED_ORACLE_SOURCES",
    "FORBIDDEN_ORACLE_SOURCES",
    "AttemptMetrics",
    "ExperimentAttemptRecord",
    "ExperimentLedger",
    "evaluate_pair_from_attempts",
    "summarize_split_ledger",
    "OptimizationProposal",
    "PairedComparisonResult",
    "evaluate_improvement_step",
    "wilson_score_interval",
    "clopper_pearson_interval",
    "exact_paired_mcnemar",
    "summarize_timings_ns",
    "theoretical_cua_tokens",
    "theoretical_hierarchy_ops",
    "amdahl_end_to_end_bound",
    "run_microbenchmarks",
    "ProtocolState",
    "ModelCheckResult",
    "check_protocol_model",
    "run_mutation_sensitivity_suite",
]
