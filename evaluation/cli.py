"""CLI runner to generate frozen split manifests, synthetic ledger runs, benchmarks, and formal checks.

Usage:
    python3 -m evaluation.cli --output-dir docs/evaluation/artifacts
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .complexity_bench import run_microbenchmarks
from .formal_model import run_mutation_sensitivity_suite
from .improvement_loop import OptimizationProposal, evaluate_improvement_step
from .ledger import (
    AttemptMetrics,
    ExperimentAttemptRecord,
    ExperimentLedger,
    RunSideEvidence,
    summarize_split_ledger,
)
from .splits import NativeSplitManifest, SplitManifest, build_frozen_splits, build_frozen_splits_v2
from .stats import clopper_pearson_interval, exact_paired_mcnemar, wilson_score_interval


def _h(s: str) -> str:
    return sha256(s.encode("utf-8")).hexdigest()


def build_synthetic_pilot_and_dev_records(manifest: SplitManifest | NativeSplitManifest) -> list[ExperimentAttemptRecord]:
    """Generate deterministic SYNTHETIC experiment records to validate the evaluation pipeline.

    Explicitly labeled evidence_mode='SYNTHETIC' and actual_live_pilot_runs=0.
    """
    commit_sha = _h("commit-269b0c45eed1643f8a3913e2c196f0debfa1f918")
    faulty_apk = _h("com.tinyburn.reproloop.lab-faulty-debug-v1.apk")
    repaired_apk = _h("com.tinyburn.reproloop.lab-repaired-debug-v1.apk")
    prompt_v1 = _h("prompt-v1-base")
    prompt_v2 = _h("prompt-v2-reground-after-navigation")
    v_of = lambda s: s.layout_variant if hasattr(s, "layout_variant") else s.variant

    records: list[ExperimentAttemptRecord] = []

    # 1. DEV split: base version (DEV-01 passes, DEV-02 fails to export) vs candidate version (both pass)
    for idx, scen in enumerate(manifest.by_split("DEV"), 1):
        # Base condition on DEV
        base_pass = (idx == 1)
        records.append(
            ExperimentAttemptRecord(
                experiment_id="exp-synthetic-dev-base-v1",
                attempt_id=f"att-dev-base-{scen.case_id}",
                case_id=scen.case_id,
                split="DEV",
                variant=v_of(scen),
                condition_id="B3_spark_cua_base_v1",
                repeat_index=1,
                status="complete" if base_pass else "attempted",
                reason_code="OK_CONFIRMED" if base_pass else "EXPORT_LOCATOR_AMBIGUOUS",
                evidence_mode="SYNTHETIC",
                source_commit_sha256=commit_sha,
                model_id="muse-spark-1.3",
                prompt_version_sha256=prompt_v1,
                exporter_version="tap-buttons-v1",
                media_sha256=_h(f"media-{scen.case_id}"),
                task_sha256=scen.task_sha256,
                fixture_sha256=scen.fixture_sha256,
                faulty_build_sha256=faulty_apk,
                repaired_build_sha256=repaired_apk,
                generation=1,
                export_created=base_pass,
                export_script_sha256=_h(f"export-{scen.case_id}-v1") if base_pass else None,
                no_llm_replay_verified=base_pass,
                faulty_evidence=RunSideEvidence(
                    run_id=f"run-faulty-base-{scen.case_id}",
                    build_sha256=faulty_apk,
                    reset_receipt_sha256=_h(f"reset-f-base-{scen.case_id}"),
                    oracle_log_sha256=_h(f"log-f-base-{scen.case_id}"),
                    trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                    completed=True,
                    preconditions_verified=True,
                    goal_reached=True,
                    failure_observed=True,
                    visual_match=True,
                ),
                repaired_evidence=RunSideEvidence(
                    run_id=f"run-repaired-base-{scen.case_id}" if base_pass else None,
                    build_sha256=repaired_apk,
                    reset_receipt_sha256=_h(f"reset-r-base-{scen.case_id}") if base_pass else None,
                    oracle_log_sha256=_h(f"log-r-base-{scen.case_id}") if base_pass else None,
                    trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS" if base_pass else "NONE_NOT_RUN",
                    completed=base_pass,
                    preconditions_verified=base_pass,
                    goal_reached=base_pass,
                    failure_observed=False if base_pass else None,
                    visual_match=False,
                ),
                metrics=AttemptMetrics(),  # All token/cost/latency fields explicitly "UNKNOWN" in synthetic mode
            )
        )
        # Candidate condition on DEV (both DEV-01 and DEV-02 pass)
        records.append(
            ExperimentAttemptRecord(
                experiment_id="exp-synthetic-dev-cand-v2",
                attempt_id=f"att-dev-cand-{scen.case_id}",
                case_id=scen.case_id,
                split="DEV",
                variant=v_of(scen),
                condition_id="B3_spark_cua_cand_v2",
                repeat_index=1,
                status="complete",
                reason_code="OK_CONFIRMED",
                evidence_mode="SYNTHETIC",
                source_commit_sha256=commit_sha,
                model_id="muse-spark-1.3",
                prompt_version_sha256=prompt_v2,
                exporter_version="tap-buttons-v1",
                media_sha256=_h(f"media-{scen.case_id}"),
                task_sha256=scen.task_sha256,
                fixture_sha256=scen.fixture_sha256,
                faulty_build_sha256=faulty_apk,
                repaired_build_sha256=repaired_apk,
                generation=1,
                export_created=True,
                export_script_sha256=_h(f"export-{scen.case_id}-v2"),
                no_llm_replay_verified=True,
                faulty_evidence=RunSideEvidence(
                    run_id=f"run-faulty-cand-{scen.case_id}",
                    build_sha256=faulty_apk,
                    reset_receipt_sha256=_h(f"reset-f-cand-{scen.case_id}"),
                    oracle_log_sha256=_h(f"log-f-cand-{scen.case_id}"),
                    trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                    completed=True,
                    preconditions_verified=True,
                    goal_reached=True,
                    failure_observed=True,
                    visual_match=True,
                ),
                repaired_evidence=RunSideEvidence(
                    run_id=f"run-repaired-cand-{scen.case_id}",
                    build_sha256=repaired_apk,
                    reset_receipt_sha256=_h(f"reset-r-cand-{scen.case_id}"),
                    oracle_log_sha256=_h(f"log-r-cand-{scen.case_id}"),
                    trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                    completed=True,
                    preconditions_verified=True,
                    goal_reached=True,
                    failure_observed=False,
                    visual_match=False,
                ),
                metrics=AttemptMetrics(),
            )
        )

    # 2. PILOT split synthetic worked scenario (matching docs/04 5-row worked example:
    # P01..P03 CONFIRMED, P04 missing export, P05 incomplete fixed control -> M1=3/5, M2=0/3+2 unknown, M3=0/5)
    for scen in manifest.by_split("PILOT"):
        if scen.case_id in ("P01", "P02", "P03"):
            records.append(
                ExperimentAttemptRecord(
                    experiment_id="exp-synthetic-pilot-worked",
                    attempt_id=f"att-pilot-{scen.case_id}",
                    case_id=scen.case_id,
                    split="PILOT",
                    variant=v_of(scen),
                    condition_id="B3_spark_cua_synthetic_worked",
                    repeat_index=1,
                    status="complete",
                    reason_code="OK_CONFIRMED",
                    evidence_mode="SYNTHETIC",
                    source_commit_sha256=commit_sha,
                    model_id="muse-spark-1.3",
                    prompt_version_sha256=prompt_v2,
                    exporter_version="tap-buttons-v1",
                    media_sha256=_h(f"media-{scen.case_id}"),
                    task_sha256=scen.task_sha256,
                    fixture_sha256=scen.fixture_sha256,
                    faulty_build_sha256=faulty_apk,
                    repaired_build_sha256=repaired_apk,
                    generation=1,
                    export_created=True,
                    export_script_sha256=_h(f"export-{scen.case_id}"),
                    no_llm_replay_verified=True,
                    faulty_evidence=RunSideEvidence(
                        run_id=f"run-faulty-{scen.case_id}",
                        build_sha256=faulty_apk,
                        reset_receipt_sha256=_h(f"reset-f-{scen.case_id}"),
                        oracle_log_sha256=_h(f"log-f-{scen.case_id}"),
                        trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                        completed=True,
                        preconditions_verified=True,
                        goal_reached=True,
                        failure_observed=True,
                        visual_match=True,
                    ),
                    repaired_evidence=RunSideEvidence(
                        run_id=f"run-repaired-{scen.case_id}",
                        build_sha256=repaired_apk,
                        reset_receipt_sha256=_h(f"reset-r-{scen.case_id}"),
                        oracle_log_sha256=_h(f"log-r-{scen.case_id}"),
                        trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                        completed=True,
                        preconditions_verified=True,
                        goal_reached=True,
                        failure_observed=False,
                        visual_match=False,
                    ),
                    metrics=AttemptMetrics(),
                )
            )
        elif scen.case_id == "P04":
            # Missing export / control not run
            records.append(
                ExperimentAttemptRecord(
                    experiment_id="exp-synthetic-pilot-worked",
                    attempt_id="att-pilot-P04",
                    case_id="P04",
                    split="PILOT",
                    variant=v_of(scen),
                    condition_id="B3_spark_cua_synthetic_worked",
                    repeat_index=1,
                    status="unknown",
                    reason_code="EXPORT_NOT_CREATED",
                    evidence_mode="SYNTHETIC",
                    source_commit_sha256=commit_sha,
                    model_id="muse-spark-1.3",
                    prompt_version_sha256=prompt_v2,
                    exporter_version="tap-buttons-v1",
                    media_sha256=_h("media-P04"),
                    task_sha256=scen.task_sha256,
                    fixture_sha256=scen.fixture_sha256,
                    faulty_build_sha256=faulty_apk,
                    repaired_build_sha256=repaired_apk,
                    generation=1,
                    export_created=False,
                    export_script_sha256=None,
                    no_llm_replay_verified=False,
                    faulty_evidence=RunSideEvidence(
                        run_id=None,
                        build_sha256=faulty_apk,
                        reset_receipt_sha256=None,
                        oracle_log_sha256=None,
                        trusted_oracle_source="NONE_NOT_RUN",
                        completed=False,
                        preconditions_verified=False,
                        goal_reached=False,
                        failure_observed=None,
                        visual_match=False,
                    ),
                    repaired_evidence=RunSideEvidence(
                        run_id=None,
                        build_sha256=repaired_apk,
                        reset_receipt_sha256=None,
                        oracle_log_sha256=None,
                        trusted_oracle_source="NONE_NOT_RUN",
                        completed=False,
                        preconditions_verified=False,
                        goal_reached=False,
                        failure_observed=None,
                        visual_match=False,
                    ),
                    metrics=AttemptMetrics(),
                )
            )
        elif scen.case_id == "P05":
            # Faulty positive, but fixed control incomplete
            records.append(
                ExperimentAttemptRecord(
                    experiment_id="exp-synthetic-pilot-worked",
                    attempt_id="att-pilot-P05",
                    case_id="P05",
                    split="PILOT",
                    variant=v_of(scen),
                    condition_id="B3_spark_cua_synthetic_worked",
                    repeat_index=1,
                    status="unknown",
                    reason_code="FIXED_CONTROL_INCOMPLETE",
                    evidence_mode="SYNTHETIC",
                    source_commit_sha256=commit_sha,
                    model_id="muse-spark-1.3",
                    prompt_version_sha256=prompt_v2,
                    exporter_version="tap-buttons-v1",
                    media_sha256=_h("media-P05"),
                    task_sha256=scen.task_sha256,
                    fixture_sha256=scen.fixture_sha256,
                    faulty_build_sha256=faulty_apk,
                    repaired_build_sha256=repaired_apk,
                    generation=1,
                    export_created=True,
                    export_script_sha256=_h("export-P05"),
                    no_llm_replay_verified=False,
                    faulty_evidence=RunSideEvidence(
                        run_id="run-faulty-P05",
                        build_sha256=faulty_apk,
                        reset_receipt_sha256=_h("reset-f-P05"),
                        oracle_log_sha256=_h("log-f-P05"),
                        trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                        completed=True,
                        preconditions_verified=True,
                        goal_reached=True,
                        failure_observed=True,
                        visual_match=True,
                    ),
                    repaired_evidence=RunSideEvidence(
                        run_id="run-repaired-P05",
                        build_sha256=repaired_apk,
                        reset_receipt_sha256=_h("reset-r-P05"),
                        oracle_log_sha256=_h("log-r-P05"),
                        trusted_oracle_source="SYNTHETIC_FIXTURE_HARNESS",
                        completed=False,
                        preconditions_verified=True,
                        goal_reached=False,
                        failure_observed=None,
                        visual_match=False,
                    ),
                    metrics=AttemptMetrics(),
                )
            )

    return records


def run_all_and_save(output_dir: str | Path, *, preserve_existing_v1: bool = True) -> dict:
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1a. Historical v1 splits manifest (preserved untouched if preserve_existing_v1=True and file exists)
    manifest_v1 = build_frozen_splits()
    splits_v1_path = out_root / "frozen-splits-v1.json"
    if not (preserve_existing_v1 and splits_v1_path.exists()):
        splits_v1_path.write_text(json.dumps(manifest_v1.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ledger_v1_path = out_root / "synthetic-experiment-ledger.jsonl"
    if not (preserve_existing_v1 and ledger_v1_path.exists()):
        if ledger_v1_path.exists():
            ledger_v1_path.unlink()
        ledger_v1 = ExperimentLedger(ledger_v1_path, manifest=manifest_v1)
        for rec in build_synthetic_pilot_and_dev_records(manifest_v1):
            ledger_v1.append(rec)

    # 1b. Live v2 splits manifest aligned byte-for-byte with runtime.app_state.FixtureSpec
    manifest_v2 = build_frozen_splits_v2()
    splits_v2_path = out_root / "frozen-splits-live-v2.json"
    splits_v2_path.write_text(json.dumps(manifest_v2.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 2. Synthetic JSONL ledger & split summaries under v2 native contract
    ledger_v2_path = out_root / "synthetic-experiment-ledger-v2.jsonl"
    if ledger_v2_path.exists():
        ledger_v2_path.unlink()
    ledger_v2 = ExperimentLedger(ledger_v2_path, manifest=manifest_v2)
    records = build_synthetic_pilot_and_dev_records(manifest_v2)
    for rec in records:
        ledger_v2.append(rec)
    verified_entries = ledger_v2.read_and_verify()

    dev_base_summary = summarize_split_ledger(records, split="DEV", condition_id="B3_spark_cua_base_v1", manifest=manifest_v2)
    dev_cand_summary = summarize_split_ledger(records, split="DEV", condition_id="B3_spark_cua_cand_v2", manifest=manifest_v2)
    pilot_summary = summarize_split_ledger(records, split="PILOT", condition_id="B3_spark_cua_synthetic_worked", manifest=manifest_v2)

    # 3. Developer improvement loop check on DEV (using v1 manifest for backward-compat + v2 check)
    proposal = OptimizationProposal(
        proposal_id="prop-dev-001",
        hypothesis="Re-grounding after screen transition resolves Variant A secondary seed without regressions.",
        changed_component_id="planner_screen_transition_prompt",
        base_version_sha256=_h("prompt-v1-base"),
        candidate_version_sha256=_h("prompt-v2-reground-after-navigation"),
        target_split="DEV",
        is_tuning_iteration=True,
    )
    v1_records = build_synthetic_pilot_and_dev_records(manifest_v1)
    dev_base_recs = [r for r in v1_records if r.split == "DEV" and r.condition_id == "B3_spark_cua_base_v1"]
    dev_cand_recs = [r for r in v1_records if r.split == "DEV" and r.condition_id == "B3_spark_cua_cand_v2"]
    improvement_res = evaluate_improvement_step(proposal, dev_base_recs, dev_cand_recs, manifest=manifest_v1)

    # 4. Benchmarks & asymptotic models
    bench_report = run_microbenchmarks(warmup=15, repeats=120)

    # 5. Formal state-space & mutation sensitivity suite
    formal_report = run_mutation_sensitivity_suite()

    # 6. Small-sample statistical reference table (illustrative conditional models only)
    stats_reference = {
        "model_warning": (
            "Illustrative conditional binomial / sign-test calculations only. Independence and "
            "identical success probability (common p) are NOT established across the 5 fixed "
            "correlated scenarios (2 Variant A, 2 Variant B, 1 Variant C) of single fault family F01."
        ),
        "pilot_n5_wilson_intervals": {f"{k}_of_5": wilson_score_interval(k, 5) for k in range(6)},
        "pilot_n5_clopper_pearson_intervals": {f"{k}_of_5": clopper_pearson_interval(k, 5) for k in range(6)},
        "paired_mcnemar_examples": {
            "0_vs_3_gains": exact_paired_mcnemar(0, 3),
            "0_vs_5_gains": exact_paired_mcnemar(0, 5),
            "0_vs_6_gains_min_for_p_lt_0_05": exact_paired_mcnemar(0, 6),
        },
    }

    combined = {
        "evidence_status": "SYNTHETIC_AND_HOST_CPU_BENCHMARK_ONLY",
        "actual_live_android_runs": 0,
        "actual_live_meta_api_calls": 0,
        "historical_v1_splits_manifest_sha256": manifest_v1.manifest_sha256,
        "splits_manifest_sha256": manifest_v2.manifest_sha256,
        "ledger_entries_verified": len(verified_entries),
        "ledger_tail_sha256": verified_entries[-1]["line_sha256"],
        "summaries": {
            "dev_base": dev_base_summary,
            "dev_candidate": dev_cand_summary,
            "pilot_synthetic_worked": pilot_summary,
        },
        "dev_improvement_gate": {
            "proposal_id": improvement_res.proposal_id,
            "decision": improvement_res.decision,
            "base_valid_pairs": improvement_res.base_valid_pairs,
            "candidate_valid_pairs": improvement_res.candidate_valid_pairs,
            "gained_pairs": [list(x) for x in improvement_res.gained_pairs],
            "regressed_pairs": [list(x) for x in improvement_res.regressed_pairs],
            "mcnemar_exact_p_two_sided": improvement_res.mcnemar_exact_p_two_sided,
            "reason": improvement_res.reason,
        },
        "complexity_and_microbenchmarks": bench_report,
        "formal_verification": formal_report,
        "statistical_reference": stats_reference,
    }

    summary_v1_path = out_root / "evaluation-quantitative-report.json"
    if not (preserve_existing_v1 and summary_v1_path.exists()):
        summary_v1_path.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_v2_path = out_root / "evaluation-quantitative-report-v2.json"
    summary_v2_path.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ReproLoop evaluation, benchmark, and formal verification suite.")
    parser.add_argument(
        "--output-dir",
        default="docs/evaluation/artifacts",
        help="Directory to write JSON/JSONL evaluation artifacts.",
    )
    args = parser.parse_args()
    res = run_all_and_save(args.output_dir)
    print(
        json.dumps(
            {
                "status": "OK",
                "evidence_status": res["evidence_status"],
                "splits_manifest_sha256": res["splits_manifest_sha256"],
                "ledger_entries_verified": res["ledger_entries_verified"],
                "ledger_tail_sha256": res["ledger_tail_sha256"],
                "formal_nominal_states": res["formal_verification"]["nominal_result"]["reachable_states"],
                "formal_all_mutations_killed": res["formal_verification"]["all_mutations_killed"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
