# L3.09 session resume — local/offline corrective evidence

Date: 2026-08-13. Bead: `boulderroller-v2-f4acp.2.9`.

Evidence class: **local/offline simulator**. This is not a deployed or
physical-device claim. The prior production-read symptom was a process-kill
relaunch landing on onboarding; this pass reproduced its two-refresh failure
deterministically without using a live account.

## Exact inherited finding

Foreground `AppSession.resume()` and background upload reconciliation can both
resume the process session. The existing task coalesced overlapping calls, but
a caller arriving just after the first flight completed started a second token
rotation. The retained red test produced:

```text
refresh flight succeeded (attempt 1)
refresh flight failed (attempt 1): rejected(expired)
testColdStartResumeUsesOneRotationAcrossOverlappingAndSequentialCallers FAILED
```

The unsigned iPhone 17 simulator host returned Security status `-34018`
(`errSecMissingEntitlement`) for refresh-token read, delete, add, and update.
That explains why a `CODE_SIGNING_ALLOWED=NO` test build cannot durably adopt a
rotated token through Keychain. No token values were logged.

## Corrected outcome

- A process that already adopted an access token reuses that session instead
  of rotating again for a later cold-start caller.
- Concurrent callers still share the existing single flight.
- Refresh-token replacement uses `SecItemUpdate` first, eliminating the
  signed-build delete/add process-kill window.
- DEBUG simulator builds use the existing debug-only `UserDefaults` fallback
  when Security returns `-34018`; signed device and TestFlight builds do not
  compile that fallback.

Green command:

```text
xcodebuild -project BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO \
  -only-testing:BoulderRollerTests/SessionOperationsTests test
```

Result: **18/18 passed**, including one request for overlapping plus sequential
cold-start callers and persisted rotation from generation 1 to generation 2.
