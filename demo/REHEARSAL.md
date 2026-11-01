# Automated local rehearsal check

PASS: 180.000 seconds; 1920×1080; H.264 yuv420p; 24fps; 4,320 decoded frames; no audio streams.

- 23 segments cover 0–180s contiguously. English captions are burned in and supplied as SRT.
- Caption peak reading rate: 15.83 characters/second (automated threshold <22); large 32px caption baseline.
- One actual source MP4 plays at disclosed 1.731x (computed from the source container duration / 18s). CUA and model-free replays use original saved capture pixels with transitions omitted, explicitly labeled. No generated touch or timestamp overlays.
- Same FINAL-C export SHA-256 0f2185d91acb8e96ca33339e8dc517a0458aedb674c522bf458a935dae7d565d binds the two saved model-free controls.
- All copied source assets match full hashes in source-manifest.json. Identity aliases and allowlisted summary fields only. Aggregate numeric claims reference safe-aggregates.json and original-record/ledger-aggregate hashes; they are not producer-authenticated.
- Rehearsal type: automated local decode, pacing and image review, not a fresh device/model run.
- Novice human readthrough: NOT DONE. Human script review and final private viewing remain pending.
- B1 native baseline/fault testing: parent-owned; not claimed by this demo.
- Producer/physical-tap/timestamp/OS attestation: NOT PROVIDED. No publication, submission or release approval.
