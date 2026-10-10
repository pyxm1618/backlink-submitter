"""Boundary tests: only fixtures perform Submit/write; never real external mutations."""

import asyncio
import copy
import importlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def contract():
    assert importlib.util.find_spec("backlink_submitter.contracts") is not None, (
        "Migration contracts are not implemented"
    )
    return importlib.import_module("backlink_submitter.contracts")


def test_pack_loads_official_values_and_assets(contract):
    pack = contract.load_project("wyrplay", ROOT / "projects/wyrplay")
    assert pack["fields"]["Public Contact Email"] == "support@wyrplay.com"
    assert pack["manifest"]["identity"]["ai_product"] is False
    assert len(pack["screenshots"]) == 5
    assert pack["logo_svg"].is_file()


def test_unknown_project_fails_closed(contract):
    with pytest.raises(ValueError):
        contract.load_project("unknown", ROOT / "projects/wyrplay")


@pytest.mark.parametrize("term", ["Quick I Ching", "quickiching.com", "Divination", "TierListBase"])
def test_contamination_aborts_before_action(contract, term):
    calls = []

    async def click():
        calls.append("submit")

    with pytest.raises(ValueError):
        asyncio.run(
            contract.submit_once(
                ROOT / "unused-intent.json",
                payload={"name": term},
                click=click,
                project_id="wyrplay",
                prior_status="待提交",
                final_action=True,
                qualified=True,
                blacklisted=False,
                human_verification=False,
                missing_required=[],
            )
        )
    assert calls == []


def test_wrong_project_cannot_submit(contract, tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(
            contract.submit_once(
                tmp_path / "intent.json",
                payload={},
                click=None,
                project_id="other",
                prior_status="待提交",
                final_action=True,
                qualified=True,
                blacklisted=False,
                human_verification=False,
                missing_required=[],
            )
        )
    assert not (tmp_path / "intent.json").exists()


def valid_payload():
    return {"name": "WYRPlay", "url": "https://www.wyrplay.com/", "email": "support@wyrplay.com", "ai_product": False}


def submit_args(path, click, **extra):
    return dict(
        journal=path,
        payload=valid_payload(),
        click=click,
        project_id="wyrplay",
        prior_status="待提交",
        final_action=True,
        qualified=True,
        blacklisted=False,
        human_verification=False,
        missing_required=[],
        **extra,
    )


def test_once_survives_restarts_and_counts_true_submit(contract, tmp_path):
    calls = []

    class RequestPage:
        callback = None

        def on(self, name, callback):
            assert name == "request"
            self.callback = callback

        def remove_listener(self, name, callback):
            assert self.callback == callback
            self.callback = None

    page = RequestPage()

    async def click():
        from types import SimpleNamespace

        calls.append("submit")
        page.callback(SimpleNamespace(method="POST", url="https://site.example/api/submissions?token=fixture"))

    path = tmp_path / "intent.json"
    args = submit_args(
        path,
        click,
        page=page,
        submission_request={"verified": True, "method": "POST", "host": "site.example", "path": "/api/submissions"},
    )
    assert asyncio.run(contract.submit_once(**args)) == 1
    with pytest.raises(ValueError):
        asyncio.run(contract.submit_once(**submit_args(path, click)))
    assert calls == ["submit"]
    assert json.loads(path.read_text())["attempt_increment"] == 1


def test_nonfinal_click_does_not_submit_or_increment(contract, tmp_path):
    args = submit_args(tmp_path / "intent.json", None)
    args["final_action"] = False
    assert asyncio.run(contract.submit_once(**args)) == 0
    assert not (tmp_path / "intent.json").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("human_verification", True),
        ("missing_required", ["Funding"]),
        ("blacklisted", True),
        ("qualified", False),
        ("prior_status", "需人工核查"),
        ("prior_status", "历史未验证"),
        ("prior_status", "成功"),
        ("prior_status", "审核中"),
    ],
)
def test_boundary_stop_has_no_attempt(contract, tmp_path, field, value):
    args = submit_args(tmp_path / "intent.json", None)
    args[field] = value
    with pytest.raises(ValueError):
        asyncio.run(contract.submit_once(**args))
    assert not (tmp_path / "intent.json").exists()


def test_click_timeout_keeps_intent_and_prevents_retry(contract, tmp_path):
    async def click():
        raise TimeoutError("fixture timeout")

    path = tmp_path / "intent.json"
    with pytest.raises(TimeoutError):
        asyncio.run(contract.submit_once(**submit_args(path, click)))
    with pytest.raises(ValueError):
        asyncio.run(contract.submit_once(**submit_args(path, click)))
    assert json.loads(path.read_text())["state"] == "SUBMIT_DISPATCH_UNCONFIRMED"


@pytest.mark.parametrize(
    "before,after,submitted",
    [("", "", True), ("Pending review", "Pending review", True), ("", "Submission received", False)],
)
def test_no_new_bound_receipt_is_never_pending_or_success(contract, before, after, submitted):
    result = contract.classify(before, after, submitted=submitted)
    assert result["status"] not in {"审核中", "成功"}
    assert result["result_url"] == ""


@pytest.mark.parametrize("submitted,preexisting", [(True, False), (True, True), (False, False)])
def test_matchbox_review_receipt_requires_new_final_submission(contract, submitted, preexisting):
    receipt = (
        "You’re in - we’ll review your product, add it, and email you a link to claim and customise it, "
        "usually within a day."
    )
    result = contract.classify(receipt if preexisting else "Add my product", receipt, submitted=submitted)
    assert result["status"] == ("审核中" if submitted and not preexisting else "需人工核查" if submitted else "待提交")


def test_e1_new_receipt_only_pending(contract):
    result = contract.classify("Submit product", "Submission received", submitted=True)
    assert (result["status"], result["evidence_code"], result["result_url"]) == ("审核中", "E1", "")


def mail(**changes):
    item = {
        "message_id": "fixture-mail",
        "received_at": NOW.isoformat(),
        "sender": "verify@directory.example",
        "recipient": "support@wyrplay.com",
        "subject": "WYRPlay listing received",
        "body": "WYRPlay submission received for review",
    }
    item.update(changes)
    return item


def test_e2_official_new_confirmation(contract):
    proof = contract.email_pending(mail(), domain="directory.example", recipient="support@wyrplay.com", started_at=NOW)
    assert contract.classify("", "", submitted=True, proof=proof)["status"] == "审核中"
    assert "body" not in proof


@pytest.mark.parametrize(
    "changes",
    [
        {"received_at": "2026-10-08T11:59:59+00:00"},
        {"sender": "x@evildirectory.example"},
        {"recipient": "other@example.com"},
        {"body": "Your verification code is 123456", "subject": "Verification code"},
        {"body": "Other product listing received"},
    ],
)
def test_e2_rejects_unbound_or_otp_mail(contract, changes):
    assert (
        contract.email_pending(
            mail(**changes), domain="directory.example", recipient="support@wyrplay.com", started_at=NOW
        )
        is None
    )


def test_e3_requires_new_unique_wyrplay_tracking(contract):
    proof = contract.tracking_pending(
        "https://directory.example/submission/123",
        "WYRPlay submission 123 pending",
        previous_url="https://directory.example/submit",
        submitted=True,
        domain="directory.example",
    )
    result = contract.classify("", "", submitted=True, proof=proof)
    assert (result["status"], result["evidence_code"], result["result_url"]) == (
        "审核中",
        "E3",
        "https://directory.example/submission/123",
    )
    assert (
        contract.tracking_pending(
            "https://directory.example/dashboard",
            "WYRPlay",
            previous_url="",
            submitted=True,
            domain="directory.example",
        )
        is None
    )


def test_unknown_mandatory_reports_owner_gap_not_platform_failure(contract):
    pack = contract.load_project("wyrplay", ROOT / "projects/wyrplay")
    gap = contract.field_value(
        pack,
        "Founder",
        required=True,
        platform="StartupFound",
        why="Founder structure required",
        possible_values=["Solo", "Multiple"],
    )
    assert gap["code"] == "OWNER_INPUT_REQUIRED"
    assert gap["field"] == "Founder"
    assert contract.field_value(pack, "Founder", required=False, platform="StartupFound") == ""
    assert contract.field_value(pack, "Operator / Legal Owner", required=True, platform="x") == "Wang Yufei"


@pytest.mark.parametrize(
    "changes",
    [
        {"received_at": "2026-10-08T11:59:59+00:00"},
        {"sender": "a@evil.example"},
        {"recipient": "wrong@example.com"},
        {"body": "Order number 123456"},
        {"body": "Your verification code is 12345"},
    ],
)
def test_otp_rejects_old_unrelated_or_wrong_length(contract, changes):
    m = mail(
        subject="Email verification",
        body="Your verification code is 123456",
        **{k: v for k, v in changes.items() if k != "body"},
    )
    m.update(changes)
    assert (
        contract.extract_otp(m, domain="directory.example", recipient="support@wyrplay.com", requested_at=NOW, length=6)
        is None
    )


def test_otp_stays_memory_only_and_redacted(contract, capsys):
    secret = contract.extract_otp(
        mail(subject="Verification", body="Your verification code is 123456"),
        domain="directory.example",
        recipient="support@wyrplay.com",
        requested_at=NOW,
        length=6,
    )
    assert secret.value == "123456"
    assert "123456" not in repr(secret)
    out = capsys.readouterr()
    assert out.out == out.err == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"otp": "123456"},
        {"cookie": "private"},
        {"url": "https://a.example/?access_token=secret"},
        {"notes": "Your verification code is 123456"},
        {"password": "hidden"},
        {"api_key": "fixture-private-key"},
        {"notes": "Authorization: Bearer fixture-private-token"},
    ],
)
def test_secrets_rejected_before_artifact_write(contract, tmp_path, payload):
    with pytest.raises(ValueError):
        contract.save_evidence(tmp_path / "evidence.json", payload)
    assert not (tmp_path / "evidence.json").exists()


class SheetAPI:
    def __init__(self, project="wyrplay", backlink="site.example", corrupt=False):
        self.row = [project, backlink, "site.example", "待提交", "", "", "https://www.wyrplay.com/", "", "", ""]
        self.writes = 0
        self.corrupt = corrupt
        self.blacklist = [["外链ID", "平台域名"]]

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kw):
        if kw["range"] == "黑名单!A:B":
            self.response = {"values": copy.deepcopy(self.blacklist)}
            return self
        assert kw["range"] == "外链管理!A2:J2"
        assert kw["spreadsheetId"] == "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"
        self.response = {"values": [copy.deepcopy(self.row)]}
        if self.corrupt and self.writes:
            self.response["values"][0][8] = "changed by another writer"
        return self

    def update(self, **kw):
        assert kw["range"] == "外链管理!D2:J2"
        assert kw["valueInputOption"] == "RAW"
        self.row[3:10] = kw["body"]["values"][0]
        self.writes += 1
        self.response = {"updatedCells": 7}
        return self

    def execute(self):
        return self.response


def sheets():
    return importlib.import_module("backlink_submitter.sheets")


@pytest.mark.parametrize("project,backlink", [("other", "site.example"), ("wyrplay", "wrong.example")])
def test_sheet_refuses_joint_key_mismatch(contract, project, backlink):
    api = SheetAPI(project, backlink)
    with pytest.raises(ValueError):
        sheets().write_outcome(
            api,
            2,
            "site.example",
            contract.classify("", "", submitted=True),
            reason="unconfirmed",
            summary="NO_EVIDENCE",
        )
    assert api.writes == 0


def test_sheet_preserves_blank_attempt_and_exact_readback(contract):
    api = SheetAPI()
    actual = sheets().write_outcome(
        api, 2, "site.example", contract.classify("", "", submitted=True), reason="unconfirmed", summary="NO_EVIDENCE"
    )
    assert actual == api.row
    assert actual[4] == ""
    assert actual[7:] == ["", "unconfirmed", "NO_EVIDENCE"]
    with pytest.raises(ValueError):
        sheets().write_outcome(
            SheetAPI(corrupt=True),
            2,
            "site.example",
            contract.classify("", "", submitted=True),
            reason="x",
            summary="NO_EVIDENCE",
        )


@pytest.mark.parametrize(
    "result",
    [
        {"status": "成功", "evidence_code": "", "result_url": ""},
        {"status": "审核中", "evidence_code": "", "result_url": ""},
        {"status": "需人工核查", "evidence_code": "", "result_url": "https://site.example/dashboard"},
    ],
)
def test_sheet_rejects_evidence_less_status_and_general_result_url(contract, result):
    api = SheetAPI()
    with pytest.raises(ValueError):
        sheets().write_outcome(api, 2, "site.example", result, reason="x", summary="x")
    assert api.writes == 0


def test_sheet_rejects_secret_summary(contract):
    api = SheetAPI()
    with pytest.raises(ValueError):
        sheets().write_outcome(
            api, 2, "site.example", contract.classify("", "", submitted=True), reason="x", summary="OTP: 123456"
        )
    assert api.writes == 0


def test_real_anonymous_e4_and_bad_pages(contract):
    async def run():
        from playwright.async_api import async_playwright

        from backlink_submitter.browser import verify_listing

        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            original = browser.new_context

            async def fresh(**options):
                assert "storage_state" not in options
                ctx = await original(**options)
                await ctx.route(
                    "https://fixture.example/**",
                    lambda route: route.fulfill(
                        status=200,
                        headers={"X-Robots-Tag": "noindex"},
                        content_type="text/html",
                        body=(
                            '<title>WYRPlay listing</title><h1>WYRPlay</h1><a rel="nofollow ugc" href="https://www.wyrplay.com/">Play</a>'
                            if route.request.url.endswith("/products/wyrplay")
                            else "<title>WYRPlay</title><h1>WYRPlay</h1>"
                        ),
                    ),
                )
                return ctx

            browser.new_context = fresh
            try:
                proof = await verify_listing(browser, "https://fixture.example/products/wyrplay")
                result = contract.classify("", "", submitted=True, proof=proof)
                assert result["status"] == "成功"
                assert proof["indexability"] == "noindex"
                assert proof["links"][0]["rel"] == "nofollow ugc"
                for path in ["/preview/wyrplay", "/search?q=WYRPlay", "/products/no-link", "/dashboard/wyrplay"]:
                    assert await verify_listing(browser, "https://fixture.example" + path) is None
            finally:
                await browser.close()

    asyncio.run(run())


def test_sheet_attempt_increment_requires_matching_single_use_receipt(contract, tmp_path):
    api = SheetAPI()
    result = contract.classify("", "", submitted=True)
    with pytest.raises(ValueError):
        sheets().write_outcome(
            api, 2, "site.example", result, reason="uncertain", summary="NO_EVIDENCE", attempt_increment=1
        )
    assert api.writes == 0
    receipt = tmp_path / "intent.json"
    receipt.write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "site.example",
                "prior_attempts": "",
                "attempt_increment": 1,
                "dispatch_confirmed": True,
                "dispatch": {"method": "POST", "host": "site.example", "path": "/api/submissions"},
            }
        )
    )
    sheets().write_outcome(
        api,
        2,
        "site.example",
        result,
        reason="uncertain",
        summary="NO_EVIDENCE",
        attempt_increment=1,
        attempt_receipt=receipt,
    )
    assert api.row[4] == "1"
    with pytest.raises(ValueError):
        sheets().write_outcome(
            api,
            2,
            "site.example",
            result,
            reason="uncertain",
            summary="NO_EVIDENCE",
            attempt_increment=1,
            attempt_receipt=receipt,
        )
    assert api.writes == 1


def test_invalid_live_proof_cannot_make_dashboard_success(contract):
    proof = {
        "project_id": "wyrplay",
        "evidence_code": "E4",
        "anonymous": True,
        "public_verified": True,
        "authentic_listing": True,
        "links": [{"href": "https://evil.example", "rel": "dofollow"}],
        "listing_url": "https://site.example/dashboard/wyrplay",
        "title": "WYRPlay dashboard",
    }
    assert contract.classify("", "", submitted=True, proof=proof)["status"] == "需人工核查"


def test_blacklist_is_checked_by_platform_key_or_domain(contract):
    api = SheetAPI()
    api.blacklist.append(["platform-id", "site.example"])
    assert sheets().is_blacklisted(api, "platform-id", "different.example") is True
    assert sheets().is_blacklisted(api, "another-id", "www.site.example") is True
    assert sheets().is_blacklisted(api, "unknown-id", "other.example") is False
