# AFS Foundation 1.5 dev.16 — Release Notes

**Version:** `1.5.0.dev16`  
**Baseline:** independent copy of `AFS_Foundation_1.5_dev.15`; dev.15 remains unchanged.

## Scope

Fix the Director Control Center approval-to-execution UI continuity defect discovered during the dev.15 acceptance-path review.

## Changes

1. After a successful human disposition, the inbox filter changes to the resulting status (`approved`, `rejected`, `deferred`, or `closed`) before refreshing. The selected decision case therefore remains visible and its detail panel is not cleared.
2. The mocked Chromium regression now applies the requested status filter to inbox results. It asserts that after approval the filter is `approved`, the approved case detail remains selected, and the second-confirmation execution button is still present.
3. The live Chromium runner accepts `AFS_CHROMIUM_EXECUTABLE`, matching the existing mocked runner and enabling use of a system-installed Chromium.
4. CI declares read-only `contents` permission and a 30-minute job timeout.

## Verification

See `TEST_REPORT_DEV16.md` and `BUILD_VERIFICATION_DEV16.log`.
