"""Submission dispatch fixtures only; no live platforms or official Sheet writes."""

import asyncio
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright
from test_contracts import SheetAPI, submit_args

from backlink_submitter import contracts, sheets
from backlink_submitter.workflow import fill_fields, run_submission

ROOT = Path(__file__).resolve().parents[1]
MATCHER = {"verified": True, "method": "POST", "host": "site.example", "path": "/api/submissions"}


@pytest.mark.parametrize(
    "case,expected_increment,expected_status,expected_reason",
    [
        ("no_dispatch", 0, "需人工核查", "SUBMIT_DISPATCH_UNCONFIRMED"),
        ("html_validation", 0, "需人工核查", "SUBMIT_DISPATCH_UNCONFIRMED"),
        ("modal", 0, "需人工核查", "SUBMIT_DISPATCH_UNCONFIRMED"),
        ("fake_receipt", 0, "需人工核查", "SUBMIT_DISPATCH_UNCONFIRMED"),
        ("wrong_path", 0, "需人工核查", "SUBMIT_DISPATCH_UNCONFIRMED"),
        ("wrong_method", 0, "需人工核查", "SUBMIT_DISPATCH_UNCONFIRMED"),
        ("post_no_evidence", 1, "需人工核查", "SUBMIT_RESULT_UNCONFIRMED"),
        ("post_e1", 1, "审核中", "New post-submit page receipt verified"),
    ],
)
def test_actual_browser_dispatch_controls_attempt(tmp_path, case, expected_increment, expected_status, expected_reason):
    async def run():
        pack = contracts.load_project("wyrplay", ROOT / "projects/wyrplay")
        adapter = {
            "domain": "site.example",
            "submit_url": "https://site.example/submit",
            "fields": {"Product / App Name": "#name", "Website URL": "#url", "Public Contact Email": "#email"},
            "required_fields": [],
            "final_submit_selector": "#submit",
            "final_action_verified": True,
            "qualification": "QUALIFIED_A",
            "free_verified": True,
            "reciprocal_required": False,
            "automatic_submit_allowed": True,
            "submission_request": MATCHER,
            "dispatch_timeout_ms": 200,
        }
        url = "/api/unrelated" if case == "wrong_path" else "/api/submissions"
        method = "GET" if case == "wrong_method" else "POST"
        handler = "event.preventDefault();"
        if case in {"post_no_evidence", "post_e1", "wrong_path", "wrong_method"}:
            handler += f"fetch('{url}',{{method:'{method}'}})"
            if case == "post_e1":
                handler += ";document.getElementById('receipt').innerText='WYRPlay submission received';"
        if case == "fake_receipt":
            handler += "document.getElementById('receipt').innerText='WYRPlay submission received';"
        if case == "modal":
            handler += "document.getElementById('modal').hidden=false;"
        # Nonempty invalid type=email passes old required emptiness precheck but native validation blocks onsubmit.
        validation = '<input type=email required value="invalid-address">' if case == "html_validation" else ""
        html = f'''<title>Submit Product</title><form onsubmit="{handler}">
        <input id=name><input id=url><input id=email>{validation}
        <button id=submit type=submit>Submit Product</button></form>
        <p id=receipt></p><div id=modal hidden>Choose a launch option</div>'''
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            context = await browser.new_context(service_workers="block")

            async def route(request_route):
                if request_route.request.url.endswith("/submit"):
                    await request_route.fulfill(status=200, content_type="text/html", body=html)
                else:
                    await request_route.fulfill(status=200, content_type="application/json", body="{}")

            await context.route("https://site.example/**", route)
            page = await context.new_page()
            try:
                await page.goto(adapter["submit_url"])
                await fill_fields(page, adapter, pack)
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
                assert result["status"] == expected_status
                assert result["reason"] == expected_reason
                assert api.row[4] == ("1" if expected_increment else "")
                intent = json.loads((tmp_path / "submit-intents/wyrplay/site.example.json").read_text())
                assert intent["dispatch_confirmed"] is bool(expected_increment)
                assert intent["attempt_increment"] == expected_increment
                if expected_increment:
                    assert intent["dispatch"] == {"method": "POST", "host": "site.example", "path": "/api/submissions"}
                evidence = json.loads(next(tmp_path.glob("*/site.example/evidence.json")).read_text())
                assert evidence["attempt_increment"] == expected_increment
                assert evidence["dispatch_confirmed"] is bool(expected_increment)
                assert not any(k in json.dumps(intent) for k in ["request_body", "authorization", "cookie", "otp"])
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
            finally:
                await context.close()
                await browser.close()

    asyncio.run(run())


def test_sheet_rejects_legacy_click_only_receipt(tmp_path):
    api = SheetAPI()
    receipt = tmp_path / "intent.json"
    receipt.write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "site.example",
                "prior_attempts": "",
                "attempt_increment": 1,
                "click_dispatched": True,
            }
        )
    )
    with pytest.raises(ValueError):
        sheets.write_outcome(
            api,
            2,
            "site.example",
            contracts.classify("", "", submitted=True),
            reason="unknown",
            summary="NO_EVIDENCE",
            attempt_increment=1,
            attempt_receipt=receipt,
        )
    assert api.writes == 0


def test_click_without_observed_request_keeps_intent(tmp_path):
    async def click():
        return None

    path = tmp_path / "intent.json"
    assert asyncio.run(contracts.submit_once(**submit_args(path, click))) == 0
    assert json.loads(path.read_text())["state"] == "SUBMIT_DISPATCH_UNCONFIRMED"
    with pytest.raises(ValueError):
        asyncio.run(contracts.submit_once(**submit_args(path, click)))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_verified_dispatch_metadata_only_even_when_click_later_fails(tmp_path, method):
    class Request:
        url = "https://site.example/api/submissions?token=fixture-only"

        @property
        def headers(self):
            raise AssertionError("Request headers must not be read")

        @property
        def post_data(self):
            raise AssertionError("Request body must not be read")

    request = Request()
    request.method = method

    class Page:
        callback = None

        def on(self, name, callback):
            self.callback = callback

        def remove_listener(self, name, callback):
            self.callback = None

    page = Page()

    async def click():
        page.callback(request)
        raise TimeoutError("fixture click response timeout after request was issued")

    path = tmp_path / "intent.json"
    args = submit_args(path, click, page=page, submission_request={**MATCHER, "method": method})
    assert asyncio.run(contracts.submit_once(**args)) == 1
    receipt = json.loads(path.read_text())
    assert receipt["dispatch_confirmed"] is True
    assert receipt["dispatch"] == {"method": method, "host": "site.example", "path": "/api/submissions"}
    assert "fixture-only" not in path.read_text()
    assert page.callback is None


@pytest.mark.parametrize("extra", [{"body": "fixture"}, {"authorization": "fixture"}, {"cookie": "fixture"}])
def test_sheet_refuses_unsafe_dispatch_metadata(tmp_path, extra):
    api = SheetAPI()
    path = tmp_path / "intent.json"
    path.write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "site.example",
                "prior_attempts": "",
                "attempt_increment": 1,
                "dispatch_confirmed": True,
                "dispatch": {"method": "POST", "host": "site.example", "path": "/api/submissions", **extra},
            }
        )
    )
    with pytest.raises(ValueError):
        sheets.write_outcome(
            api,
            2,
            "site.example",
            contracts.classify("", "", submitted=True),
            reason="unknown",
            summary="NO_EVIDENCE",
            attempt_increment=1,
            attempt_receipt=path,
        )
    assert api.writes == 0
