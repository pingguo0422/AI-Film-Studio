# Work Log — dev.14

1. Copied dev.13 into a new dev.14 working directory; dev.13 remains unchanged.
2. Added an optional Playwright E2E dependency group.
3. Implemented a Chromium runner using the existing Control Center HTML/CSS/JS assets.
4. Environment restriction discovered: Chromium navigation to local HTTP and file origins returns `ERR_BLOCKED_BY_ADMINISTRATOR`. The runner therefore uses `page.set_content` and a deterministic in-page API mock. This still executes the actual browser UI and JavaScript, but does not claim live HTTP integration.
5. Browser test passed: project connection, inbox, action binding, approval, separate execution confirmation, result display and activity timeline.
6. Full pytest suite: 141 passed / 12 skipped.
7. Python compilation, JavaScript syntax, PostgreSQL shell syntax, SQLite migration/drift/downgrade/re-upgrade and PostgreSQL offline SQL generation passed.
8. HTTP smoke checks passed for health, control center and OpenAPI; health reports `1.5.0-dev.14`.
9. No live PostgreSQL service was available. The 12 PostgreSQL tests remain skipped.
10. Generated release documentation, verification artifacts, manifest and release archive.
