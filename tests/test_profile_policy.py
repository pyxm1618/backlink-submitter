"""Offline profile, authentication-order and display-only safety checks."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backlink_submitter.browser import browser_session, isolated_profile
from backlink_submitter.candidates import action_result
from backlink_submitter.sheets import human_reason, write_display


@pytest.mark.parametrize(
    "path",
    [
        "~/Library/Application Support/Google/Chrome",
        "~/Library/Application Support/Google/Chrome/Default",
        "~/Library/Application Support/Google/Chrome/Profile 2",
        "~/Library/Application Support/Tabbit",
        "~/Library/Application Support/Tabbit/Profile 1",
        "~/.backlink-autofill/Default",
    ],
)
def test_personal_profiles_rejected_before_browser_launch(path):
    launch = AsyncMock()

    async def run():
        with pytest.raises(ValueError, match="AUTOMATION_PROFILE_FORBIDDEN"):
            async with browser_session(
                SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch)), profile=path
            ):
                pytest.fail("must not open personal data")

    asyncio.run(run())
    launch.assert_not_called()


def test_profile_symlink_cannot_reach_personal_data(tmp_path):
    alias = tmp_path / "automation"
    alias.symlink_to(Path.home() / "Library/Application Support/Google/Chrome")
    with pytest.raises(ValueError, match="AUTOMATION_PROFILE_FORBIDDEN"):
        isolated_profile(alias)
    assert (
        isolated_profile("~/.backlink-autofill/browser-profile")
        == Path("~/.backlink-autofill/browser-profile").expanduser().resolve()
    )


def test_unavailable_google_session_does_not_click_or_retry(monkeypatch):
    from test_automatic_progress import browser_case

    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.contracts import load_project

    check_session = AsyncMock(return_value=False)
    monkeypatch.setattr("backlink_submitter.automation.google_session_available", check_session)

    async def check(page):
        guard = AuthGuard("site.example")
        for _ in range(2):
            result = await automatic_authentication(page, load_project("wyrplay", Path("projects/wyrplay")), guard)
            assert result["reason"] == "GOOGLE_SESSION_UNAVAILABLE"
        assert await page.evaluate("window.clicks") == 0

    asyncio.run(
        browser_case(
            '<button onclick="window.clicks++">Continue with Google</button><script>window.clicks=0</script>', check
        )
    )
    assert check_session.await_count == 1


@pytest.mark.parametrize(
    "challenge",
    [
        "Verify it's you",
        "Suspicious activity",
        "Unusual traffic",
        "Recovery",
        "Confirm your device",
        "Enter authenticator code",
        '<input type="password">',
        "CAPTCHA",
    ],
)
def test_google_risk_stops_and_closes_oauth(challenge):
    from test_automatic_progress import browser_case

    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.contracts import load_project

    async def check(page):
        await page.goto("https://accounts.google.com/challenge")
        guard = AuthGuard("site.example")
        guard.oauth_active = True
        result = await automatic_authentication(page, load_project("wyrplay", Path("projects/wyrplay")), guard)
        assert result["reason"] == "GOOGLE_RISK_VERIFICATION"
        assert page.is_closed() and guard.oauth_stopped and not guard.oauth_active
        assert not guard.navigation_allowed("https://accounts.google.com/signin")
        assert not guard.permits("POST", "https://accounts.google.com/signin", {})

    asyncio.run(browser_case(challenge, check))


def test_email_authentication_precedes_google(monkeypatch):
    from test_automatic_progress import browser_case

    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.contracts import load_project

    check_session = AsyncMock(return_value=True)
    monkeypatch.setattr("backlink_submitter.automation.google_session_available", check_session)

    async def check(page):
        guard = AuthGuard("site.example")
        await automatic_authentication(page, load_project("wyrplay", Path("projects/wyrplay")), guard)
        assert await page.evaluate("window.method") == "email"
        check_session.assert_not_called()

    asyncio.run(
        browser_case(
            """<form onsubmit="event.preventDefault();window.method='email';this.remove();document.querySelector('#google').remove()"><input type=email><button>Send magic link</button></form><button id=google onclick="window.method='google'">Continue with Google</button><script>window.method='none'</script>""",
            check,
        )
    )


@pytest.mark.parametrize(
    "reason,status",
    [
        ("RECIPROCAL_REQUIRED", "去人工"),
        ("AUTOMATED_ACCESS_FORBIDDEN", "去人工"),
        ("PAYMENT_ONLY_FOR_CURRENT_PATH", "暂时不可用"),
    ],
)
def test_execution_conditions_are_not_project_rejection(reason, status):
    result = action_result({"outcome": "NOT_APPLICABLE", "reason": reason}, {"kind": "official_entry"})
    assert result["action_status"] == status and result["coverage"] == "deferred"


@pytest.mark.parametrize(
    "code",
    [
        "Phase MANUAL_REVIEW",
        "QUALIFIED_A LOGIN_REQUIRED",
        "ADAPTER_REVIEW_REQUIRED",
        "DISPATCH_MATCHER_UNVERIFIED",
        "callback host:3000",
        "automation_pending",
    ],
)
def test_sheet_notes_hide_engineering_labels(code):
    import re

    note = human_reason("暂时不可用", code)
    assert not re.search(
        r"Phase|MANUAL_REVIEW|QUALIFIED_|ADAPTER_|matcher|callback host|automation_pending", note, re.I
    )


def test_display_write_preserves_business_fields(monkeypatch, tmp_path):
    # Use the existing in-memory Sheets fixture; no control-plane request.
    prior = [
        "wyrplay",
        "fazier.com",
        "fazier.com",
        "不适用",
        "",
        "old-time",
        "https://www.wyrplay.com/",
        "",
        "RECIPROCAL_REQUIRED",
        "old evidence",
    ]

    class Call:
        def __init__(self, value):
            self.value = value

        def execute(self):
            return self.value

    class Values:
        def get(self, **kwargs):
            return Call({"values": [list(prior)]})

        def batchUpdate(self, **kwargs):
            for entry in kwargs["body"]["data"]:
                col = 3 if "!D" in entry["range"] else 8
                prior[col] = entry["values"][0][0]
            return Call({})

    api = SimpleNamespace(spreadsheets=lambda: SimpleNamespace(values=lambda: Values()))
    monkeypatch.setenv("HOME", str(tmp_path))
    old = list(prior)
    got = write_display(
        api, 2, "fazier.com", reason="暂未提交：免费收录要求换链，本轮未做换链。", status="去人工", expected_prior=old
    )
    assert got[:3] == old[:3] and got[4:8] == old[4:8] and got[9] == old[9]
    assert list(tmp_path.rglob("*.json"))


def test_existing_platform_session_never_starts_google(monkeypatch):
    from test_automatic_progress import browser_case

    from backlink_submitter.automation import AuthGuard, automatic_authentication
    from backlink_submitter.contracts import load_project

    session = AsyncMock(return_value=True)
    monkeypatch.setattr("backlink_submitter.automation.google_session_available", session)

    async def check(page):
        assert (
            await automatic_authentication(
                page, load_project("wyrplay", Path("projects/wyrplay")), AuthGuard("site.example")
            )
            is None
        )
        assert await page.evaluate("window.clicks") == 0

    asyncio.run(
        browser_case(
            '<a href="/logout">Log out</a><button onclick="window.clicks++">Continue with Google</button><script>window.clicks=0</script>',
            check,
        )
    )
    session.assert_not_called()


def test_cookie_presence_is_not_google_session_proof(monkeypatch, tmp_path):
    from backlink_submitter.automation import google_session_available

    monkeypatch.setenv("HOME", str(tmp_path))
    probe = SimpleNamespace(goto=AsyncMock(), close=AsyncMock())
    locator = SimpleNamespace(
        inner_text=AsyncMock(return_value="Sign in"),
        all=AsyncMock(return_value=[]),
        evaluate_all=AsyncMock(return_value=""),
    )
    probe.url = "https://accounts.google.com/"
    probe.locator = lambda selector: locator
    context = SimpleNamespace(
        _backlink_profile=str(tmp_path / ".backlink-autofill/browser-profile"),
        cookies=AsyncMock(return_value=[{"name": "SID", "value": "fixture-only"}]),
        new_page=AsyncMock(return_value=probe),
    )
    page = SimpleNamespace(context=context)
    assert not asyncio.run(google_session_available(page, expected_email="fixture@example.test"))
    assert not asyncio.run(google_session_available(page, expected_email="fixture@example.test"))
    assert context.new_page.await_count == 1
    probe.close.assert_awaited_once()


def test_google_risk_pause_survives_new_context(monkeypatch, tmp_path):
    from backlink_submitter.automation import google_session_available, pause_google

    monkeypatch.setenv("HOME", str(tmp_path))
    profile = str(tmp_path / ".backlink-autofill/browser-profile")
    pause_google(SimpleNamespace(_backlink_profile=profile))
    context = SimpleNamespace(_backlink_profile=profile, cookies=AsyncMock(), new_page=AsyncMock())
    assert not asyncio.run(
        google_session_available(SimpleNamespace(context=context), expected_email="fixture@example.test")
    )
    context.cookies.assert_not_called()
    context.new_page.assert_not_called()


def test_old_stages_do_not_override_current_note():
    assert "付费" not in human_reason("去人工", "[Phase 2] Free $0，付费仅加速\n[本次行动] 网站要求人机验证")
    assert "AI 工具" not in human_reason("不适用", "Official domains lists only; privacy mail links")
    assert "本轮未重新验证" in human_reason("成功", "historical imported success")


@pytest.mark.parametrize("failure", [None, "prior_changed", "wrong_readback", "protected_state"])
def test_bounded_display_batch_preserves_protected_fields(monkeypatch, tmp_path, failure):
    from copy import deepcopy

    from backlink_submitter.sheets import write_display_batch

    monkeypatch.setenv("HOME", str(tmp_path))
    rows = [
        [
            "wyrplay",
            "fazier.com",
            "fazier.com",
            "不适用",
            "",
            "old-time",
            "https://www.wyrplay.com/",
            "",
            "RECIPROCAL_REQUIRED",
            "old evidence",
        ],
        [
            "wyrplay",
            "vuink.com",
            "vuink.com",
            "需人工核查",
            "1",
            "submit-time",
            "https://www.wyrplay.com/",
            "",
            "SUBMIT_RESULT_UNCONFIRMED",
            "submit proof",
        ],
    ]
    original = deepcopy(rows)
    writes = []
    reads = []

    class Call:
        def __init__(self, value):
            self.value = value

        def execute(self):
            return self.value

    class Values:
        def batchGet(self, **kwargs):
            reads.append(kwargs["ranges"])
            snapshot = deepcopy(rows)
            if failure == "prior_changed" and not writes:
                snapshot[0][1] = "another.example"
            if failure == "wrong_readback" and writes:
                snapshot[1][4] = "2"
            return Call({"valueRanges": [{"values": [row]} for row in snapshot]})

        def batchUpdate(self, **kwargs):
            writes.append(kwargs["body"])
            for change in kwargs["body"]["data"]:
                column = 3 if "!D" in change["range"] else 8
                index = 0 if change["range"].endswith("2") else 1
                rows[index][column] = change["values"][0][0]
            return Call({})

    api = SimpleNamespace(spreadsheets=lambda: SimpleNamespace(values=lambda: Values()))
    changes = [
        {
            "row": 2,
            "backlink_id": "fazier.com",
            "expected_prior": original[0],
            "reason": "暂未提交：免费路径要求换链。",
            "status": "去人工",
        },
        {"row": 3, "backlink_id": "vuink.com", "expected_prior": original[1], "reason": "已提交待核实，禁止重复提交。"},
    ]
    if failure == "protected_state":
        changes[1]["status"] = "暂时不可用"
    if failure:
        with pytest.raises(ValueError):
            write_display_batch(api, changes)
        assert len(writes) == (1 if failure == "wrong_readback" else 0)
    else:
        result = write_display_batch(api, changes)
        assert len(writes) == 1 and len(reads) == 2
        for before, after in zip(original, result, strict=True):
            assert before[:3] == after[:3] and before[4:8] == after[4:8] and before[9] == after[9]
        assert result[1][3] == original[1][3]
        assert len(list(tmp_path.rglob("*.json"))) == 2


@pytest.mark.parametrize("expected_email,available", [("fixture@example.test", True), ("other@example.test", False)])
def test_google_session_requires_positive_matching_account(monkeypatch, tmp_path, expected_email, available):
    from backlink_submitter.automation import google_session_available

    monkeypatch.setenv("HOME", str(tmp_path))
    empty = SimpleNamespace(all=AsyncMock(return_value=[]))
    positive = SimpleNamespace(
        all=AsyncMock(return_value=[SimpleNamespace(is_visible=AsyncMock(return_value=True))]),
        evaluate_all=AsyncMock(return_value="Google Account: fixture@example.test"),
    )
    body = SimpleNamespace(inner_text=AsyncMock(return_value="fixture@example.test"))
    probe = SimpleNamespace(url="https://accounts.google.com/", goto=AsyncMock(), close=AsyncMock())
    probe.locator = lambda selector: (
        body if selector == "body" else positive if selector.startswith("a[href") else empty
    )
    context = SimpleNamespace(
        _backlink_profile=str(tmp_path / ".backlink-autofill/browser-profile"),
        cookies=AsyncMock(return_value=[{"name": "SID", "value": "fixture-only"}]),
        new_page=AsyncMock(return_value=probe),
    )
    assert (
        asyncio.run(google_session_available(SimpleNamespace(context=context), expected_email=expected_email))
        is available
    )
    probe.close.assert_awaited_once()
