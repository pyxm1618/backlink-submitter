"""A first real request can establish its matcher; analytics cannot count as an attempt."""

import asyncio
import json

import pytest
from playwright.async_api import async_playwright
from test_contracts import submit_args

from backlink_submitter.contracts import submit_once


@pytest.mark.parametrize(
    "path,body,increment",
    [
        ("/api/new-listing", {"name": "WYRPlay", "url": "https://www.wyrplay.com/"}, 1),
        ("/analytics", {"name": "WYRPlay", "url": "https://www.wyrplay.com/"}, 0),
        ("/api/new-listing", {"event": "button_clicked"}, 0),
        ("/api/new-listing", "binary", 1),
    ],
)
def test_first_submit_discovers_only_identity_bound_business_request(tmp_path, path, body, increment):
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            context = await browser.new_context()
            await context.route("**/*", lambda route: route.fulfill(status=200, body="{}"))
            page = await context.new_page()
            await page.goto("https://site.example/submit")
            clicks = []

            async def click():
                clicks.append(1)
                await page.evaluate(
                    'async ([path,body])=>{await fetch(path,{method:"POST",body:body==="binary"?new Uint8Array([255,...new TextEncoder().encode("WYRPlay https://www.wyrplay.com/")]):JSON.stringify(body)})}',
                    [path, body],
                )

            journal = tmp_path / "intent.json"
            args = submit_args(journal, click, page=page, dispatch_timeout_ms=200)
            assert await submit_once(**args) == increment
            receipt = json.loads(journal.read_text())
            assert receipt["dispatch_confirmed"] is bool(increment)
            if increment:
                assert receipt["dispatch"]["path"] == path
            with pytest.raises(ValueError):
                await submit_once(**args)
            assert clicks == [1]
            await context.close()
            await browser.close()

    asyncio.run(run())
