# Private 180-second storyboard
All timings are edited presentation time, not native execution time.

## 000–018s | Cancel should mean cancel.
Mode: RECORDED SOURCE VIDEO. Original recording • 1.731x playback • no audio
A bug video is not a regression test.
Release → Today → Cancel
Expected: keep Release. Actual: Today.
Caption: This self-owned synthetic app saves the draft title after Cancel.

## 018–028s | Start with the real recording.
Mode: RECORDED META. FINAL-C • source SHA-256 afd7f11e • LAB-ANDROID-1
Meta muse-spark-1.3
VIDEO + 12 uniform frames
Native pointer pixels + temporal OCR
Caption: The recorded Meta input combines video, uniform frames, pointer pixels and OCR.

## 028–038s | A candidate, not a verdict.
Mode: RECORDED META. No new inference during this demo
Video intent proposes the workflow.
Predeclared invariant: Cancel preserves stored title.
The independent oracle judges later.
Caption: Model intent proposes actions. A separate predeclared oracle checks the result.

## 038–046s | 01  Select the task.
Mode: RECORDED META. RECORDED FRAME SEQUENCE; transitions omitted
Fresh screenshot → native pixel input
Recorded CUA: 4 model calls total.
Caption: Recorded CUA step 1: select the task.

## 046–053s | 02  Open Rename.
Mode: RECORDED META. RECORDED FRAME SEQUENCE; transitions omitted
Fresh screenshot, not copied video coordinates
Recorded CUA: 4 model calls total.
Caption: Recorded CUA step 2: open Rename.

## 053–060s | 03  Set the draft to Today.
Mode: RECORDED META. RECORDED FRAME SEQUENCE; transitions omitted
Accepted input checked by fresh readback
Recorded CUA: 4 model calls total.
Caption: Recorded CUA step 3: choose Today.

## 060–067s | 04  Press Cancel.
Mode: RECORDED META. RECORDED FRAME SEQUENCE; transitions omitted
Four native CUA inputs accepted
Recorded CUA: 4 model calls total.
Caption: Recorded CUA step 4: press Cancel.

## 067–075s | The title changed anyway.
Mode: RECORDED META. RECORDED FRAME SEQUENCE; transitions omitted
Fault candidate observed.
A model saying “done” is not proof.
Fresh faulty/fixed controls are still required.
Caption: The title is Today after Cancel. The control pair is still required.

## 075–087s | Judge persisted state + events.
Mode: RECORDED NO-MODEL REPLAY. Saved oracle summary • actual replay capture
Oracle: cancel_preserves_stored_title
Faulty replay: completed; failure = true.
Not a screenshot-similarity score.
Caption: The independent persisted-state and event oracle reports the faulty signal.

## 087–100s | Keep the evidence boundary clear.
Mode: RECORDED META. Saved-frame montage, not end-to-end elapsed time
FINAL-C: sampled pointer context.
Consistent context, not causal proof.
Read-only observations used: 0.
Caption: Sampled-context consistency is not physical-tap proof. The optional read-only branch was unused.

## 100–108s | Export semantics once.
Mode: RECORDED NO-MODEL REPLAY. Export 0f2185d9 • fixture 4c557c97 • model calls 0
Target task: Release
Rename → Today → Cancel
Same export on both fresh controls.
Caption: Export four semantic steps once. Replay the exact same export on fresh faulty and fixed builds.

## 108–114s | Faulty control  1/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Select task
Fresh reset • model calls 0
Failure signal: true after completion.
Caption: Faulty model-free replay: select task.

## 114–120s | Faulty control  2/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Open Rename
Fresh reset • model calls 0
Failure signal: true after completion.
Caption: Faulty model-free replay: open rename.

## 120–125s | Faulty control  3/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Choose Today
Fresh reset • model calls 0
Failure signal: true after completion.
Caption: Faulty model-free replay: choose today.

## 125–130s | Faulty control  4/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Cancel
Fresh reset • model calls 0
Failure signal: true after completion.
Caption: Faulty model-free replay: cancel.

## 130–136s | Fixed control  1/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Select task
Same export • fresh reset • model calls 0
Developer-supplied fixed control; not ReproLoop repair.
Caption: Fixed model-free replay: select task.

## 136–142s | Fixed control  2/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Open Rename
Same export • fresh reset • model calls 0
Developer-supplied fixed control; not ReproLoop repair.
Caption: Fixed model-free replay: open rename.

## 142–147s | Fixed control  3/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Choose Today
Same export • fresh reset • model calls 0
Developer-supplied fixed control; not ReproLoop repair.
Caption: Fixed model-free replay: choose today.

## 147–152s | Fixed control  4/4
Mode: RECORDED NO-MODEL REPLAY. RECORDED FRAME SEQUENCE; transitions omitted
Cancel
Same export • fresh reset • model calls 0
Developer-supplied fixed control; not ReproLoop repair.
Caption: Fixed model-free replay: cancel.

## 152–158s | Same test. Different outcome.
Mode: RECORDED NO-MODEL REPLAY. Same export 0f2185d9 • builds 5b7e27d2 / 4bcd2374
FAULTY: Today • failure true
FIXED: Release • failure false
Both workflows completed.
Caption: The developer-supplied fixed control keeps Release. Faulty is true; fixed is false.

## 158–166s | Preserve both result cohorts.
Mode: RECORDED RESULTS. One F01 family • three correlated variants • not independent bugs
Original v3 pilot: 2/5; target ≥3/5 missed.
3 original failures remain.
Separate v4obs1 FINAL: 3/3 pairs.
Caption: Original pilot: two of five, below target. Separate FINAL: three of three correlated variants.

## 166–172s | Bounded evidence. Real limits.
Mode: RECORDED RESULTS. Cumulative fees include earlier failed conditions; not final billing
Each FINAL: 5 calls, 4 inputs, 2 controls.
Cumulative: 54/60 calls; $1.030238 token fees.
Uploads UNPRICED; no generic accuracy claim.
Caption: Each FINAL case used five model calls and two model-free controls. Upload fees remain unpriced.

## 172–180s | A replay we can verify.
Mode: PRIVATE • RECORDED EVIDENCE. Byte integrity is not producer, physical-tap, timestamp or OS attestation.
PRIVATE PROTOTYPE
Not release approved.
Generalization not evaluated.
Caption: Private prototype. Not release approved. Generalization has not been evaluated.
