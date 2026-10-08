"""Readonly official discovery; fixtures never dispatch a real submission."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from backlink_submitter.contracts import load_project

FORM = """<h1>Submit your product for free</h1><p>We accept games and web applications. No account required.</p>
<form id="listing" method="post" action="/api/listings">
<label for="product">Product name</label><input id="product" required>
<input name="website" placeholder="Website URL" required>
<label for="category">Category</label><select id="category" required><option>Games</option><option>AI</option></select>
<button id="final" type="submit">Submit product</button></form>"""


async def fixture_discover(tmp_path, html=FORM, *, entry="https://site.example/submit", routes=None):
    from backlink_submitter.discovery import discover

    pack = load_project("wyrplay", Path("projects/wyrplay"))
    pack = dict(pack, root=tmp_path)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(service_workers="block")
        requested = []

        async def route(r):
            requested.append((r.request.method, r.request.url))
            await r.fulfill(content_type="text/html", body=(routes or {}).get(r.request.url, html))

        await ctx.route("**/*", route)
        page = await ctx.new_page()
        try:
            result = await discover(page, pack, {"domain": "site.example", "submit_url": entry})
        finally:
            await ctx.close()
            assert browser.contexts == []
            await browser.close()
        return result, requested


def test_native_adapter_semantics_and_existing_gate(tmp_path):
    from backlink_submitter.batch import adapter_gate

    result, requests = asyncio.run(fixture_discover(tmp_path))
    assert result["outcome"] == "READY_TO_SUBMIT"
    adapter = json.loads((tmp_path / "adapters/site.example.json").read_text())
    assert adapter["fields"] == {"Product / App Name": '[id="product"]', "Website URL": '[name="website"]'}
    assert adapter["submission_request"] == {
        "method": "POST",
        "host": "site.example",
        "path": "/api/listings",
        "verified": True,
    }
    assert adapter["automatic_submit_allowed"] is False
    assert adapter_gate(adapter, load_project("wyrplay", Path("projects/wyrplay"))) is None
    assert all(method == "GET" for method, _ in requests)
    assert adapter["provenance"]["dispatch_evidence"]["kind"] == "native_form"


def test_observed_link_only_and_no_guessed_paths(tmp_path):
    home = '<a href="/real-entry">Add product</a><a href="https://other.example/submit">Submit</a>'
    result, requests = asyncio.run(
        fixture_discover(
            tmp_path, entry="", routes={"https://site.example/": home, "https://site.example/real-entry": FORM}
        )
    )
    assert result["outcome"] == "READY_TO_SUBMIT"
    assert [url for _, url in requests] == ["https://site.example/", "https://site.example/real-entry"]
    other, requests = asyncio.run(fixture_discover(tmp_path / "other", "<h1>Welcome</h1>", entry=""))
    assert other["reason"] == "OFFICIAL_SUBMIT_URL_UNCONFIRMED"
    assert requests == [("GET", "https://site.example/")]


@pytest.mark.parametrize(
    "extra,expected",
    [
        ('<input name="founder" required>', "OWNER_INPUT_REQUIRED"),
        ('<input aria-label="Mystery fact" required>', "OWNER_INPUT_REQUIRED"),
    ],
)
def test_unknown_required_is_owner_input(tmp_path, extra, expected):
    result, _ = asyncio.run(fixture_discover(tmp_path, FORM.replace("</form>", extra + "</form>")))
    assert result["outcome"] == expected
    assert not (tmp_path / "adapters/site.example.json").exists()


@pytest.mark.parametrize(
    "html,reason",
    [
        ("<h1>Verify you are human</h1>", "HUMAN_VERIFICATION_REQUIRED"),
        ("<h1>Sign in to submit your product</h1>", "OWNER_LOGIN_REQUIRED"),
    ],
)
def test_human_login_classification(tmp_path, html, reason):
    result, _ = asyncio.run(fixture_discover(tmp_path, html))
    assert result["outcome"] == "HUMAN_VERIFICATION_REQUIRED" and result["reason"] == reason


@pytest.mark.parametrize(
    "html,outcome",
    [
        ("<p>We only accept AI tools.</p>", "NOT_APPLICABLE"),
        ("<p>All submissions require payment. No free submissions.</p>", "GLOBAL_BLACKLIST"),
        ("<p>This service has permanently closed.</p>", "GLOBAL_BLACKLIST"),
        ("<p>We are a private blog network selling backlinks.</p>", "GLOBAL_BLACKLIST"),
        ("<p>Pricing starts at $10.</p>", "需人工核查"),
    ],
)
def test_positive_qualification_not_inversion(tmp_path, html, outcome):
    result, _ = asyncio.run(fixture_discover(tmp_path, html))
    assert result["outcome"] == outcome


def test_bound_official_js_handler_and_unknown_matcher(tmp_path):
    js = """<script>document.querySelector('#listing').addEventListener('submit', async (event) => {event.preventDefault(); await fetch('/api/create', {method: 'POST'});});</script>"""
    html = FORM.replace('method="post" action="/api/listings"', "")
    result, _ = asyncio.run(fixture_discover(tmp_path, html + js))
    assert result["outcome"] == "READY_TO_SUBMIT"
    adapter = json.loads((tmp_path / "adapters/site.example.json").read_text())
    assert adapter["submission_request"]["path"] == "/api/create"
    other, _ = asyncio.run(
        fixture_discover(tmp_path / "unknown", html + '<script>fetch("/unbound", {method:"POST"})</script>')
    )
    assert other["reason"] == "DISPATCH_MATCHER_UNVERIFIED"


def test_existing_adapter_never_overwritten(tmp_path):
    directory = tmp_path / "adapters"
    directory.mkdir()
    path = directory / "site.example.json"
    path.write_text('{"existing":true}')
    result, _ = asyncio.run(fixture_discover(tmp_path))
    assert result["reason"] == "ADAPTER_REVIEW_REQUIRED"
    assert path.read_text() == '{"existing":true}'


def test_discovery_blocks_page_write_requests(tmp_path):
    script = """<script>for(const method of ['POST','PUT','PATCH','DELETE'])fetch('/probe',{method}).catch(()=>{});</script>"""
    result, requests = asyncio.run(fixture_discover(tmp_path, FORM + script))
    assert result["reason"] == "DISPATCH_MATCHER_UNVERIFIED"
    assert all(method == "GET" for method, _ in requests)


def test_missing_adapter_enters_existing_worker_and_human_queue(tmp_path, monkeypatch):
    from test_contracts import SheetAPI

    from backlink_submitter import batch_worker as worker

    @asynccontextmanager
    async def context(pw, profile):
        async with worker.site_context_original(pw, profile) as ctx:
            await ctx.route("**/*", lambda r: r.fulfill(content_type="text/html", body="<h1>Verify you are human</h1>"))
            yield ctx

    monkeypatch.setattr(worker, "site_context_original", worker.site_context, raising=False)
    monkeypatch.setattr(worker, "site_context", context)
    pack = dict(load_project("wyrplay", Path("projects/wyrplay")), root=tmp_path)
    job = {
        "project_id": "wyrplay",
        "backlink_id": "site.example",
        "domain": "site.example",
        "row": 2,
        "submit_url": "https://site.example/submit",
        "mode": "dry-run",
        "runtime_root": str(tmp_path / "runtime"),
        "evidence_dir": str(tmp_path / "evidence"),
    }
    api = SheetAPI()
    api.row = ["wyrplay", "site.example", "site.example", "", "", "", "", "", "", ""]

    async def run():
        async with async_playwright() as pw:
            return await worker.run_site(job, pack, api, pw)

    result = asyncio.run(run())
    assert result["outcome"] == "HUMAN_VERIFICATION_REQUIRED"
    assert (tmp_path / "runtime/human-queue/site.example.json").exists()
    assert api.writes == 0


def test_generated_ready_uses_existing_authorization_dispatch_and_submit_once(tmp_path):
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import execute_ready, prepare_form

    result, _ = asyncio.run(fixture_discover(tmp_path))
    assert result["outcome"] == "READY_TO_SUBMIT"
    adapter = json.loads((tmp_path / "adapters/site.example.json").read_text())
    pack = load_project("wyrplay", Path("projects/wyrplay"))

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context()
            dispatched = []

            async def route(r):
                if r.request.method == "POST":
                    dispatched.append(r.request.url)
                    await r.fulfill(content_type="text/html", body="<h1>WYRPlay submission received</h1>")
                else:
                    await r.fulfill(content_type="text/html", body=FORM)

            await ctx.route("**/*", route)
            page = await ctx.new_page()
            await page.goto(adapter["submit_url"])
            await prepare_form(page, adapter, pack)
            api = SheetAPI()
            job = {
                "mode": "dry-run",
                "runtime_root": str(tmp_path / "runtime"),
                "backlink_id": "site.example",
                "domain": "site.example",
                "row": 2,
                "runtime_approved": False,
                "approval_expires_at": "2999-01-01T00:00:00+00:00",
            }
            with pytest.raises(ValueError, match="runtime Owner"):
                await execute_ready(page, adapter, pack, api, job)
            assert dispatched == []
            job.update(mode="live", runtime_approved=True)
            result = await execute_ready(page, adapter, pack, api, job)
            assert result["outcome"] == "PENDING" and api.row[4] == "1"
            with pytest.raises(ValueError):
                await execute_ready(page, adapter, pack, api, job)
            assert dispatched == ["https://site.example/api/listings"]
            assert adapter["automatic_submit_allowed"] is False
            await ctx.close()
            assert browser.contexts == []
            await browser.close()

    asyncio.run(run())


def test_negated_policy_is_not_global_blacklist(tmp_path):
    result, _ = asyncio.run(
        fixture_discover(
            tmp_path, "<p>Not all submissions require payment. No free submissions are advertised here.</p>"
        )
    )
    assert result["outcome"] != "GLOBAL_BLACKLIST"


def test_same_domain_only_navigation(tmp_path):
    result, requests = asyncio.run(
        fixture_discover(tmp_path, '<a href="https://other.example/submit">Submit product</a>', entry="")
    )
    assert result["reason"] == "OFFICIAL_SUBMIT_URL_UNCONFIRMED"
    assert requests == [("GET", "https://site.example/")]


def test_existing_handoff_worker_entry_routes_only_explicit_single_job(tmp_path, monkeypatch):
    from playwright import async_api

    from backlink_submitter import batch_worker as worker

    calls = []

    @asynccontextmanager
    async def playwright():
        yield object()

    async def handoff(job, api, pw):
        calls.append(job["backlink_id"])
        assert job["owner_human_action"] is True and job["resume"] is True
        return {"outcome": "需人工核查", "reason": "HUMAN_ACTION_FINISHED_RECHECK_REQUIRED", "submit": 0}

    monkeypatch.setattr(async_api, "async_playwright", playwright)
    monkeypatch.setattr(worker, "handoff", handoff)
    monkeypatch.setattr(worker, "service", lambda writable=False: object())
    job = {
        "project_id": "wyrplay",
        "backlink_id": "site.example",
        "domain": "site.example",
        "mode": "handoff",
        "resume": True,
        "owner_human_action": True,
        "result_path": str(tmp_path / "result.json"),
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job))
    asyncio.run(worker.main(path))
    assert calls == ["site.example"]
    assert json.loads((tmp_path / "result.json").read_text())["submit"] == 0


def test_required_native_constraint_not_ready(tmp_path):
    result, _ = asyncio.run(
        fixture_discover(tmp_path, FORM.replace('id="product" required', 'id="product" required pattern="[0-9]+"'))
    )
    assert result["outcome"] == "OWNER_INPUT_REQUIRED"
    assert not (tmp_path / "adapters/site.example.json").exists()


def test_js_and_inline_override_cannot_prove_dispatch(tmp_path):
    html = FORM.replace('<form id="listing"', '<form onsubmit="event.preventDefault()" id="listing"')
    result, _ = asyncio.run(fixture_discover(tmp_path, html))
    assert result["reason"] == "DISPATCH_MATCHER_UNVERIFIED"


def test_native_taxonomy_does_not_bypass_existing_non_ai_guard():
    from backlink_submitter.batch_worker import prepare_form

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await page.set_content("<p>WYRPlay</p>")
            with pytest.raises(ValueError, match="TAXONOMY_UNVERIFIED"):
                await prepare_form(
                    page,
                    {
                        "fields": {},
                        "taxonomy": {
                            "native_select": True,
                            "category": "AI",
                            "option_text": "AI",
                            "selected_verified": True,
                        },
                    },
                    load_project("wyrplay", Path("projects/wyrplay")),
                )
            await ctx.close()
            await browser.close()

    asyncio.run(run())


def test_generated_adapter_reusable_when_master_entry_is_blank(tmp_path, monkeypatch):
    from test_contracts import SheetAPI

    from backlink_submitter import batch_worker as worker

    result, _ = asyncio.run(fixture_discover(tmp_path))
    assert result["outcome"] == "READY_TO_SUBMIT"
    original = worker.site_context

    @asynccontextmanager
    async def context(pw, profile):
        async with original(pw, profile) as ctx:
            await ctx.route("**/*", lambda r: r.fulfill(content_type="text/html", body=FORM))
            yield ctx

    monkeypatch.setattr(worker, "site_context", context)
    pack = dict(load_project("wyrplay", Path("projects/wyrplay")), root=tmp_path)
    job = {
        "project_id": "wyrplay",
        "backlink_id": "site.example",
        "domain": "site.example",
        "row": 2,
        "submit_url": "",
        "mode": "dry-run",
        "runtime_root": str(tmp_path / "runtime"),
        "evidence_dir": str(tmp_path / "evidence"),
    }
    api = SheetAPI()

    async def run():
        async with async_playwright() as pw:
            return await worker.run_site(job, pack, api, pw)

    result = asyncio.run(run())
    assert result["outcome"] == "READY_TO_SUBMIT"
    assert api.writes == 0


def test_native_option_verified_is_not_claim_of_current_selection(tmp_path):
    html = FORM.replace("<option>Games</option>", '<option value="">Choose</option><option>Gaming</option>')
    result, _ = asyncio.run(fixture_discover(tmp_path, html))
    assert result["outcome"] == "READY_TO_SUBMIT"
    adapter = json.loads((tmp_path / "adapters/site.example.json").read_text())
    assert adapter["taxonomy"]["option_verified"] is True
    assert adapter["taxonomy"]["selected_verified"] is False
