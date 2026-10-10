"""Real Chromium checks for the four bounded LIVE repairs; fixtures are not production evidence."""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from backlink_submitter.contracts import load_project, submit_once
from backlink_submitter.workflow import submission_response, validate_final_form


def test_required_radio_category_upload_and_errors_before_final(tmp_path):
    async def run():
        pack = load_project("wyrplay", Path("projects/wyrplay"))
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            page = await browser.new_page()
            await page.set_content("""<form><input id=name value=WYRPlay><input id=url value="https://www.wyrplay.com/">
            <input type=radio name=ownership required><input type=radio name=ownership checked>
            <label>Games<input type=checkbox name=categories value=games></label>
            <input id=logo type=file required><div id=error role=alert>Category required</div><button id=final>Submit Product</button></form>""")
            adapter = {
                "domain": "site.example",
                "fields": {"Product / App Name": "#name", "Website URL": "#url"},
                "final_submit_selector": "#final",
            }
            with pytest.raises(ValueError, match="FORM_VALIDATION_UNRESOLVED"):
                await validate_final_form(page, adapter, pack, repair=True)
            assert await page.locator("input[name=categories]").is_checked()
            await page.locator("#logo").set_input_files(str(pack["logo_svg"]))
            await page.locator("#error").evaluate("e=>e.remove()")
            assert (await validate_final_form(page, adapter, pack))["native_valid"]
            assert not list(tmp_path.glob("*intent*"))
            await browser.close()

    asyncio.run(run())


def test_native_multipart_first_submit_and_once(tmp_path):
    from test_contracts import submit_args

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            page = await browser.new_page()
            await page.route(
                "**/*",
                lambda r: r.fulfill(
                    content_type="text/html",
                    body="<h1>Submission received</h1>"
                    if r.request.method == "POST"
                    else '<form method=post action=/submit enctype=multipart/form-data><input name=name value=WYRPlay><input name=url value="https://www.wyrplay.com/"><input id=file name=image type=file><button id=final>Submit Product</button></form>',
                ),
            )
            await page.goto("https://site.example/submit")
            await page.locator("#file").set_input_files(
                {"name": "image.bin", "mimeType": "application/octet-stream", "buffer": bytes([255, 0, 128])}
            )
            args = submit_args(
                tmp_path / "intent.json", lambda: page.locator("#final").click(), page=page, dispatch_timeout_ms=1000
            )
            assert await submit_once(**args) == 1
            with pytest.raises(ValueError):
                await submit_once(**args)
            await browser.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,payload,accepted",
    [
        (200, {"status": "pending"}, True),
        (422, {"status": "pending", "errors": {"category": "required"}}, False),
        (200, {"success": False, "message": "submission received"}, False),
    ],
)
def test_json_receipt_requires_bound_business_response(status, payload, accepted):
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            page = await browser.new_page()
            await page.route("**/*", lambda r: r.fulfill(status=status, json=payload))
            await page.goto("https://site.example/submit")
            async with page.expect_response("https://site.example/api/listings") as pending:
                await page.evaluate(
                    '()=>fetch("/api/listings",{method:"POST",body:JSON.stringify({name:"WYRPlay",url:"https://www.wyrplay.com/"})})'
                )
            result = await submission_response(await pending.value, "site.example", "")
            assert bool(result.get("receipt_marker")) is accepted
            assert await submission_response(await pending.value, "foreign.example", "") is None
            await browser.close()

    asyncio.run(run())


def test_owner_platform_login_keeps_public_contact_separate():
    from test_automatic_progress import browser_case

    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.gmail_connector import ConnectedGmail

    async def invoke(operation, arguments):
        assert operation == "new_account_password"
        return {"value": "fixture-only-credential", "email": "owner@example.com"}

    async def check(page):
        pack = load_project("wyrplay", Path("projects/wyrplay"))
        connector = ConnectedGmail(invoke)
        await connector.new_account_password("site.example")
        counts = {}
        assert (
            await automatic_authentication(page, pack, AuthGuard("site.example"), connector=connector, counters=counts)
            is None
        )
        assert await page.evaluate("window.loginEmail") == "owner@example.com"
        assert pack["fields"]["Public Contact Email"] == "support@wyrplay.com"
        assert counts["automatic_login"] == 1

    asyncio.run(
        browser_case(
            "<h1>Login</h1><form onsubmit=\"event.preventDefault();window.loginEmail=this.email.value;this.outerHTML='<a href=/logout>Logout</a>'\"><input type=email name=email><input type=password name=password><button>Login</button></form>",
            check,
        )
    )
