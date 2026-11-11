# Work Log — AFS Foundation 1.5 dev.17

1. Reviewed the GitHub Actions failure supplied by the user.
2. Identified setuptools flat-layout auto-discovery as the earliest failing step.
3. Created dev.17 as a separate copy from dev.16; dev.16 remains unchanged.
4. Added explicit setuptools package discovery for `backend` and `integrations`; excluded non-package directories.
5. Updated package and FastAPI app versions to `1.5.0.dev17`.
6. Executed editable package build/install checks, verified distribution extras and top-level packages.
7. Executed the full local pytest suite.
8. Recorded remaining remote acceptance requirements and environment limitations.
