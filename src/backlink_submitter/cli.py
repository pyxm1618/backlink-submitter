"""Read-only recovery entry point. Intentionally has no submit, login or write command."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .contracts import load_project
from .sheets import read_ledger, service


async def browser_smoke():
    from playwright.async_api import async_playwright

    from .browser import browser_session

    async with async_playwright() as playwright:
        async with browser_session(playwright) as context:
            page = await context.new_page()
            response = await page.goto("https://www.wyrplay.com/", wait_until="domcontentloaded", timeout=20000)
            agent = await page.evaluate("navigator.userAgent")
            return {
                "headless": "HeadlessChrome" in agent,
                "service_workers": "block",
                "http_status": response.status if response else None,
                "title": await page.title(),
                "anonymous": True,
                "profile_touched": False,
                "submit": 0,
            }


def main():
    parser = argparse.ArgumentParser(description="WYRPlay recovery/preflight only; no external mutation")
    parser.add_argument("command", choices=["preflight"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--read-sheet", action="store_true")
    parser.add_argument("--browser-smoke", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        pack = load_project(args.project, root / "projects/wyrplay")
        state = json.loads((pack["root"] / "canary_state.json").read_text())
        report = {
            "project_id": args.project,
            "manifest_version": pack["manifest"]["schema_version"],
            "pack": "PASS",
            "submit": 0,
            "attempt_increment": 0,
            "sheet_writes": 0,
            "functional_canary": state["functional_canary"],
            "ready_for_controlled_rollout": state["ready_for_controlled_rollout"],
            "canary_platforms": state["platforms"],
            "gmail": "OPTIONAL_CONNECTOR; no local OAuth",
            "sheet": "NOT_REQUESTED",
            "browser": "NOT_REQUESTED",
        }
        if args.read_sheet:
            report["sheet"] = read_ledger(service())
        if args.browser_smoke:
            report["browser"] = asyncio.run(browser_smoke())
            if report["browser"]["headless"] is not True or report["browser"]["http_status"] != 200:
                raise ValueError("Browser headless/public reachability preflight failed")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        # Raw provider exceptions can contain auth URLs, tokens or request bodies.
        print(
            json.dumps(
                {
                    "preflight": "FAIL",
                    "error_type": type(exc).__name__,
                    "action": "Check configuration/dependency externally; no Submit or write performed",
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
