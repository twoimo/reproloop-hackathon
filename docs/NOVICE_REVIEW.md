# Human novice review form (UNFILLED)

Status: **NOT DONE.** Every field below is blank on purpose. Only a real human
observer watching a real human participant may fill it. An LLM, agent,
simulated persona or the developer answering on someone else's behalf cannot
substitute for this review, and a filled form is not valid unless the observer
records it themselves.

## Purpose

Check whether a person new to the project can follow the source-only archive
and the fresh-reproduction runbook, and whether they understand the reported
results correctly without help.

## Rules for the observer

1. Give the participant only the verified extracted source archive (and, if
   testing the runbook, a host that meets `docs/FRESH_REPRODUCTION.md`
   section 3). No private evidence, receipts, keys or original journal.
2. Do not help, hint, or correct during the session. If the participant is
   stuck, record where and for how long; they may give up on a step.
3. Device steps (runbook sections 8 and later) happen only if a new target has
   been separately authorized. Otherwise mark them NOT ATTEMPTED.
4. Record wrong interpretations word for word. Keep every failure.
5. Use one wall clock and write times as you observe them; do not estimate
   afterwards.

## Session record

| Field | Value |
|---|---|
| Observer name (human) | |
| Participant identifier (no personal data needed) | |
| Participant's prior Android / Python experience (self-reported) | |
| Date | |
| Clock used (device, timezone) | |
| Session start time | |
| Session end time | |
| Host for the session (OS, chip; same as original host? yes/no) | |
| Archive identifier / manifest hash given to participant | |
| Device-step authorization reference, or "NOT AUTHORIZED" | |

## Step coverage

For each step record start/end time, outcome (DONE / STUCK / GAVE UP / NOT
ATTEMPTED), where they got stuck, and anything they misread.

| Step | Start | End | Outcome | Stuck point / notes |
|---|---|---|---|---|
| Read README.md | | | | |
| `python3 tools/check_local.py` | | | | |
| `python3 android/scripts/verify-toolchain.py` | | | | |
| `bash android/test-domain.sh` | | | | |
| `bash android/build.sh` | | | | |
| Reference export (runbook section 7) | | | | |
| Bootstrap new AVD (section 8) | | | | |
| Initialize new journal (section 9) | | | | |
| Dry run (section 10) | | | | |
| Admitted paired replay (section 10) | | | | |

Coverage summary (steps reached / steps attempted / steps in table): ___ / ___ / 10

## Unaided understanding questions

Ask after the steps, without showing the answers. Write the participant's own
words, not a paraphrase.

1. What is the difference between the original v3 pilot result (2/5) and the
   v4obs1 FINAL result (3/3)? Can they be added together?
   - Participant's words:
2. Why does B1 producing the same export as B3 (3/3 vs 3/3) not show that the
   model method is better, or that it is eligible/approved for anything?
   - Participant's words:
3. Why does a fresh build need `--admit-local-build`, and what does that flag
   prove and not prove?
   - Participant's words:
4. Is the "fixed" build a repair produced by ReproLoop?
   - Participant's words:
5. What would a CONFIRMED fresh replay show, and what would it NOT show?
   - Participant's words:

## Incorrect answers and misreadings (verbatim)

| Question / step | Exact words | Observer note on what was wrong |
|---|---|---|
| | | |

## Observer sign-off

- I observed this session in person or live, and did not assist: ______
- Observer signature / initials and time: ______

Until this form is filled by a real observer, the novice-readthrough gate stays
open and must be reported as NOT DONE.

## Separate demo-only entry point

For an actual novice watching only the recorded film, use NOVICE_DEMO_REVIEW.md
and keep NOVICE_DEMO_OBSERVER_GUIDE.md with the observer. No SDK/setup step is
required for that distinct comprehension check. Do not report either form as
executed merely because a package or questionnaire exists.
