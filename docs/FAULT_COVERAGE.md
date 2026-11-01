# WO-10 fault coverage: bounded local closure

2026-10-27. Source inspected/tested: detached `5acba518815c9507838cd3aaabe2e5f27999ba1e`, plus only `tests/faults/test_fault_boundaries.py` and this document. No runtime/source files changed. Parent owns native B1; release packaging is another worker's scope.

**Result:** all eight required WO-10 categories have inspected code/assertion coverage, with 11 additional meaningful local tests. **192 affected Python tests passed, zero skips/failures in this run.** This closes the bounded local-simulated fault work, not native/OS fault certification or release approval. No actual core defect was found by these checks. Canonical external cross-audit: **NOT_RUN**. Novice human readthrough: **NOT_DONE**.

## Contract and real callers

`RuntimeDriver.execute` in `src/reproloop/runtime/driver.py` commits a PENDING intent before input, retains the cooperative file/SQLite fence across dispatch, classifies post-dispatch exceptions UNKNOWN, and blocks dependent actions whenever PENDING/UNKNOWN exists. `start` converts crash residue PENDING to UNKNOWN; `reconcile` only recaptures the same intent and a false predicate remains UNKNOWN. A driver ACCEPTED receipt is **not** a pair CONFIRMED verdict.

`OwnedAdbTransport.discover/capture/tap` in `src/reproloop/runtime/owned.py` enforce boot/owner/APK identity and screenshot/hierarchy stability. `EvidenceTransport.capture/observe_capture_probe/persist_capture` and `save_blob` in `src/reproloop/lab.py` persist actual capture artifacts before returning a frame. `model_free_replay` in `src/reproloop/replay.py` requires ACCEPTED steps and independent state/event collection, retains unresolved fences, and produces no valid completed control when evidence is absent. `bind_saved_pair` in `src/reproloop/pair_binding.py` rejects mismatched/corrupt/raw-missing records. `judge` in `examples/repro_oracle.py` does not substitute a visual match for independent controls.

## Required category matrix

Every row below is **local simulated boundary evidence**. Actual fault-injected native/provider/OS evidence is **NOT_TESTED for every row**. No device, provider, emulator or operational database was accessed by this task. Existing normal native FINAL results are not proof that these faults occurred.

| Required category | Actual code boundary and existing assertion coverage | Added assertion coverage / disposition |
|---|---|---|
| Cancel races | `RuntimeDriver.cancel/execute/start`, runtime `test_pending_is_committed_at_input_and_cancel_serialized`: a separate SQLite reader sees PENDING during blocked input, cancel waits for dispatch/readback, one ACCEPTED effect is preserved. `test_stale_binding_and_generation` blocks a cancelled generation. `tests/runtime/test_audit_regressions.py::test_cancel_tombstone_survives_new_driver_and_journal` and `tests/runtime/test_repair.py::test_cancelled_generation_stays_dead_after_replacement_expiry_and_reopen` retain cancellation across reopen/replacement leases. | Existing assertions sufficient; no duplicate cancellation test added. A cooperating cancel does not undo an already accepted external effect. No OS scheduling exhaustiveness claim. |
| ADB timeout | `OwnedAdbTransport._cmd`; `RuntimeDriver.execute/reconcile`. Runtime `test_unknown_blocks_new_id_and_reconciles_read_only`: timeout after fake tap becomes UNKNOWN, new ID blocked, false reconcile stays UNKNOWN, true reconcile ACCEPTED, tap count stays one. Repair `test_unknown_still_blocks_new_generation`, `test_late_predicate_is_unknown_and_never_replayed`, `test_readonly_reconcile_late_predicate_cannot_confirm` cover delayed/partial outcomes and generation fences. | Existing assertions sufficient. No actual ADB invocation. “Reconcile accepted” is an action receipt, not bug confirmation. |
| Emulator reboot / boot identity change | `OwnedAdbTransport.discover` reads exact boot identity at capture and immediately before input; runtime host-boot fence test covers journal ownership after host change. | New `test_boot_change_before_input_rejects_without_intent`: zero taps, no intent. `test_boot_change_after_input_is_unknown_and_readonly_reconcile_stops`: one input, UNKNOWN persists, changed boot rejects read-only reconciliation and new action. No actual reboot. |
| Missing events | `AppStateReader.collect`, `validate_snapshot`, `oracle_fields` in `src/reproloop/runtime/app_state.py`. `SchemaTests.test_state_event_mutability_and_sequence_windows`, `test_missing_unknown_duplicate_malformed_and_truncated`, `test_cancel_cannot_be_inferred_from_dismiss`; `OracleAdapterTests.test_missing_independent_trace_stays_unknown` assert sequence/schema rejection or no completed usable oracle. | New real-caller `test_missing_cancel_event_in_real_replay_cannot_be_negative_control_success` deletes terminal Cancel event from fake bytes at the transport boundary; actual fixed replay returns incomplete with absent/unknown failure signal. Missing evidence is not fixed-negative success. |
| Malformed / duplicate JSON | `app_state.parse/pairs`, provider `strict_json` in `src/reproloop/meta/client.py`, raw pair reader, reference `parse_candidate`. `SchemaTests.test_missing_unknown_duplicate_malformed_and_truncated`, `tests/pair/test_pair_binding.py::test_malformed_duplicate_json` and protocol `test_duplicate_keys` reject ambiguous objects. | New `test_malformed_or_duplicate_provider_json_stays_unknown_after_reopen` uses two subcases (malformed and duplicate-key HTTP-200 bytes); UNKNOWN survives real temporary SQLite reopen, new ID blocked, fake HTTP calls remain one per subcase. No raw model response files read. |
| Provider 429 | `MetaClient._result/responses`, `CostLedger.finish/reserve` in `src/reproloop/meta/ledger.py`. Existing `MetaTests.test_http_reject_vs_server_unknown_and_warning_halt` distinguishes 400 rejection from 429 halt and blocks next request. | New `test_simulated_429_halt_survives_reopen_without_another_http_request`: REJECTED + durable HTTP_429 halt, reopened client rejects new ID without a second request. A fake transport returns 429; real rate limiting deliberately not induced. |
| Screenshot MIME / rotation mismatch | `png_size`, `OwnedAdbTransport.capture`, stale preframe comparison in `RuntimeDriver.execute`; protocol `test_mime_mismatch` rejects JPEG-as-PNG. `tests/runtime/test_capture_stability.py` asserts stable bracket, read-only resampling of a transition, and persistent-animation rejection with zero inputs. | New `test_rotation_before_input_rejects_stale_frame_without_intent` supplies a valid different-dimension PNG and asserts zero input/no intent. `test_bad_screenshot_mime_after_input_is_unknown_not_accepted` supplies JPEG-like bytes after one fake tap; UNKNOWN survives journal reopen and new ID is blocked. Rotation to a fresh valid observation is not claimed universally unsupported. |
| Disk-full before/after durable input; partial artifact | `RuntimeJournal.locked`, durable commit/update boundaries in `RuntimeDriver.execute/start`; `EvidenceTransport` capture saves and `save_blob`. Pair `test_hash_corruption`, `test_missing_reset`, `test_unknown_readdressed_journal`, `test_declared_booleans_without_raw_do_not_bind` explicitly reject damaged/partial/unresolved evidence. Lab `test_hash_collision_fails_closed` rejects an existing content-addressed file with wrong bytes. | New disk tests inject a deterministic SQLite OperationalError at pre-intent commit or post-input receipt update; real temp DB reopen demonstrates rollback before input, versus PENDING→UNKNOWN and no new-ID replay after input. New capture ENOSPC tests cover driver and actual replay/EvidenceTransport callers. No disk fill, filesystem crash, pager corruption or power loss was induced. |

## New tests: exact names (11)

All reside in `tests/faults/test_fault_boundaries.py`:

1. `DurableInputFaultTests.test_disk_full_before_durable_intent_prevents_input_and_rolls_back`
2. `DurableInputFaultTests.test_disk_full_after_input_keeps_pending_then_unknown_across_reopen`
3. `DurableInputFaultTests.test_capture_artifact_enospc_after_input_is_unknown_and_blocks_new_id`
4. `DurableInputFaultTests.test_boot_change_before_input_rejects_without_intent`
5. `DurableInputFaultTests.test_boot_change_after_input_is_unknown_and_readonly_reconcile_stops`
6. `DurableInputFaultTests.test_rotation_before_input_rejects_stale_frame_without_intent`
7. `DurableInputFaultTests.test_bad_screenshot_mime_after_input_is_unknown_not_accepted`
8. `DurableProviderFaultTests.test_simulated_429_halt_survives_reopen_without_another_http_request`
9. `DurableProviderFaultTests.test_malformed_or_duplicate_provider_json_stays_unknown_after_reopen` (two subcases, counted as one unittest)
10. `ReplayFaultTests.test_real_capture_save_enospc_after_input_cannot_complete_or_start_new_run`
11. `ReplayFaultTests.test_missing_cancel_event_in_real_replay_cannot_be_negative_control_success`

SQLite injections subclass the real connection and raise `sqlite3.OperationalError('database or disk is full')` at selected commit/update boundaries. This tests application control flow and persistence/reopen, not every SQLite pager/disk failure. ENOSPC is a deterministic `OSError(errno.ENOSPC)` at the real evidence-saving caller or its capture boundary. Inputs/HTTP are in-memory fakes; all DBs/files created by these tests are temporary synthetic fixtures.

## Normal / partial / known-failed / UNKNOWN controls

- **Normal:** runtime `test_acceptance_requires_readback_and_duplicate_is_not_replayed` exercises accepted/negative readback and duplicate dispatch count; lab `test_pair_same_generation_and_persisted_post_frames` replays both builds with model calls zero and opposing actual fixture oracle signals. Pair `test_normal_raw_pair` reaches CONFIRMED only with complete valid raw synthetic controls.
- **Partial:** missing Cancel/event sequence, malformed receipts, unreadable capture and truncated artifacts cannot provide completed independent controls. New real replay tests assert `complete=False` and missing/unknown oracle, not merely exception text.
- **Known failed:** false readback returns NOT_ACCEPTED; definitive fake HTTP429 returns REJECTED and halts further requests. Neither result becomes an UNKNOWN retry permission or pair CONFIRMED.
- **UNKNOWN:** action timeout, identity loss after input, post-input MIME or evidence-write error retains one unresolved intent. Post-input durable receipt-write failure leaves committed PENDING even when execute raises; restart durably classifies UNKNOWN. Same action returns unresolved receipt; different action ID/generation cannot dispatch; only matching read-only reconciliation can resolve action acceptance.
- **No false CONFIRMED:** raw-pair tests reject UNKNOWN journals, malformed/duplicate JSON, hash corruption, reused/missing logs or reset proofs, forged stored oracle and false completion. Oracle tests cover incomplete/unknown/missing controls and visual-only signals. No new test silently changes a failing expected assertion to green.

## Exact run and counts

Run from the worktree with `PYTHONPATH=src:examples:.`:

```sh
python3 -m unittest discover -s tests/faults -q                         # 11
python3 -m unittest discover -s tests/runtime -q                        # 64
python3 -m unittest discover -s tests/meta -p test_meta.py -q            # 19
python3 -m unittest discover -s tests/pair -q                           # 17
python3 -m unittest discover -s examples -p test_meta_protocol.py -q     # 32
python3 -m unittest discover -s tests/lab -q                            # 9
python3 -m unittest discover -s examples -p test_repro_oracle.py -q      # 40
```

**Total: 192 tests passed, zero failures/errors/skips.** 181 existing + 11 new; subcases are not inflated into separate tests. Runtime64 already includes app-state/repair/capture tests. Meta19 deliberately selects client/gateway fake HTTP tests; four unrelated FIFO IPC tests were not rerun. This task did not rerun UI/video/all443 tests and does not claim a new full-suite aggregate. Parent will merge and rerun the full checker, which discovers `tests/faults/` automatically.

## Remaining limits and holds

- No actual native timeout/reboot, real429, disk exhaustion, OS kill/power loss, adversarial filesystem durability or real-provider idempotency was tested. Actual operational faults are **NOT_TESTED**, deliberately.
- Bounded cooperative race tests are not exhaustive interprocess/OS model checking. File lock/SQLite semantics, injected fake runner, and local trusted-host assumptions remain.
- Normal FINAL native evidence does not upgrade simulated fault coverage to native fault evidence. Native B1 is parent-owned and not inspected or interrupted here.
- No runtime fix was needed or authorized by these passing examples; no core defect/counterexample was found. Future failing counterexamples must be retained and coordinated before source changes.
- External ChatGPT→Gemini→ChatGPT review **NOT_RUN**; public release/submission/payment remain held. Human novice demo readthrough **NOT_DONE**.
