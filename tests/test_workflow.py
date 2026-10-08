"""Meaningful flow checks using an actual headless Chromium and fixture directory."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("after_screenshot_fails", [False, True])
def test_fixture_final_submit_upload_artifacts_sheet_and_once(tmp_path, after_screenshot_fails):
    assert importlib.util.find_spec("backlink_submitter.workflow") is not None, "Protected flow missing"
    from playwright.async_api import async_playwright
    from test_contracts import SheetAPI

    from backlink_submitter.contracts import load_project
    from backlink_submitter.workflow import fill_fields, run_submission

    async def run():
        pack = load_project("wyrplay", ROOT / "projects/wyrplay")
        adapter = {
            "domain": "site.example",
            "submit_url": "https://site.example/submit",
            "fields": {
                "Product / App Name": "#name",
                "Website URL": "#url",
                "Public Contact Email": "#email",
                "Short Description": "#desc",
            },
            "required_fields": ["Product / App Name", "Website URL"],
            "logo_selector": "#logo",
            "logo_format": "svg",
            "screenshots_selector": "#shots",
            "screenshot_limit": 5,
            "final_submit_selector": "#submit",
            "final_action_verified": True,
            "qualification": "QUALIFIED_A",
            "free_verified": True,
            "reciprocal_required": False,
            "automatic_submit_allowed": True,
            "submission_request": {
                "verified": True,
                "method": "POST",
                "host": "site.example",
                "path": "/api/submissions",
            },
            "dispatch_timeout_ms": 200,
        }
        html = """<title>Submit Product</title><form onsubmit="event.preventDefault();fetch('/api/submissions', {method:'POST'});document.body.innerHTML='<h1>WYRPlay submission received</h1>'">
        <input id=name><input id=url><input id=email><textarea id=desc></textarea>
        <input id=logo type=file><input id=shots type=file multiple><button id=submit type=submit>Submit Product</button></form>"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(service_workers="block")
            await ctx.route(
                "https://site.example/**", lambda route: route.fulfill(status=200, content_type="text/html", body=html)
            )
            page = await ctx.new_page()
            await page.goto(adapter["submit_url"])
            uploaded = await fill_fields(page, adapter, pack)
            assert uploaded == {"logo": True, "screenshots": 5}
            assert await page.locator("#name").input_value() == "WYRPlay"
            if after_screenshot_fails:
                original_screenshot = page.screenshot
                screenshots_called = 0

                async def screenshot(**kwargs):
                    nonlocal screenshots_called
                    screenshots_called += 1
                    if screenshots_called > 1:
                        raise TimeoutError("fixture after screenshot failure")
                    return await original_screenshot(**kwargs)

                page.screenshot = screenshot
            api = SheetAPI()
            result = await run_submission(
                page,
                adapter,
                pack,
                api,
                row=2,
                backlink_id="site.example",
                runtime=tmp_path,
                allow_submit=True,
                blacklisted=False,
            )
            assert result["status"] == ("需人工核查" if after_screenshot_fails else "审核中")
            assert api.row[4] == "1"
            assert api.row[7] == ""
            artifacts = list(tmp_path.glob("*/site.example/evidence.json"))
            assert len(artifacts) == 1
            evidence = json.loads(artifacts[0].read_text())
            assert evidence["evidence_code"] == ("" if after_screenshot_fails else "E1")
            assert evidence["attempt_increment"] == 1
            assert Path(evidence["screenshot_before"]).is_file()
            if not after_screenshot_fails:
                assert Path(evidence["screenshot_after"]).is_file()
            with pytest.raises(ValueError):
                await run_submission(
                    page,
                    adapter,
                    pack,
                    api,
                    row=2,
                    backlink_id="site.example",
                    runtime=tmp_path,
                    allow_submit=True,
                    blacklisted=False,
                )
            assert api.writes == 1
            await ctx.close()
            await browser.close()

    asyncio.run(run())


def test_schema_wrong_sheet_destination_is_rejected(tmp_path):
    from shutil import copytree

    from backlink_submitter.contracts import load_project

    pack = tmp_path / "pack"
    copytree(ROOT / "projects/wyrplay", pack)
    config = json.loads((pack / "project.json").read_text())
    config["spreadsheet_id"] = "wrong-sheet"
    (pack / "project.json").write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_project("wyrplay", pack)
