"""Continuation must prove AUTH/verification separately from business Submit."""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from backlink_submitter.contracts import load_project


def test_unknown_rows_and_prior_review_use_execution_order(tmp_path):
    from test_batch import snapshot

    from backlink_submitter.batch import select_candidates

    s = snapshot()
    for m in s["master"][1:]:
        m[2] = ""
    s["master"][1:] = reversed(s["master"][1:])
    s["execution"][5][3] = "去人工"
    items = select_candidates(s, tmp_path)
    assert [x["row"] for x in items] == sorted(x["row"] for x in items)
    unknown = next(x for x in items if x["backlink_id"] == "unknown.example")
    assert unknown["process"] and unknown["channel_basis"] is None
    assert next(x for x in items if x["backlink_id"] == "human.example")["process"]


def test_email_asterisk_name_and_fieldset_are_known():
    from backlink_submitter.discovery import semantic_field

    control = {
        "labels": ["Email *"],
        "name": "wpforms[fields][4]",
        "placeholder": "",
        "aria": "",
        "legend": "Contact details",
        "id": "email",
    }
    assert semantic_field(control) == "Public Contact Email"


def test_technical_limits_not_owner_work():
    from backlink_submitter.candidates import action_result

    for reason in [
        "OWNER_LOGIN_REQUIRED",
        "FINAL_SELECTOR_UNVERIFIED",
        "DISPATCH_MATCHER_UNVERIFIED",
        "UNMAPPED_REQUIRED_FIELDS",
        "ADAPTER_REVIEW_REQUIRED",
    ]:
        r = action_result({"outcome": "需人工核查", "reason": reason}, {"kind": "official_entry"})
        assert r["action_status"] == "暂时不可用" and r["automation_pending"]


async def browser_case(html, check):
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(service_workers="block")

        async def route(r):
            await r.fulfill(content_type="text/html", body=html)

        await ctx.route("**/*", route)
        page = await ctx.new_page()
        await page.goto("https://site.example/login")
        try:
            return await check(page)
        finally:
            await ctx.close()
            await browser.close()


@pytest.mark.parametrize(
    "html,reason",
    [
        ('<input type="password">', "OWNER_PASSWORD_REQUIRED"),
        ("<h1>Enter authenticator code</h1>", "OWNER_2FA_REQUIRED"),
        ("<h1>Verify you are human</h1>", "HUMAN_VERIFICATION_REQUIRED"),
    ],
)
def test_real_owner_boundaries(html, reason):
    from backlink_submitter.automation import owner_boundary

    assert asyncio.run(browser_case(html, owner_boundary))["reason"] == reason


def test_auth_unknown_final_allows_only_observed_auth_post():
    from backlink_submitter.automation import AuthGuard

    async def run(page):
        guard = AuthGuard("site.example")
        await guard.observe(page)
        guard.phase = "AUTH"
        assert guard.permits("POST", "https://site.example/session", {"email": "support@wyrplay.com"})
        assert not guard.permits(
            "POST", "https://site.example/session", {"email": "support@wyrplay.com", "product": "WYRPlay"}
        )
        assert not guard.permits("POST", "https://site.example/api/listings", {"email": "support@wyrplay.com"})
        guard.phase = "FINAL_SUBMIT"
        assert not guard.permits("POST", "https://site.example/session", {"email": "support@wyrplay.com"})

    asyncio.run(
        browser_case(
            '<form method="post" action="/session"><label>Email</label><input name="email" type="email"><button>Sign in</button></form>',
            run,
        )
    )


def test_oauth_link_is_observed_not_guessed():
    from backlink_submitter.automation import AuthGuard

    async def run(page):
        guard = AuthGuard("site.example")
        await guard.observe(page)
        assert guard.navigation_allowed(
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc&redirect_uri=https%3A%2F%2Fsite.example%2Fcallback&response_type=code"
        )
        assert not guard.navigation_allowed(
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=evil&redirect_uri=https%3A%2F%2Fevil.example%2Fcallback"
        )

    asyncio.run(
        browser_case(
            '<a href="https://accounts.google.com/o/oauth2/v2/auth?client_id=abc&amp;redirect_uri=https%3A%2F%2Fsite.example%2Fcallback&amp;response_type=code">Continue with Google</a>',
            run,
        )
    )


def test_multi_step_continue_client_side_never_dispatches_final(tmp_path):
    from test_discovery import FORM, fixture_discover

    html = (
        FORM.replace('<form id="listing"', '<form hidden id="listing"')
        + '<button id="next" type="button" onclick="document.getElementById(\'listing\').hidden=false;this.remove()">Continue</button>'
    )
    result, requests = asyncio.run(fixture_discover(tmp_path, html))
    assert result["outcome"] == "READY_TO_SUBMIT"
    assert result["automatic_steps"] == 1
    assert all(method == "GET" for method, _ in requests)


def test_otp_and_magic_link_strict_connector_binding():
    from backlink_submitter.automation import mailbox_challenge

    started = "2026-10-09T03:00:00+00:00"
    message = {
        "message_id": "1",
        "sender": "auth@site.example",
        "recipient": "support@wyrplay.com",
        "received_at": started,
        "subject": "Verification code",
        "body": "Verification code: 123456",
    }

    async def connector(operation, arguments):
        if operation == "get_profile":
            return {"email": "support@wyrplay.com"}
        if operation == "search_messages":
            return [message]
        raise AssertionError(operation)

    otp = asyncio.run(
        mailbox_challenge(
            connector, domain="site.example", recipient="support@wyrplay.com", started_at=started, length=6
        )
    )
    assert otp.value == "123456" and "123456" not in repr(otp)
    message.update(subject="Magic link sign in", body="Sign in: https://site.example/auth/verify?token=secret")
    link = asyncio.run(
        mailbox_challenge(
            connector, domain="site.example", recipient="support@wyrplay.com", started_at=started, length=None
        )
    )
    assert link.value.startswith("https://site.example/auth/verify") and "secret" not in repr(link)
    message["recipient"] = "other@example.com"
    assert (
        asyncio.run(
            mailbox_challenge(
                connector, domain="site.example", recipient="support@wyrplay.com", started_at=started, length=None
            )
        )
        is None
    )


def test_existing_authenticated_form_does_not_login_again():
    from backlink_submitter.automation import AuthGuard, automatic_authentication

    async def run(page):
        result = await automatic_authentication(
            page, load_project("wyrplay", Path("projects/wyrplay")), AuthGuard("site.example")
        )
        assert result is None

    asyncio.run(browser_case('<form><input name="website"><button>Submit product</button></form>', run))


def test_bound_react_and_xhr_are_proof_unbound_text_is_not():
    from backlink_submitter.handler_proof import matcher_from_handler

    for h in [
        "function(e){e.preventDefault();fetch('/api/listings',{method:'POST',body:JSON.stringify(v)})}",
        "function(e){e.preventDefault();const x=new XMLHttpRequest();x.open('POST','/api/listings');x.send(v)}",
    ]:
        assert matcher_from_handler(h, "https://site.example/submit", "site.example")[0]["path"] == "/api/listings"
    assert matcher_from_handler("const endpoint='/api/listings'", "https://site.example/submit", "site.example") is None


def test_native_form_ignores_unrelated_scripts_but_bound_override_blocks(tmp_path):
    from test_discovery import FORM, fixture_discover

    r, _ = asyncio.run(fixture_discover(tmp_path, FORM + "<script>globalThis.analytics=true;</script>"))
    assert r["outcome"] == "READY_TO_SUBMIT"
    r, _ = asyncio.run(
        fixture_discover(
            tmp_path / "override",
            FORM
            + "<script>document.querySelector('#listing').addEventListener('submit', e=>e.preventDefault());</script>",
        )
    )
    assert r["reason"] == "DISPATCH_MATCHER_UNVERIFIED"


def test_ordinary_login_posts_only_auth_then_continues(tmp_path):
    from test_discovery import FORM

    from backlink_submitter.automation import AuthGuard, automatic_authentication

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(service_workers="block")
            requests = []

            async def route(r):
                requests.append((r.request.method, r.request.url))
                await r.fulfill(
                    content_type="text/html",
                    body=FORM
                    if r.request.method == "POST"
                    else '<form method="post" action="/session"><input name="email" type="email"><button>Sign in</button></form>',
                )

            await ctx.route("**/*", route)
            page = await ctx.new_page()
            await page.goto("https://site.example/login")
            guard = AuthGuard("site.example")
            await page.route("**/*", guard.route)
            counters = {}
            try:
                assert (
                    await automatic_authentication(
                        page, load_project("wyrplay", Path("projects/wyrplay")), guard, counters=counters
                    )
                    is None
                )
                assert counters["automatic_login"] == 1
                assert requests == [("GET", "https://site.example/login"), ("POST", "https://site.example/session")]
            finally:
                await ctx.close()
                await browser.close()

    asyncio.run(run())


def test_oauth_normal_session_continues_without_password(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("backlink_submitter.automation.google_session_available", AsyncMock(return_value=True))
    from test_discovery import FORM

    from backlink_submitter.automation import AuthGuard, automatic_authentication

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(service_workers="block")
            oauth = "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc&redirect_uri=https%3A%2F%2Fsite.example%2Fcallback"

            async def route(r):
                if r.request.url.startswith("https://accounts.google.com/"):
                    await r.fulfill(
                        content_type="text/html", body="<script>location.href='https://site.example/callback'</script>"
                    )
                else:
                    await r.fulfill(
                        content_type="text/html",
                        body=FORM
                        if r.request.url.endswith("/callback")
                        else '<a href="' + oauth + '">Continue with Google</a>',
                    )

            await ctx.route("**/*", route)
            page = await ctx.new_page()
            await page.goto("https://site.example/login")
            guard = AuthGuard("site.example")
            await page.route("**/*", guard.route)
            counters = {}
            try:
                assert (
                    await automatic_authentication(
                        page, load_project("wyrplay", Path("projects/wyrplay")), guard, counters=counters
                    )
                    is None
                )
                assert counters["automatic_oauth"] == 1
            finally:
                await ctx.close()
                await browser.close()

    asyncio.run(run())


def test_connected_gmail_uses_existing_tools_only_and_parses_mime():
    import base64

    from backlink_submitter.gmail_connector import ConnectedGmail

    calls = []

    async def invoke(name, args):
        calls.append(name)
        if name == "gmail_get_profile":
            return {"structuredContent": {"emailAddress": "support@wyrplay.com"}}
        if name == "gmail_search_emails":
            return {"structuredContent": {"messages": [{"id": "1"}]}}
        return {
            "structuredContent": {
                "id": "1",
                "internalDate": "1791514800000",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "auth@site.example"},
                        {"name": "To", "value": "support@wyrplay.com"},
                        {"name": "Subject", "value": "Verification code"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(b"Verification code: 123456").decode()},
                },
            }
        }

    async def run():
        connector = ConnectedGmail(invoke)
        assert (await connector("get_profile", {}))["email"] == "support@wyrplay.com"
        messages = await connector(
            "search_messages", {"query": "to:support@wyrplay.com after:1791514800", "max_results": 10}
        )
        assert messages[0]["body"] == "Verification code: 123456"

    asyncio.run(run())
    assert calls == ["gmail_get_profile", "gmail_search_emails", "gmail_read_email"]


def test_captcha_password_two_factor_never_auto_click():
    from backlink_submitter.automation import AuthGuard, automatic_authentication

    async def check(page):
        g = AuthGuard("site.example")
        r = await automatic_authentication(page, load_project("wyrplay", Path("projects/wyrplay")), g)
        assert r["reason"] == "OWNER_2FA_REQUIRED" and g.auth_requests == 0

    asyncio.run(browser_case("<h1>Authenticator verification</h1><button>Continue</button>", check))


def test_google_alternative_before_password_not_false_owner_work():
    from backlink_submitter.automation import AuthGuard, automatic_authentication

    async def check(page):
        guard = AuthGuard("site.example")
        result = await automatic_authentication(page, load_project("wyrplay", Path("projects/wyrplay")), guard)
        assert result["reason"] == "GOOGLE_SESSION_UNAVAILABLE"
        assert result["outcome"] == "TEMPORARILY_UNAVAILABLE"

    asyncio.run(
        browser_case('<form><input type="password"><button type="button">Continue with Google</button></form>', check)
    )


def test_observed_captcha_transport_allowed_only_in_owner_auth_phase():
    from backlink_submitter.automation import AuthGuard

    async def check(page):
        guard = AuthGuard("site.example")
        await guard.observe(page)
        guard.phase = "VERIFICATION"
        assert guard.permits(
            "POST", "https://api.hcaptcha.com/checkcaptcha", {}, frame_url="https://newassets.hcaptcha.com/captcha/test"
        )
        assert not guard.permits(
            "POST", "https://site.example/api/listings", {}, frame_url="https://newassets.hcaptcha.com/captcha/test"
        )
        assert not guard.permits(
            "POST", "https://api.hcaptcha.com/checkcaptcha", {}, frame_url="https://other.example/"
        )

    asyncio.run(browser_case('<iframe src="https://newassets.hcaptcha.com/captcha/test"></iframe>', check))


def test_google_redirect_to_another_platform_is_blocked():
    from backlink_submitter.automation import AuthGuard

    g = AuthGuard("site.example")
    g.oauth_active = True
    assert not g.navigation_allowed(
        "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&redirect_uri=https%3A%2F%2Fevil.example%2Fcallback"
    )


def test_ordinary_terms_checkbox_is_automatically_resolved(tmp_path):
    from test_discovery import FORM, fixture_discover

    from backlink_submitter.candidates import action_result

    html = FORM.replace(
        "</form>", '<label><input type="checkbox" name="terms" required>I agree to the terms of service</label></form>'
    )
    result, _ = asyncio.run(fixture_discover(tmp_path, html))
    assert result["outcome"] == "READY_TO_SUBMIT"
    assert action_result(result)["action_status"] == "待提交"


def test_optional_password_widget_does_not_block_observed_submission_navigation(tmp_path):
    from test_discovery import FORM, fixture_discover

    html = '<a href="/submit">Submit product</a><form method="post" action="/session"><input type="password" name="password"><button>Sign in</button></form>'
    result, _ = asyncio.run(
        fixture_discover(
            tmp_path, entry="", routes={"https://site.example/": html, "https://site.example/submit": FORM}
        )
    )
    assert result["outcome"] == "READY_TO_SUBMIT"


def test_new_account_secret_only_fills_confirmed_creation():
    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.contracts import MemorySecret

    class Credentials:
        async def new_account_password(self, domain):
            assert domain == "site.example"
            return MemorySecret("fixture-only-secret")

    async def run(page):
        result = await automatic_authentication(
            page, {"fields": {}}, AuthGuard("site.example"), connector=Credentials()
        )
        assert result is None
        assert await page.locator('input[type="password"]').first.input_value() == "fixture-only-secret"

    asyncio.run(
        browser_case(
            '<h1>Create your account</h1><label>Password<input type="password"></label><label>Confirm password<input type="password"></label>',
            run,
        )
    )


def test_existing_password_not_replaced_by_new_account_secret():
    from backlink_submitter.automation import AuthGuard, automatic_authentication

    class Credentials:
        async def new_account_password(self, domain):
            raise AssertionError("Existing login must not request new-account credentials")

    async def run(page):
        result = await automatic_authentication(
            page, {"fields": {}}, AuthGuard("site.example"), connector=Credentials()
        )
        assert result["reason"] == "OWNER_PASSWORD_REQUIRED"
        assert await page.locator('input[type="password"]').input_value() == ""

    asyncio.run(browser_case('<h1>Login</h1><input type="password">', run))


def test_reactive_model_has_stable_semantic_selector():
    from backlink_submitter.automation import fill_known_controls
    from backlink_submitter.discovery import controls, selector_for

    async def run(page):
        control = (await controls(page, page))[0]
        selector = await selector_for(page, control)
        assert selector == '[wire\\:model="website_url"]'
        filled = await fill_known_controls(
            page, {"fields": {"Website URL": "https://www.wyrplay.com/"}}, "site.example"
        )
        assert filled == ["Website URL"]
        assert await page.locator(selector).input_value() == "https://www.wyrplay.com/"

    asyncio.run(browser_case('<input type="url" wire:model="website_url" placeholder="https://">', run))


def test_unchanged_next_is_not_reported_as_progress():
    from backlink_submitter.automation import AuthGuard, advance_local_step

    async def run(page):
        assert not await advance_local_step(page, {"fields": {}}, AuthGuard("site.example"))

    asyncio.run(browser_case("<button>Continue</button>", run))


def test_ebool_review_checks_actual_identity_and_free_plan():
    from backlink_submitter.batch import adapter_gate
    from backlink_submitter.ebool import review_adapter
    from backlink_submitter.workflow import fill_fields, verify_identity

    async def run(page):
        pack = {
            "fields": {
                "Product / App Name": "WYRPlay",
                "Website URL": "https://www.wyrplay.com/",
                "Public Contact Email": "support@wyrplay.com",
            }
        }
        adapter = await review_adapter(page, pack)
        assert adapter and adapter_gate(adapter, pack) is None
        await fill_fields(page, adapter, pack)
        await verify_identity(page, adapter, pack)
        await page.get_by_text("WYRPlay", exact=True).evaluate("e=>e.textContent='Another product'")
        assert await review_adapter(page, pack) is None

    asyncio.run(
        browser_case(
            "<h2>Review &amp; Submit</h2><div>Total due</div><div>Free</div><p>No payment required</p><div>WYRPlay</div><div>https://www.wyrplay.com/</div><div>support@wyrplay.com</div><button>Submit Listing</button>",
            run,
        )
    )


def test_binary_verification_transport_does_not_crash_or_grant_business():
    from backlink_submitter.automation import AuthGuard

    class Request:
        method = "POST"
        url = "https://www.google.com/recaptcha/api2/reload"
        headers = {"content-type": "application/octet-stream"}
        frame = type("Frame", (), {"url": "https://www.google.com/recaptcha/api2/anchor"})()

        def is_navigation_request(self):
            return False

        @property
        def post_data(self):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "binary verification payload")

    class Route:
        request = Request()
        allowed = False

        async def fallback(self):
            self.allowed = True

        async def abort(self):
            self.allowed = False

    async def run():
        guard = AuthGuard("site.example")
        guard.phase = "FINAL_SUBMIT"
        guard.verification_families.add("google-recaptcha")
        route = Route()
        await guard.route(route)
        assert route.allowed
        assert not guard.permits("POST", "https://evil.example/submit", None, frame_url=Request.frame.url)

    asyncio.run(run())


def test_authorized_new_account_registration_is_auth_only():
    from backlink_submitter.automation import AuthGuard

    guard = AuthGuard("site.example")
    guard.live = True
    guard.phase = "AUTH"
    guard.registration_active = True
    assert guard.permits(
        "POST",
        "https://site.example/api/register",
        {"name": "Wang Yufei", "email": "support@wyrplay.com", "password": "fixture-only"},
    )
    assert not guard.permits(
        "POST", "https://site.example/api/register", {"name": "WYRPlay", "website": "https://www.wyrplay.com/"}
    )
    assert not guard.permits("POST", "https://evil.example/register", {"email": "support@wyrplay.com"})


def test_registration_returning_to_login_reuses_memory_secret_once():
    from test_discovery import FORM

    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.contracts import MemorySecret

    class Credentials:
        calls = 0

        async def new_account_password(self, domain):
            self.calls += 1
            return MemorySecret("fixture-only-secret")

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(service_workers="block")
            requests = []

            async def route(r):
                requests.append((r.request.method, r.request.url))
                if r.request.url.endswith("/session"):
                    body = FORM
                elif r.request.url.endswith("/login"):
                    body = '<form method="post" action="/session"><input name="email" type="email"><input name="password" type="password"><button>Sign in</button></form><a href="/register">Sign up</a>'
                elif r.request.method == "POST":
                    assert "username=wyrplay" in r.request.post_data
                    body = '<script>location.href="/login"</script>'
                else:
                    body = '<h1>Create an account</h1><form method="post" action="/register"><input name="name"><input name="username" required pattern="[a-z]{3,24}"><input name="email" type="email"><input name="password" type="password"><button>Create an account</button></form>'
                await r.fulfill(content_type="text/html", body=body)

            await ctx.route("**/*", route)
            page = await ctx.new_page()
            await page.goto("https://site.example/register")
            guard = AuthGuard("site.example")
            guard.live = True
            await page.route("**/*", guard.route)
            credentials = Credentials()
            counters = {}
            try:
                assert (
                    await automatic_authentication(
                        page,
                        load_project("wyrplay", Path("projects/wyrplay")),
                        guard,
                        connector=credentials,
                        counters=counters,
                    )
                    is None
                )
                assert credentials.calls == 1
                assert [u for method, u in requests if method == "POST"] == [
                    "https://site.example/register",
                    "https://site.example/session",
                ]
                assert counters["automatic_login"] == 1
            finally:
                await ctx.close()
                await browser.close()

    asyncio.run(run())
