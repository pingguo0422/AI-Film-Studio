# Code Review — AFS Foundation 1.5 dev.16

## Finding fixed

**Severity: High — approval-to-execution workflow became unusable in the UI.**

`submitDecision()` rendered the approved decision detail and then refreshed the inbox using the current `open` filter. The newly approved case was absent from that filtered result, and `loadInbox()` cleared the selected ID and detail panel. This removed the second explicit execution control immediately after approval. The dev.15 live browser test expected that control to remain visible, but the mocked inbox always returned the case regardless of the requested status and therefore did not model the production filter behavior.

**Fix:** switch the inbox filter to the disposition status before refreshing. This keeps the selected case in the returned result and preserves its detail/actions. The mocked browser test now implements status-aware filtering and explicitly asserts the approved case and execution control remain available.

## Additional harness improvement

The live browser runner now accepts `AFS_CHROMIUM_EXECUTABLE`, allowing a system Chromium installation to be selected. This does not bypass browser network policy; the local environment still blocks browser navigation to its local FastAPI server.

## CI hardening

Added explicit `contents: read` permission and a 30-minute job timeout. No production credentials or external secrets are introduced.

## Review boundary

This increment changes only Control Center post-decision selection behavior, browser test fidelity/configuration, and CI job permissions/timeout. It does not change authorization policy, database schema, action execution semantics, or Agent scheduling.
