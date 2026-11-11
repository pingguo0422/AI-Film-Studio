# Work Log — dev.16

1. Copied dev.15 into a separate dev.16 workspace; dev.15 was not modified.
2. Static review identified that the open-inbox refresh cleared the approved case detail and removed the execution button after approval.
3. Changed the post-decision refresh to select the resulting disposition status.
4. Changed the mocked inbox to honor the requested status filter and added assertions for selected detail retention and execution-button availability.
5. Added `AFS_CHROMIUM_EXECUTABLE` support to the live browser runner.
6. Hardened the GitHub Actions job with explicit read-only repository permissions and timeout.
7. Executed full pytest, mocked Chromium workflow, Python compilation, and JavaScript syntax checks.
8. Attempted the live browser-to-local-API workflow; Chromium navigation was blocked by the execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`), so no live browser acceptance is claimed.
