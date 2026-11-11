#!/usr/bin/env python3
"""Fail early with a focused diagnostic if the Playwright Chromium binary cannot launch."""
from __future__ import annotations

import os
import sys
from playwright.sync_api import Error, sync_playwright


def main() -> int:
    executable = os.getenv("AFS_CHROMIUM_EXECUTABLE") or None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()
            page.set_content("<title>AFS Chromium Smoke Check</title><p>ready</p>")
            assert page.title() == "AFS Chromium Smoke Check"
            assert page.locator("p").inner_text() == "ready"
            browser.close()
    except (Error, AssertionError, OSError) as exc:
        print("PLAYWRIGHT_CHROMIUM_LAUNCH: FAIL", file=sys.stderr)
        print(f"Executable override: {executable or '(Playwright-managed Chromium)'}", file=sys.stderr)
        print(f"Diagnostic: {exc}", file=sys.stderr)
        return 1

    print("PLAYWRIGHT_CHROMIUM_LAUNCH: PASS")
    print("- Chromium launched headlessly")
    print("- A local page rendered and DOM assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
