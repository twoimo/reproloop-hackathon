"""Bounded finite-state model checker and mutation-sensitivity suite for ReproLoop.

Maps directly to:
1. Offline evaluation/oracle reference:
   - `examples/repro_oracle.py` (`36e6471e5a0b804d3a82872ba8a953d6f12cdd309630752551d99c06bd8cf73c`)
   - `examples/replay_contracts.py` (`49b940f6ddadda9f2b95cfce5e89fd947714ac04290972240e27683ce6e0d21c`)
2. Repaired Runtime commit `354b845d723a05e5e091b07d8b1723929a82df77` (cherry-picked to main `047e8e8`),
   contrasted against superseded defective commit `782783d` (`a99b1c9`):
   - `src/reproloop/runtime/driver.py` (`354b845d` SHA-256 `727994c33a66078239d1487b6e1f64a08dc4b4247729bc66b7b872ff4cb3acf1`
     vs. `782783d` SHA-256 `0749834fef1e9f33e4b65bfa0c378ff6d3e410691995c8c772011d58f165704c`)
   - `src/reproloop/runtime/owned.py` (`354b845d` SHA-256 `ed37dcd8be3eaac120f7ad7fbb5a8defe7d67395048ee63d284f2be2dd809001`
     vs. `782783d` SHA-256 `bd7514e2960db91d687d4d37cea33bb2451ab71decdb74eb1c3bad76effaeba2`)

Verified Safety Invariants (`INV-SAFE-1` .. `INV-SAFE-8`):
- `INV-SAFE-1` (Owned-Target & Precondition Gate): No ADB dispatch on foreign/unowned AVD or without lease/preconditions.
- `INV-SAFE-2` (No Blind Retry on Unknown Outcome): `UNKNOWN` blocks dependent input until read-only reconciliation (`driver.py:126-129, 188-189`).
- `INV-SAFE-2b` (Fresh Readback Predicate Acceptance): `ACCEPTED` requires `expected(after) is True`, never `adb exit 0` alone (`driver.py:216-222`).
- `INV-SAFE-3a` (Pre-Dispatch Generation Fence): No new ADB dispatch when `run_gen < fence_gen` (`driver.py:202, 208`).
- `INV-SAFE-3b` (Honest In-Flight Cancel Semantics — No False Syscall Undo Claim): When `cancel()` arrives while an authorized ADB syscall is in flight, never claim the OS effect was rolled back (`driver.py:157`).
- `INV-SAFE-4` (Sound Pair-Level `CONFIRMED` Release Gate): `CONFIRMED` requires `faulty_obs == 'POS'`, `repaired_obs == 'NEG'`, independent log digests, and `export_bound == True` (`repro_oracle.py:92-139`).
- `INV-SAFE-5` (Durable Cancelled-Generation Tombstone in `run_history`): Cancelled generation `G1` can never restart even after `G2` overwrites singleton `lease` and expires (`354b845d` `driver.py:51-55, 133-137, 160`; violated in `782783d` -> `MUT-7`).
- `INV-SAFE-6` (Post-Capture & Post-Predicate Lease Fence): `capture()` and `execute()` re-verify `_fence(db)` after `transport.capture()` and `expected(after)` before returning a `Frame` or committing `ACCEPTED` (`354b845d` `driver.py:115-118, 216-218`; violated in `782783d` -> `MUT-8`).
- `INV-SAFE-7` (Reject Unknown Critical PNG Chunks): `png_size()` rejects unknown critical chunks where `(kind[0] & 32) == 0` outside `{IHDR, PLTE, IDAT, IEND}` (`354b845d` `owned.py:45-48`; violated in `782783d` -> `MUT-9`).
- `INV-SAFE-8` (High-Water Generation & Binding Retirement in `run_history`): Once `G2` starts (`run_history.generation = 2` and `G1` marked `retired = 1`), superseded `G1` can never restart even if `G1` was not explicitly cancelled (`354b845d` `driver.py:131-137, 147-148`; violated if high-water/retirement omitted -> `MUT-10`).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Callable


@dataclass(frozen=True)
class ProtocolState:
    target_kind: str = "OWNED_EMULATOR"  # 'OWNED_EMULATOR' | 'FOREIGN_OR_PHYSICAL'
    lease_valid: bool = False
    lease_expired_mid_capture: bool = False
    pre_verified: bool = False
    fence_gen: int = 1
    run_gen: int = 1
    max_history_gen: int = 1
    gen1_cancelled_in_history: bool = False
    gen1_retired_in_history: bool = False
    resurrected_cancelled_gen: bool = False
    resurrected_retired_or_superseded_gen: bool = False
    journal_state: str = "IDLE"  # 'IDLE' | 'PENDING' | 'DISPATCHED_INFLIGHT' | 'ACCEPTED' | 'NOT_ACCEPTED' | 'UNKNOWN' | 'STOPPED'
    dispatched_count: int = 0
    dispatched_while_stale_or_unowned: bool = False
    blind_retry_from_unknown: bool = False
    accepted_on_exit0_without_fresh_predicate: bool = False
    accepted_after_lease_expiry: bool = False
    accepted_unknown_critical_png_chunk: bool = False
    actual_os_effect_applied: bool = False
    claimed_clean_undo_after_effect: bool = False
    faulty_obs: str = "NONE"  # 'NONE' | 'POS' | 'NEG'
    repaired_obs: str = "NONE"  # 'NONE' | 'POS' | 'NEG' | 'SHARED_LOG_NEG'
    export_bound: bool = False
    released_verdict: str = "NONE"  # 'NONE' | 'INCONCLUSIVE' | 'CONFIRMED'


@dataclass(frozen=True)
class ModelCheckResult:
    variant_id: str
    is_nominal_reference: bool
    reachable_states: int
    explored_transitions: int
    all_invariants_hold: bool
    violated_invariant: str | None
    counterexample_trace: tuple[str, ...] | None
    liveness_confirmed_reachable: bool
    liveness_reconciled_stop_reachable: bool


def check_invariants(state: ProtocolState) -> str | None:
    """Return the first violated invariant ID, or None if all safety invariants hold."""
    if state.dispatched_while_stale_or_unowned:
        if state.target_kind != "OWNED_EMULATOR" or not state.lease_valid or not state.pre_verified:
            return "INV-SAFE-1_NO_UNOWNED_OR_UNVERIFIED_DISPATCH"
        return "INV-SAFE-3a_NO_POST_CANCEL_FENCE_DISPATCH"

    if state.blind_retry_from_unknown:
        return "INV-SAFE-2_NO_BLIND_RETRY_AFTER_UNKNOWN"

    if state.accepted_on_exit0_without_fresh_predicate:
        return "INV-SAFE-2b_NO_ACCEPTED_ON_EXIT0_WITHOUT_FRESH_PREDICATE"

    if state.claimed_clean_undo_after_effect:
        return "INV-SAFE-3b_NO_FALSE_UNDO_CLAIM_ON_INFLIGHT_CANCEL"

    if state.released_verdict == "CONFIRMED":
        if not (
            state.faulty_obs == "POS"
            and state.repaired_obs == "NEG"
            and state.export_bound
            and state.run_gen == state.fence_gen
        ):
            return "INV-SAFE-4_SOUND_CONFIRMED_RELEASE_GATE"

    if state.resurrected_cancelled_gen:
        return "INV-SAFE-5_DURABLE_CANCELLED_GENERATION_TOMBSTONE"

    if state.accepted_after_lease_expiry:
        return "INV-SAFE-6_POST_CAPTURE_AND_PREDICATE_LEASE_FENCE"

    if state.accepted_unknown_critical_png_chunk:
        return "INV-SAFE-7_REJECT_UNKNOWN_CRITICAL_PNG_CHUNKS"

    if state.resurrected_retired_or_superseded_gen:
        return "INV-SAFE-8_HIGHWATER_GENERATION_AND_RETIREMENT_FENCE"

    return None


def _bump_dispatch(count: int) -> int:
    return min(2, count + 1)


def _nominal_transitions(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out: list[tuple[str, ProtocolState]] = []
    if s.released_verdict != "NONE" or s.journal_state in ("STOPPED", "NOT_ACCEPTED"):
        return out

    # Environment setup transitions (OwnedTarget + RuntimeJournal(path, host_boot_id))
    if not s.lease_valid and not s.lease_expired_mid_capture:
        # 354b845d driver.py:131-137 checks run_history for generation > t.generation
        # and cancelled=1 or retired=1 before allowing start()
        if (
            s.run_gen >= s.max_history_gen
            and not (s.run_gen == 1 and (s.gen1_cancelled_in_history or s.gen1_retired_in_history))
        ):
            out.append(("ACQUIRE_LEASE_OWNED_TARGET", replace(s, lease_valid=True, target_kind="OWNED_EMULATOR")))
        out.append(("PROBE_FOREIGN_OR_RUNNING_UNOWNED_AVD", replace(s, lease_valid=False, target_kind="FOREIGN_OR_PHYSICAL")))

    if s.lease_valid and s.target_kind == "OWNED_EMULATOR" and not s.pre_verified:
        out.append(("VERIFY_RESET_PRECONDITIONS", replace(s, pre_verified=True)))

    # Cancellation records cancelled=1 in run_history AND bumps singleton lease generation (driver.py:156-162)
    if s.fence_gen == 1:
        out.append((
            "USER_CANCEL_BUMP_FENCE_AND_RECORD_HISTORY",
            replace(s, fence_gen=2, max_history_gen=2, gen1_cancelled_in_history=True),
        ))

    # Superseding run G2 can also retire G1 when G1 lease expires without explicit cancel (driver.py:147-154)
    if s.fence_gen == 1 and s.journal_state == "IDLE" and s.lease_valid:
        out.append((
            "SUPERSEDE_BY_GEN2_AND_RETIRE_GEN1_IN_HISTORY",
            replace(s, lease_valid=False, fence_gen=2, max_history_gen=2, gen1_retired_in_history=True),
        ))

    # RuntimeJournal PENDING -> ACCEPTED | NOT_ACCEPTED | UNKNOWN | STOPPED lifecycle
    if s.journal_state == "IDLE" and s.lease_valid and s.pre_verified and s.target_kind == "OWNED_EMULATOR":
        if s.run_gen == s.fence_gen:
            out.append(("PERSIST_PENDING_ACTION_RECEIPT", replace(s, journal_state="PENDING")))

    if s.journal_state == "PENDING":
        if s.lease_valid and s.pre_verified and s.target_kind == "OWNED_EMULATOR" and s.run_gen == s.fence_gen:
            out.append((
                "DRIVER_DISPATCH_ADB_TAP",
                replace(s, journal_state="DISPATCHED_INFLIGHT", dispatched_count=_bump_dispatch(s.dispatched_count)),
            ))
        else:
            out.append(("FENCE_BLOCKED_TO_STOPPED", replace(s, journal_state="STOPPED", released_verdict="INCONCLUSIVE")))

    if s.journal_state == "DISPATCHED_INFLIGHT":
        # 354b845d driver.py:115-118 & 216-218 re-checks _fence(db) after capture() and after expected(after)
        if s.lease_valid and not s.lease_expired_mid_capture and s.run_gen == s.fence_gen:
            out.append((
                "ADB_EXIT0_AND_FRESH_FRAME_PREDICATE_TRUE_AND_POST_FENCE_OK_TO_ACCEPTED",
                replace(s, journal_state="ACCEPTED", actual_os_effect_applied=True),
            ))
        out.append((
            "LEASE_EXPIRED_DURING_READBACK_CAUGHT_BY_POST_FENCE_TO_UNKNOWN",
            replace(s, lease_valid=False, lease_expired_mid_capture=True, journal_state="UNKNOWN", actual_os_effect_applied=True),
        ))
        out.append((
            "ADB_EXIT0_BUT_FRESH_FRAME_PREDICATE_FALSE_TO_NOT_ACCEPTED",
            replace(s, journal_state="NOT_ACCEPTED", actual_os_effect_applied=False, released_verdict="INCONCLUSIVE"),
        ))
        out.append((
            "ADB_SYSCALL_TIMEOUT_EFFECT_APPLIED_TO_UNKNOWN",
            replace(s, journal_state="UNKNOWN", actual_os_effect_applied=True),
        ))
        out.append((
            "ADB_SYSCALL_TIMEOUT_NO_EFFECT_TO_UNKNOWN",
            replace(s, journal_state="UNKNOWN", actual_os_effect_applied=False),
        ))

    if s.journal_state == "UNKNOWN":
        out.append(("READONLY_RECONCILE_TO_STOPPED", replace(s, journal_state="STOPPED", released_verdict="INCONCLUSIVE")))

    # Post-workflow oracle & control evaluation
    if s.journal_state == "ACCEPTED":
        if s.faulty_obs == "NONE":
            out.append(("OBSERVE_FAULTY_POS", replace(s, faulty_obs="POS")))
            out.append(("OBSERVE_FAULTY_NEG", replace(s, faulty_obs="NEG")))
        elif s.repaired_obs == "NONE":
            out.append(("OBSERVE_REPAIRED_INDEPENDENT_NEG", replace(s, repaired_obs="NEG", export_bound=True)))
            out.append(("OBSERVE_REPAIRED_STILL_FAILS_POS", replace(s, repaired_obs="POS", export_bound=True)))
            out.append(("OBSERVE_REPAIRED_SHARED_LOG_DIGEST", replace(s, repaired_obs="SHARED_LOG_NEG", export_bound=True)))
            out.append(("OBSERVE_REPAIRED_MISSING_EXPORT_BINDING", replace(s, repaired_obs="NEG", export_bound=False)))
        else:
            if (
                s.run_gen == s.fence_gen
                and s.faulty_obs == "POS"
                and s.repaired_obs == "NEG"
                and s.export_bound
            ):
                out.append(("SAVE_TERMINAL_CONFIRMED", replace(s, released_verdict="CONFIRMED")))
            else:
                out.append(("SAVE_TERMINAL_INCONCLUSIVE", replace(s, released_verdict="INCONCLUSIVE")))

    return out


def _mut1_skip_serial_or_precondition_check(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out = _nominal_transitions(s)
    if s.journal_state == "IDLE" and s.target_kind == "FOREIGN_OR_PHYSICAL" and s.dispatched_count < 2:
        out.append((
            "MUT1_UNOWNED_DIRECT_DISPATCH",
            replace(s, journal_state="DISPATCHED_INFLIGHT", dispatched_count=_bump_dispatch(s.dispatched_count), dispatched_while_stale_or_unowned=True),
        ))
    return out


def _mut2_blind_retry_on_unknown(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out = _nominal_transitions(s)
    if s.journal_state == "UNKNOWN" and s.dispatched_count < 2:
        out.append((
            "MUT2_BLIND_RETRY_TAP_FROM_UNKNOWN",
            replace(s, journal_state="DISPATCHED_INFLIGHT", dispatched_count=_bump_dispatch(s.dispatched_count), blind_retry_from_unknown=True),
        ))
    return out


def _mut3_omit_driver_generation_fence(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out = _nominal_transitions(s)
    if s.journal_state == "PENDING" and s.run_gen < s.fence_gen and s.dispatched_count < 2:
        out.append((
            "MUT3_STALE_GENERATION_DISPATCH_TAP",
            replace(s, journal_state="DISPATCHED_INFLIGHT", dispatched_count=_bump_dispatch(s.dispatched_count), dispatched_while_stale_or_unowned=True),
        ))
    return out


def _mut4_claim_clean_undo_on_inflight_cancel(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out = _nominal_transitions(s)
    if s.journal_state == "DISPATCHED_INFLIGHT" and s.run_gen < s.fence_gen:
        out.append((
            "MUT4_CLAIM_INFLIGHT_EFFECT_ROLLED_BACK",
            replace(s, journal_state="STOPPED", actual_os_effect_applied=True, claimed_clean_undo_after_effect=True),
        ))
    return out


def _mut5_confirm_on_shared_log_or_missing_binding(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out = _nominal_transitions(s)
    if s.journal_state == "ACCEPTED" and s.faulty_obs == "POS" and s.repaired_obs == "SHARED_LOG_NEG":
        out.append((
            "MUT5_CONFIRM_SHARED_LOG_RECEIPT",
            replace(s, released_verdict="CONFIRMED"),
        ))
    return out


def _mut6_accept_on_exit0_without_fresh_predicate(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    out = _nominal_transitions(s)
    if s.journal_state == "DISPATCHED_INFLIGHT":
        out.append((
            "MUT6_ACCEPT_ON_EXIT0_IGNORING_PREDICATE_FALSE",
            replace(s, journal_state="ACCEPTED", accepted_on_exit0_without_fresh_predicate=True),
        ))
    return out


def _mut7_rt782_lease_overwrite_loses_cancelled_tombstone(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    """Models superseded 782783d driver.py:92-108 defect (fixed in 354b845d via run_history):
    Gen 1 is cancelled -> Gen 2 overwrites singleton lease row -> Gen 2 expires ->
    stale Gen 1 calls start() and resurrects Gen 1 because cancelled tombstone was lost.
    """
    out = _nominal_transitions(s)
    if s.gen1_cancelled_in_history and s.fence_gen == 2 and s.journal_state == "IDLE":
        out.append((
            "MUT7_RT782_GEN2_OVERWRITES_SINGLETON_LEASE_THEN_EXPIRES_AND_GEN1_RESURRECTS",
            replace(s, lease_valid=True, fence_gen=1, run_gen=1, resurrected_cancelled_gen=True),
        ))
    return out


def _mut8_rt782_missing_post_capture_predicate_lease_fence(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    """Models superseded 782783d driver.py:117-120,143-158 defect (fixed in 354b845d driver.py:115-118,216-218):
    Lease expires during transport.tap() / transport.capture(end) / expected(after),
    but execute() writes state='ACCEPTED' without re-checking _fence(db).
    """
    out = _nominal_transitions(s)
    if s.journal_state == "DISPATCHED_INFLIGHT":
        out.append((
            "MUT8_RT782_COMMIT_ACCEPTED_AFTER_LEASE_EXPIRED_DURING_READBACK",
            replace(s, lease_valid=False, lease_expired_mid_capture=True, journal_state="ACCEPTED", accepted_after_lease_expiry=True),
        ))
    return out


def _mut9_rt782_accept_unknown_critical_png_chunk(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    """Models superseded 782783d owned.py:36-80 defect (fixed in 354b845d owned.py:45-48):
    png_size() loops over PNG chunks checking only IHDR/IDAT/IEND and silently accepts
    unknown critical chunks (where (chunk_type[0] & 0x20) == 0).
    """
    out = _nominal_transitions(s)
    if s.journal_state == "DISPATCHED_INFLIGHT":
        out.append((
            "MUT9_RT782_PARSE_FRAME_WITH_UNKNOWN_CRITICAL_PNG_CHUNK",
            replace(s, journal_state="ACCEPTED", accepted_unknown_critical_png_chunk=True),
        ))
    return out


def _mut10_omit_run_history_retirement_and_highwater_check(s: ProtocolState) -> list[tuple[str, ProtocolState]]:
    """Models omitting 354b845d driver.py:131-137,147-148 run_history high-water & retirement check:
    Gen 1 (not explicitly cancelled) is superseded by Gen 2 -> Gen 2 expires ->
    stale Gen 1 restarts because retired=1 / generation>t.generation check was omitted.
    """
    out = _nominal_transitions(s)
    if s.gen1_retired_in_history and not s.lease_valid and s.journal_state == "IDLE":
        out.append((
            "MUT10_RESTART_RETIRED_GEN1_AFTER_GEN2_LEASE_EXPIRY",
            replace(s, lease_valid=True, fence_gen=1, run_gen=1, resurrected_retired_or_superseded_gen=True),
        ))
    return out


def check_protocol_model(
    transition_fn: Callable[[ProtocolState], list[tuple[str, ProtocolState]]] = _nominal_transitions,
    *,
    variant_id: str = "NOMINAL_354B845D_AND_V4_PROTOCOL",
    is_nominal_reference: bool = True,
) -> ModelCheckResult:
    """Exhaustively explore the finite state space via BFS and verify safety & liveness."""
    init = ProtocolState()
    queue: deque[tuple[ProtocolState, tuple[str, ...]]] = deque([(init, ())])
    visited: set[ProtocolState] = {init}
    transitions_count = 0
    violated: str | None = None
    counterexample: tuple[str, ...] | None = None
    confirmed_reached = False
    reconciled_reached = False

    while queue:
        state, trace = queue.popleft()
        if state.released_verdict == "CONFIRMED":
            confirmed_reached = True
        if state.journal_state == "STOPPED":
            reconciled_reached = True

        inv_err = check_invariants(state)
        if inv_err is not None and violated is None:
            violated = inv_err
            counterexample = trace

        for action_label, next_state in transition_fn(state):
            transitions_count += 1
            if next_state not in visited:
                visited.add(next_state)
                queue.append((next_state, trace + (action_label,)))

    return ModelCheckResult(
        variant_id=variant_id,
        is_nominal_reference=is_nominal_reference,
        reachable_states=len(visited),
        explored_transitions=transitions_count,
        all_invariants_hold=(violated is None),
        violated_invariant=violated,
        counterexample_trace=counterexample,
        liveness_confirmed_reachable=confirmed_reached,
        liveness_reconciled_stop_reachable=reconciled_reached,
    )


def run_mutation_sensitivity_suite() -> dict:
    """Run the nominal 354b845d+v4 model checker and all 10 broken variants."""
    nominal = check_protocol_model(_nominal_transitions, variant_id="NOMINAL_354B845D_AND_V4_PROTOCOL", is_nominal_reference=True)
    mutations = [
        check_protocol_model(_mut1_skip_serial_or_precondition_check, variant_id="MUT-1_SKIP_OWNED_SERIAL_CHECK", is_nominal_reference=False),
        check_protocol_model(_mut2_blind_retry_on_unknown, variant_id="MUT-2_BLIND_RETRY_ON_UNKNOWN", is_nominal_reference=False),
        check_protocol_model(_mut3_omit_driver_generation_fence, variant_id="MUT-3_OMIT_DRIVER_GEN_FENCE", is_nominal_reference=False),
        check_protocol_model(_mut4_claim_clean_undo_on_inflight_cancel, variant_id="MUT-4_FALSE_UNDO_ON_INFLIGHT_CANCEL", is_nominal_reference=False),
        check_protocol_model(_mut5_confirm_on_shared_log_or_missing_binding, variant_id="MUT-5_CONFIRM_ON_SHARED_LOG", is_nominal_reference=False),
        check_protocol_model(_mut6_accept_on_exit0_without_fresh_predicate, variant_id="MUT-6_ACCEPT_ON_EXIT0_WITHOUT_FRESH_PREDICATE", is_nominal_reference=False),
        check_protocol_model(_mut7_rt782_lease_overwrite_loses_cancelled_tombstone, variant_id="MUT-7_RT782_LEASE_OVERWRITE_RESURRECTS_CANCELLED_GEN1", is_nominal_reference=False),
        check_protocol_model(_mut8_rt782_missing_post_capture_predicate_lease_fence, variant_id="MUT-8_RT782_MISSING_POST_CAPTURE_PREDICATE_LEASE_FENCE", is_nominal_reference=False),
        check_protocol_model(_mut9_rt782_accept_unknown_critical_png_chunk, variant_id="MUT-9_RT782_UNKNOWN_CRITICAL_PNG_CHUNK_ACCEPTED", is_nominal_reference=False),
        check_protocol_model(_mut10_omit_run_history_retirement_and_highwater_check, variant_id="MUT-10_OMIT_RUN_HISTORY_RETIREMENT_AND_HIGHWATER", is_nominal_reference=False),
    ]
    return {
        "model_scope": "BOUNDED_ABSTRACT_FINITE_STATE_MODEL_NOT_FULL_CODE_PROOF",
        "liveness_interpretation": "ABSTRACT_GRAPH_COMPLETION_REACHABILITY_ONLY_NOT_UNIVERSAL_TEMPORAL_LIVENESS",
        "code_mapping_status": {
            "offline_reference_examples": {
                "status": "VERIFIED_PASS",
                "examples/repro_oracle.py": "36e6471e5a0b804d3a82872ba8a953d6f12cdd309630752551d99c06bd8cf73c",
                "examples/replay_contracts.py": "49b940f6ddadda9f2b95cfce5e89fd947714ac04290972240e27683ce6e0d21c",
                "examples/evaluation_metrics.py": "24a629a24a2a1825d8796bfd7b128002db5165babb4a4c0bba279d6a4fd793bd",
                "examples/meta_protocol.py": "1eaefeedccae5f3071ed514a1371277c0e7873bf72f73e28fb10719d9d286240",
            },
            "superseded_runtime_782783d_a99b1c9": {
                "status": "FAILED_ON_782783D_KILLED_BY_MUT7_MUT8_MUT9",
                "src/reproloop/runtime/driver.py": "0749834fef1e9f33e4b65bfa0c378ff6d3e410691995c8c772011d58f165704c",
                "src/reproloop/runtime/owned.py": "bd7514e2960db91d687d4d37cea33bb2451ab71decdb74eb1c3bad76effaeba2",
            },
            "repaired_runtime_354b845d_047e8e8": {
                "status": "READ_ONLY_SOURCE_CORRESPONDENCE_ON_354B845D_NOT_FULL_CODE_OR_NATIVE_WRAPPER_PROOF",
                "unverified_parent_main_deltas": (
                    "Parent main native wrapper, CRLF SDK identity normalization, and 5s read-timeout "
                    "adjustments outside commit 354b845d723a05e5e091b07d8b1723929a82df77 are UNVERIFIED "
                    "by this abstract model."
                ),
                "src/reproloop/runtime/driver.py": {
                    "sha256": "727994c33a66078239d1487b6e1f64a08dc4b4247729bc66b7b872ff4cb3acf1",
                    "bytes": 13557,
                    "INV-SAFE-1_and_3a": "Lines 105-113 (_fence), 120-155 (start), 187, 202, 208 (execute pre-dispatch fences)",
                    "INV-SAFE-2_and_2b": "Lines 126-129 (crash residue PENDING->UNKNOWN), 188-189 (UNKNOWN blocks dependent actions), 216-225 (fresh readback predicate expected(after))",
                    "INV-SAFE-5_and_8": "Lines 51-55 (run_history table), 131-137 (high-water generation>? and cancelled=1/retired=1 check), 147-151 (retire prior binding), 160-161 (cancel persists cancelled=1 in run_history)",
                    "INV-SAFE-6": "Lines 115-118 (_capture post-fence), 163-165 (capture), 216-218 (execute post-capture and post-predicate _fence(db) before ACCEPTED)",
                },
                "src/reproloop/runtime/owned.py": {
                    "sha256": "ed37dcd8be3eaac120f7ad7fbb5a8defe7d67395048ee63d284f2be2dd809001",
                    "bytes": 11391,
                    "INV-SAFE-1_target": "Lines 82-104 (OwnedTarget emulator- serial regex, package, generation), 182-196 (OwnedAdbTransport.discover owner_id, boot_id, base.apk sha256sum)",
                    "INV-SAFE-7_png": "Lines 36-90 (png_size rejects invalid chunk types, unknown critical chunks !(kind[0]&32) outside IHDR/PLTE/IDAT/IEND, noncontiguous IDAT, and CRC/zlib bounds)",
                    "interface_note_resolve_center": "Line 160 computes ((l+r)//2, (t+b)//2) whereas examples/replay_contracts.py:169 computes ((left+right-1)//2, (top+bottom-1)//2); 1px even-width difference noted for cross-module integration.",
                },
            },
            "os_syscall_atomicity_limit": (
                "No theorem claims zero OS effect after cancel() wall-clock timestamp when an ADB "
                "syscall was already dispatched in flight; INV-SAFE-3a/3b verifies pre-dispatch fencing "
                "and honest post-dispatch accounting. Live system UI / AVD end-to-end execution remains a separate gate."
            ),
        },
        "nominal_result": {
            "variant_id": nominal.variant_id,
            "reachable_states": nominal.reachable_states,
            "explored_transitions": nominal.explored_transitions,
            "all_invariants_hold": nominal.all_invariants_hold,
            "liveness_confirmed_reachable": nominal.liveness_confirmed_reachable,
            "liveness_reconciled_stop_reachable": nominal.liveness_reconciled_stop_reachable,
        },
        "mutation_sensitivity_results": [
            {
                "variant_id": m.variant_id,
                "all_invariants_hold": m.all_invariants_hold,
                "violated_invariant": m.violated_invariant,
                "minimal_counterexample_trace": list(m.counterexample_trace or ()),
                "trace_length": len(m.counterexample_trace or ()),
            }
            for m in mutations
        ],
        "all_mutations_killed": all(not m.all_invariants_hold and m.counterexample_trace for m in mutations),
    }
