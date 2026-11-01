"""Source-bound asymptotic complexity models and reproducible microbenchmarks.

Covers:
1. Hierarchy validation, click lifting, semantic resolution, and trace export
   (examples/replay_contracts.py): Time O(T * N), Space O(N + T) where N <= 128
   nodes per screen and T <= 24 steps per trace.
2. CUA conversation history scaling (examples/meta_protocol.py & docs/04):
   - Stateless full-history replay (store=False, resending prior pairs):
     Time/Token cost O(K^2 * (I_img + O_step)) across K turns (K <= 12 MVP cap,
     K <= 29 provider stateless cap).
   - Server-chained previous_response_id: uncached input O(K * I_img), cached prefix
     reads O(K^2 * (I_img + O_step)) at discounted cached rate ONLY when provider
     reports cached_tokens > 0.
3. End-to-End Amdahl / Network Dominance Bound and CPU Optimization Stop Criterion.
4. Reproducible seeded microbenchmarks across N in {1, 8, 32, 64, 128} (within
   contract) and N = 256 (explicitly labeled OUTSIDE_CONTRACT_STRESS_TEST).
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
import platform
from pathlib import Path
import sys
import time
import tracemalloc

from .stats import summarize_timings_ns

_EXAMPLES_DIR = str(Path(__file__).resolve().parents[1] / "examples")
if _EXAMPLES_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLES_DIR)

import evaluation_metrics as em  # noqa: E402
import meta_protocol as mp  # noqa: E402
import replay_contracts as rc  # noqa: E402
import repro_oracle as ro  # noqa: E402


def _h(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def theoretical_hierarchy_ops(num_nodes: int, num_steps: int) -> dict:
    """Exact operation counts for validate_capture, lift_click, resolve, and export_trace."""
    if type(num_nodes) is not int or num_nodes < 1 or type(num_steps) is not int or num_steps < 1:
        raise ValueError("num_nodes and num_steps must be positive ints")
    within_contract = (1 <= num_nodes <= 128 and 1 <= num_steps <= 24)
    # In export_trace(trace):
    # Each step calls validate_capture (scans N nodes) + lift_click:
    #   lift_click calls validate_capture (N) + hit scan (N) + resolve:
    #     resolve calls validate_capture (N) + semantic match scan (N)
    # Total node inspections per step in export_trace = 5 * N.
    node_scans_per_step = 5 * num_nodes
    total_node_scans = num_steps * node_scans_per_step
    return {
        "num_nodes_N": num_nodes,
        "num_steps_T": num_steps,
        "within_product_contract": within_contract,
        "contract_bounds": {"max_nodes_N": 128, "max_steps_T": 24},
        "time_complexity_symbolic": "O(T * N)",
        "space_complexity_symbolic": "O(N + T)",
        "exact_node_inspections_in_export_trace": total_node_scans,
        "exact_node_inspections_in_single_resolve": 2 * num_nodes,
    }


def theoretical_cua_tokens(
    steps_k: int,
    *,
    system_tokens: int = 400,
    screenshot_tokens: int = 1400,
    output_tokens_per_step: int = 350,
    cached_prefix_hit: bool = False,
) -> dict:
    """Compare O(K^2) stateless replay token accumulation vs server-chained caching."""
    for val in (steps_k, system_tokens, screenshot_tokens, output_tokens_per_step):
        if type(val) is not int or val < 1:
            raise ValueError("token model parameters must be positive ints")
    if type(cached_prefix_hit) is not bool:
        raise ValueError("cached_prefix_hit must be exact bool")

    # Turn k (1-indexed, k=1..K) in full history replay contains:
    # system_tokens + k * screenshot_tokens + (k - 1) * output_tokens_per_step
    stateless_uncached_input = (
        steps_k * system_tokens
        + (steps_k * (steps_k + 1) // 2) * screenshot_tokens
        + (steps_k * (steps_k - 1) // 2) * output_tokens_per_step
    )
    total_output = steps_k * output_tokens_per_step
    stateless_cost_usd = mp.estimate_usd(stateless_uncached_input, 0, total_output)

    # If prior turns (k-1) are served from cache (only valid when provider reports cached_tokens):
    cached_tokens = (
        (steps_k - 1) * system_tokens
        + (steps_k * (steps_k - 1) // 2) * (screenshot_tokens + output_tokens_per_step)
        if cached_prefix_hit
        else 0
    )
    chained_cost_usd = mp.estimate_usd(stateless_uncached_input, cached_tokens, total_output)

    return {
        "steps_K": steps_k,
        "within_mvp_cap_12": steps_k <= 12,
        "within_provider_stateless_cap_29": steps_k <= 29,
        "assumptions": {
            "system_tokens": system_tokens,
            "screenshot_tokens": screenshot_tokens,
            "output_tokens_per_step": output_tokens_per_step,
            "cached_prefix_hit": cached_prefix_hit,
            "note": (
                "Screenshot and prompt token counts must be recorded from actual provider usage "
                "fields on live responses, never estimated from PNG byte length."
            ),
        },
        "client_network_request_payload_scaling": (
            "O(K) across K turns when chaining previous_response_id (sending 1 new screenshot per turn) "
            "vs. Theta(K^2) when re-sending full stateless history."
        ),
        "total_billed_context_tokens_scaling": (
            "Theta(K^2 * (I_img + O_step)) total processed context across K turns without truncation "
            "under both stateless replay and server-chained history (cached_prefix_hit discounts the "
            "per-token rate on prior turns from $1.25/1M to $0.15/1M only when reported by provider, "
            "without reducing total context token volume)."
        ),
        "asymptotic_input_tokens_stateless": "Theta(K^2 * (I_img + O_step))",
        "total_input_tokens": stateless_uncached_input,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": stateless_uncached_input - cached_tokens,
        "total_output_tokens": total_output,
        "stateless_uncached_cost_usd": str(stateless_cost_usd),
        "effective_cost_usd": str(chained_cost_usd),
    }


def amdahl_end_to_end_bound(
    local_cpu_ms: float,
    external_io_and_api_ms: float = 3500.0,
    local_speedup_factor: float = 100.0,
    *,
    external_is_measured: bool = False,
) -> dict:
    """Compute Amdahl's Law upper bound on end-to-end speedup from local Python optimization.

    Explicitly distinguishes MEASURED local CPU time from ASSUMED/UNMEASURED external I/O + API time.
    """
    for v in (local_cpu_ms, external_io_and_api_ms, local_speedup_factor):
        if type(v) not in (int, float) or v <= 0:
            raise ValueError("all inputs must be positive numbers")
    if type(external_is_measured) is not bool:
        raise ValueError("external_is_measured must be exact bool")
    total_ms = local_cpu_ms + external_io_and_api_ms
    cpu_fraction = local_cpu_ms / total_ms
    new_total_ms = (local_cpu_ms / local_speedup_factor) + external_io_and_api_ms
    e2e_speedup = total_ms / new_total_ms
    pct_wall_saved = (1.0 - (new_total_ms / total_ms)) * 100.0
    return {
        "local_cpu_ms": round(local_cpu_ms, 4),
        "local_cpu_basis": "MEASURED_HOST_CPU_MICROBENCHMARK",
        "external_io_and_api_ms": round(external_io_and_api_ms, 4),
        "external_io_and_api_basis": (
            "MEASURED_MATCHED_END_TO_END_RUNS"
            if external_is_measured
            else "ILLUSTRATIVE_ASSUMPTION_ONLY_UNMEASURED_IN_EVAL_WORKTREE"
        ),
        "local_cpu_fraction": round(cpu_fraction, 6),
        "hypothetical_local_speedup": local_speedup_factor,
        "max_end_to_end_speedup_ratio": round(e2e_speedup, 6),
        "max_wall_time_reduction_pct": round(pct_wall_saved, 4),
        "stop_local_cpu_optimization": cpu_fraction < 0.01,
        "decision_status": (
            "EMPIRICALLY_ESTABLISHED_STOP"
            if external_is_measured and cpu_fraction < 0.01
            else "CONDITIONAL_STOP_UNDER_ASSUMED_EXTERNAL_LATENCY_AWAITING_MATCHED_E2E_RUNS"
        ),
        "stop_reason": (
            "Under the illustrative external I/O + API latency assumption, local Python CPU is <1% "
            "of step latency; actual end-to-end dominance remains to be confirmed on matched live pilot runs."
            if not external_is_measured and cpu_fraction < 0.01
            else (
                "Local Python CPU is <1% of measured end-to-end step latency; network inference and ADB capture dominate."
                if cpu_fraction < 0.01
                else "Local CPU >=1% of step latency; inspect hotspot."
            )
        ),
    }


def _build_seeded_hierarchy(num_nodes: int, epoch: int = 1) -> tuple[rc.PreActionFrame, tuple[rc.Node, ...]]:
    frame = rc.PreActionFrame(
        run_id="bench-run",
        serial="emulator-5554",
        boot_id="boot-bench-1",
        package="com.tinyburn.reproloop.lab",
        build_sha256=_h("faulty-build-v1"),
        generation=1,
        capture_epoch=epoch,
        frame_sha256=_h(f"frame-{num_nodes}-{epoch}"),
        width=1080,
        height=1920,
        expected_screen="editor_dialog",
    )
    nodes: list[rc.Node] = []
    for idx in range(num_nodes):
        row = idx // 8
        col = idx % 8
        left = 10 + col * 120
        top = 10 + row * 50
        nodes.append(
            rc.Node(
                node_key=f"node_{idx}",
                resource_id=f"com.tinyburn.reproloop.lab:id/btn_{idx}",
                text=f"Action {idx}",
                clickable=True,
                bounds=(left, top, left + 100, top + 40),
            )
        )
    return frame, tuple(nodes)


def run_microbenchmarks(*, warmup: int = 15, repeats: int = 120) -> dict:
    """Run reproducible seeded microbenchmarks on existing reference modules."""
    if type(warmup) is not int or warmup < 1 or type(repeats) is not int or repeats < 10:
        raise ValueError("warmup >= 1 and repeats >= 10 required")

    examples_root = Path(_EXAMPLES_DIR)
    module_hashes = {
        name: sha256((examples_root / name).read_bytes()).hexdigest()
        for name in ("evaluation_metrics.py", "meta_protocol.py", "replay_contracts.py", "repro_oracle.py")
    }

    hierarchy_Wait_results: list[dict] = []
    for n in (1, 8, 32, 64, 128):
        frame, nodes = _build_seeded_hierarchy(n, epoch=1)
        hierarchy = rc.Hierarchy(frame=frame, hierarchy_sha256=_h(f"tree-{n}"), nodes=nodes)
        target_node = nodes[-1]
        tx = (target_node.bounds[0] + target_node.bounds[2]) // 2
        ty = (target_node.bounds[1] + target_node.bounds[3]) // 2
        click = rc.TraceClick(frame=frame, hierarchy=hierarchy, x=tx, y=ty)
        locator = rc.Locator(target_node.resource_id, target_node.text, frame.expected_screen)

        for _ in range(warmup):
            rc.lift_click(click, frame)
            rc.resolve(locator, frame, hierarchy, frame)

        tracemalloc.start()
        lift_samples: list[int] = []
        resolve_samples: list[int] = []
        cpu_start = time.process_time_ns()
        for _ in range(repeats):
            t0 = time.perf_counter_ns()
            rc.lift_click(click, frame)
            t1 = time.perf_counter_ns()
            rc.resolve(locator, frame, hierarchy, frame)
            t2 = time.perf_counter_ns()
            lift_samples.append(t1 - t0)
            resolve_samples.append(t2 - t1)
        cpu_elapsed = time.process_time_ns() - cpu_start
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        hierarchy_Wait_results.append({
            "num_nodes_N": n,
            "scope_label": "WITHIN_PRODUCT_CONTRACT_N_LE_128",
            "lift_click_ns": summarize_timings_ns(lift_samples),
            "resolve_ns": summarize_timings_ns(resolve_samples),
            "mean_cpu_ns_per_iter": round(cpu_elapsed / repeats, 2),
            "tracemalloc_peak_bytes": peak_bytes,
            "theoretical_ops": theoretical_hierarchy_ops(n, 3),
        })

    # Out-of-contract N=256 check: verify validate_capture fails closed in O(1) header check
    # and measure raw linear scan cost separately labeled OUTSIDE_CONTRACT_STRESS_TEST
    frame_256, nodes_256 = _build_seeded_hierarchy(256, epoch=1)
    h_256 = rc.Hierarchy(frame=frame_256, hierarchy_sha256=_h("tree-256"), nodes=nodes_256)
    reject_samples: list[int] = []
    for _ in range(repeats):
        t0 = time.perf_counter_ns()
        try:
            rc.validate_capture(frame_256, h_256, frame_256)
            raise AssertionError("validate_capture must reject N=256 > 128")
        except ValueError:
            pass
        reject_samples.append(time.perf_counter_ns() - t0)

    # Benchmark 3-step vs 24-step export_trace at N=64
    trace_results: list[dict] = []
    for steps_t in (3, 24):
        trace_items: list[rc.TraceClick] = []
        for ep in range(1, steps_t + 1):
            f_ep, nodes_ep = _build_seeded_hierarchy(64, epoch=ep)
            h_ep = rc.Hierarchy(frame=f_ep, hierarchy_sha256=_h(f"h-64-{ep}"), nodes=nodes_ep)
            tn = nodes_ep[ep % 64]
            cx = (tn.bounds[0] + tn.bounds[2]) // 2
            cy = (tn.bounds[1] + tn.bounds[3]) // 2
            trace_items.append(rc.TraceClick(frame=f_ep, hierarchy=h_ep, x=cx, y=cy))
        trace_tuple = tuple(trace_items)
        task_d = _h("bench-task")
        fix_d = _h("bench-fix")

        for _ in range(warmup):
            rc.export_trace(trace_tuple, task_d, fix_d)

        tracemalloc.start()
        exp_samples: list[int] = []
        for _ in range(repeats):
            t0 = time.perf_counter_ns()
            rc.export_trace(trace_tuple, task_d, fix_d)
            exp_samples.append(time.perf_counter_ns() - t0)
        _, peak_b = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        trace_results.append({
            "num_nodes_N": 64,
            "num_steps_T": steps_t,
            "export_trace_ns": summarize_timings_ns(exp_samples),
            "tracemalloc_peak_bytes": peak_b,
            "theoretical_ops": theoretical_hierarchy_ops(64, steps_t),
        })

    # Benchmark judge_release + collect_pair + summarize (5 scenarios)
    spec = ro.CaseSpec("P01", _h("t"), _h("f"), _h("bad"), _h("good"), "cancel_preserves_stored_title")
    bad = ro.OracleRun("r1", "P01", _h("t"), _h("f"), _h("bad"), "cancel_preserves_stored_title", _h("l1"), True, True, True, True, 1, False)
    good = replace(bad, run_id="r2", build_sha256=_h("good"), oracle_log_sha256=_h("l2"), failure_observed=False)
    oracle_samples: list[int] = []
    for _ in range(repeats):
        t0 = time.perf_counter_ns()
        cp = rc.collect_pair(spec, bad, good, 1, export_created=True, pair_binding_valid=True)
        em.summarize([cp.row], ["P01"])
        oracle_samples.append(time.perf_counter_ns() - t0)

    median_3step_ms = trace_results[0]["export_trace_ns"]["p50_median_ns"] / 1_000_000.0
    amdahl = amdahl_end_to_end_bound(
        local_cpu_ms=max(0.001, median_3step_ms),
        external_io_and_api_ms=3500.0,
        external_is_measured=False,
    )

    return {
        "benchmark_metadata": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "warmup_iterations": warmup,
            "measured_repeats": repeats,
            "reference_module_sha256": module_hashes,
            "evidence_mode": "HOST_CPU_MICROBENCHMARK_ONLY",
            "limits": (
                "Measures local Python reference validation/lifting/export CPU and heap only. "
                "Does NOT measure Android ADB latency, Meta Model API latency, or UX speed."
            ),
        },
        "hierarchy_scaling_within_contract": hierarchy_Wait_results,
        "out_of_contract_N256_rejection_ns": {
            "num_nodes_N": 256,
            "scope_label": "OUTSIDE_CONTRACT_STRESS_TEST_REJECTED_BY_VALIDATOR",
            "rejection_latency_ns": summarize_timings_ns(reject_samples),
        },
        "trace_export_scaling": trace_results,
        "oracle_collect_and_summarize_ns": summarize_timings_ns(oracle_samples),
        "cua_token_scaling_models": {
            "3_steps_stateless": theoretical_cua_tokens(3, cached_prefix_hit=False),
            "12_steps_mvp_cap_stateless": theoretical_cua_tokens(12, cached_prefix_hit=False),
            "12_steps_mvp_cap_cached_prefix": theoretical_cua_tokens(12, cached_prefix_hit=True),
            "29_steps_provider_cap_stateless": theoretical_cua_tokens(29, cached_prefix_hit=False),
        },
        "amdahl_end_to_end_dominance": amdahl,
    }
