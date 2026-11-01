# Fresh-AVD reference setup v1: INCOMPLETE, no retry

This is a separate same-Mac setup observation, not a new FINAL evaluation,
video inference, independent-machine result or change to the historical cohorts.
The owner explicitly authorized one new owned target and a FINAL-C reference
faulty/fixed pair. No Meta call was authorized or made.

## Recorded result

- New private AVD booted; fresh rooted journal initialized once, generation1.
- Developer-authored B1 export SHA-256: `0f2185d91acb8e96ca33339e8dc517a0458aedb674c522bf458a935dae7d565d`.
- Faulty APK SHA-256: `0b73a42129468b8617f1516c5c5b704d38a5880ac7b5ab02bca6e5e9348aeef6`.
- Fixed APK SHA-256 (not executed): `b9a4ffa2335ebc324e6924c2b2e9def4bf5cc5573936599420f84681f880de45`.
- Faulty attempted1, complete0: `RuntimeStop: malformed hierarchy`.
- Fixed attempted0. Complete pairs0. ReproLoop model calls0.
- Setup install/clear/explicit reset commands3 ACCEPTED; accepted app taps0.
- Journal read-only reconciliation: actions empty, no PENDING/UNKNOWN, run
  retired and lease cancelled. No row reset, deletion or second run occurred.

## Two actual fresh-setup findings

1. The trusted emulator rewrites config spacing and finalizes its private
   data-partition size on first boot. The old bootstrap pinned before boot,
   so fresh initialization correctly rejected its stale pin before creating a
   journal. The same newly owned boot was verified read-only; the initial
   receipt and exact created bytes/pin were retained, then its config was
   finalized with the new helper. Future bootstrap now keeps
   created_config_sha256 and pins config_sha256 AFTER boot/owner verification.
   The original operational bootstrap/journal were not changed.
2. Android displayed its first-use "Viewing full screen" / "Got it" system
   overlay. The hierarchy belonged to package android, not the fixture app.
   The existing safety validator correctly rejected it before the first app
   input. Do NOT loosen package validation or silently skip this overlay.

## Source/evidence boundary

The launch and replay executable base was963380a3bfef7a10b73fd630c7f37ac87561f7ec;
config finalization used the separately preserved bootstrap patch. Full
pre/post bootstrap receipts, config diff, raw XML, trace and private journal
receipts are retained outside the source-only archive. Source hashes/records
are not producer/OS attestation. Later MIT/doc changes are not a new native run.

Any explicit system-help acknowledgment and extra paired attempt need their
own exact owner authority; retain this failed attempt and a new generation,
never reset/copy the journal or relabel this result as a success. A successful
setup continuation would still not be an independent machine or human study.
