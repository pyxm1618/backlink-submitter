"""Recovery, readonly batch planning and explicitly Owner-scoped execution entry point."""

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
    parser = argparse.ArgumentParser(
        description="WYRPlay preflight/batch; dry-run default, LIVE needs an external Owner grant"
    )
    parser.add_argument("command", choices=["preflight", "batch", "resume", "handoff", "human-loop"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--read-sheet", action="store_true")
    parser.add_argument("--browser-smoke", action="store_true")
    parser.add_argument("--mode", choices=["dry-run", "live"], default="dry-run")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-after")
    parser.add_argument("--owner-approval", type=Path)
    parser.add_argument("--backlink-id")
    parser.add_argument("--owner-human-action", action="store_true")
    parser.add_argument(
        "--mail-stdio", action="store_true", help="Use host connected Gmail via ephemeral stdin replies"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        pack = load_project(args.project, root / "projects/wyrplay")
        if args.command == "human-loop":
            from .human_loop import human_loop

            if args.mode != "dry-run" or args.backlink_id or args.owner_approval or args.start_after:
                raise ValueError("Human loop only verifies; LIVE requires separate scoped resume")
            report = asyncio.run(human_loop(pack, owner_human_action=args.owner_human_action, limit=args.limit or 1))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command != "preflight":
            from .batch import run_batch

            if args.command in {"resume", "handoff"} and not args.backlink_id:
                raise ValueError("Resume/handoff must target one backlink key")
            if args.command == "batch" and args.backlink_id:
                raise ValueError("Single key belongs to resume/handoff, not arbitrary row selection")
            connector = None
            if args.mail_stdio:
                from .gmail_connector import ConnectedGmail, stdio_invoke

                connector = ConnectedGmail(stdio_invoke)
            report = asyncio.run(
                run_batch(
                    pack,
                    mode="handoff" if args.command == "handoff" else args.mode,
                    concurrency=args.concurrency,
                    limit=args.limit,
                    start_after=args.start_after,
                    approval=args.owner_approval,
                    resume_key=args.backlink_id,
                    owner_human_action=args.owner_human_action,
                    connector=connector,
                )
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
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
                    "command": args.command,
                    "result": "FAIL",
                    "error_type": type(exc).__name__,
                    "action": "Inspect safe runtime evidence; preserve intents; never retry Submit blindly",
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
