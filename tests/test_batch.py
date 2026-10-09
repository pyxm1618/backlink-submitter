"""Batch boundaries: official ledger joins, bounded workers and no unsafe repeat."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def batch():
    assert importlib.util.find_spec("backlink_submitter.batch") is not None, "Batch capability missing"
    from backlink_submitter import batch as module

    return module


def snapshot():
    master = [
        [
            "外链ID",
            "平台域名",
            "提交入口",
            "发现来源",
            "发现时间",
            "基础状态",
            "基础排除原因",
            "实测免费",
            "实测需登录",
            "实测登录方式",
            "实测限制",
            "实测链接属性",
            "最后验证时间",
            "平台备注",
            "状态",
            "淘汰原因",
            "平台类型",
            "获取方式",
        ]
    ]
    execution = [
        [
            "项目ID",
            "外链ID",
            "外链域名",
            "状态",
            "尝试次数",
            "最近操作时间",
            "目标URL",
            "结果链接",
            "原因/备注",
            "证据摘要",
        ]
    ]
    for key, status in [
        ("blocked.example", "待提交"),
        ("done.example", "成功"),
        ("pending.example", "审核中"),
        ("history.example", "历史未验证"),
        ("human.example", "需人工核查"),
        ("ready.example", "待提交"),
        ("unknown.example", ""),
    ]:
        master.append([key, key, "https://" + key + "/submit"])
        execution.append(["wyrplay", key, key, status, "", "", "https://www.wyrplay.com/"])
    execution.insert(1, ["other", "ready.example", "ready.example", "成功", "1"])
    return {"master": master, "blacklist": [master[0], ["blocked.example", "blocked.example"]], "execution": execution}


def test_join_uses_master_order_and_never_visits_blacklist_or_protected(tmp_path):
    items = batch().select_candidates(snapshot(), tmp_path)
    assert [x["backlink_id"] for x in items] == [
        "blocked.example",
        "done.example",
        "pending.example",
        "history.example",
        "human.example",
        "ready.example",
        "unknown.example",
    ]
    assert [x["process"] for x in items] == [False, False, False, False, True, True, True]
    assert items[5]["row"] == 8
    assert items[0]["outcome"] == "GLOBAL_BLACKLIST"
    assert items[1]["outcome"] == "SUCCESS"


def test_existing_attempt_intent_or_legacy_exclusion_is_deferred(tmp_path):
    s = snapshot()
    s["execution"][-1][4] = "1"
    p = tmp_path / "submit-intents/wyrplay/ready.example.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    items = batch().select_candidates(s, tmp_path)
    assert not items[-1]["process"] and not items[-2]["process"]
    s = snapshot()
    s["master"][-1] += ["", "", "失效", "historical timeout"]
    assert batch().select_candidates(s, tmp_path)[-1]["process"]


def test_invalid_joint_keys_fail_closed(tmp_path):
    s = snapshot()
    s["execution"].append(s["execution"][-1])
    with pytest.raises(ValueError):
        batch().select_candidates(s, tmp_path)


def test_live_requires_scoped_unexpired_owner_grant(tmp_path):
    m = batch()
    items = m.select_candidates(snapshot(), tmp_path)
    with pytest.raises(ValueError):
        m.validate_live_grant(None, items, tmp_path)
    path = tmp_path / "approval.json"
    path.write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "mode": "LIVE",
                "owner_confirmed": True,
                "expires_at": "2999-01-01T00:00:00+00:00",
                "backlink_ids": ["ready.example"],
            }
        )
    )
    grant = m.validate_live_grant(path, items, Path("/unrelated/repo"))
    assert grant == {"ready.example"}
    path.write_text(
        json.dumps(
            {
                "project_id": "other",
                "mode": "LIVE",
                "owner_confirmed": True,
                "expires_at": "2999-01-01T00:00:00+00:00",
                "backlink_ids": ["ready.example"],
            }
        )
    )
    with pytest.raises(ValueError):
        m.validate_live_grant(path, items, Path("/unrelated/repo"))


def test_adapter_missing_fact_and_unverified_dispatch_never_ready():
    m = batch()
    from backlink_submitter.contracts import load_project

    pack = load_project("wyrplay", Path(__file__).resolve().parents[1] / "projects/wyrplay")
    a = {
        "domain": "a.example",
        "fields": {"Product / App Name": "#name", "Website URL": "#url", "Founder name": "#founder"},
        "required_fields": ["Founder name"],
        "free_verified": True,
        "qualification": "QUALIFIED_A",
        "final_action_verified": True,
        "final_submit_selector": "#submit",
        "final_submit_text": "Submit product",
        "submission_request": {"verified": True, "method": "POST", "host": "a.example", "path": "/submit"},
    }
    assert m.adapter_gate(a, pack)["outcome"] == "OWNER_INPUT_REQUIRED"
    a["required_fields"] = []
    a["submission_request"]["verified"] = False
    assert m.adapter_gate(a, pack)["outcome"] == "需人工核查"


def test_not_applicable_and_global_bad_need_distinct_positive_evidence():
    m = batch()
    finding = {
        "outcome": "NOT_APPLICABLE",
        "reason": "AI_ONLY",
        "source_url": "https://a.example/rules",
        "checked_at": "2026-10-08T00:00:00+00:00",
        "marker": "AI products only",
    }
    assert m.assessment_result(finding, "AI products only", domain="a.example")["outcome"] == "NOT_APPLICABLE"
    finding.update(outcome="GLOBAL_BLACKLIST", reason="AI_ONLY")
    with pytest.raises(ValueError):
        m.assessment_result(finding, "AI products only", domain="a.example")
    finding.update(reason="PAYMENT_ONLY", marker="Paid submissions only")
    assert m.assessment_result(finding, "Paid submissions only", domain="a.example")["outcome"] == "GLOBAL_BLACKLIST"
    with pytest.raises(ValueError):
        m.assessment_result(finding, "Free submissions available", domain="a.example")


def test_resume_only_selects_queued_single_key_and_refuses_intent(tmp_path):
    m = batch()
    items = m.select_candidates(snapshot(), tmp_path)
    p = tmp_path / "human-queue/human.example.json"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "human.example",
                "domain": "human.example",
                "submit_url": "https://human.example/submit",
                "reason": "HUMAN_VERIFICATION_REQUIRED",
            }
        )
    )
    selected = m.resume_candidate(items, "human.example", tmp_path)
    assert selected["backlink_id"] == "human.example" and selected["resume"]
    with pytest.raises(ValueError):
        m.resume_candidate(items, "done.example", tmp_path)
    intent = tmp_path / "submit-intents/wyrplay/human.example.json"
    intent.parent.mkdir(parents=True)
    intent.write_text("{}")
    with pytest.raises(ValueError):
        m.resume_candidate(items, "human.example", tmp_path)


def test_human_queues_runtime_hint_but_dry_never_writes_sheet(tmp_path):
    assert importlib.util.find_spec("backlink_submitter.batch_worker") is not None, "Site worker missing"
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import record_non_submit

    api = SheetAPI()
    api.row[3] = "待提交"
    job = {
        "project_id": "wyrplay",
        "backlink_id": "site.example",
        "domain": "site.example",
        "row": 2,
        "submit_url": "https://site.example/submit",
        "runtime_root": str(tmp_path),
        "mode": "dry-run",
    }
    result = {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_VERIFICATION_REQUIRED"}
    record_non_submit(job, result, api, api.row.copy())
    assert api.writes == 0 and api.row[4] == ""
    saved = json.loads((tmp_path / "human-queue/site.example.json").read_text())
    assert saved["backlink_id"] == "site.example" and saved["submit"] == 0
    job["mode"] = "live"
    record_non_submit(job, result, api, api.row.copy())
    assert api.writes == 1 and api.row[3] == "去人工" and api.row[4] == ""


def test_batch_uses_real_single_engine_dispatch_evidence_and_attempt_receipt(tmp_path):
    assert importlib.util.find_spec("backlink_submitter.batch_worker") is not None, "Site worker missing"
    from playwright.async_api import async_playwright
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import execute_ready
    from backlink_submitter.contracts import load_project

    pack = load_project("wyrplay", Path(__file__).resolve().parents[1] / "projects/wyrplay")
    adapter = {
        "domain": "site.example",
        "submit_url": "https://site.example/submit",
        "fields": {"Product / App Name": "#name", "Website URL": "#url"},
        "required_fields": ["Product / App Name", "Website URL"],
        "free_verified": True,
        "login_required": False,
        "qualification": "QUALIFIED_A",
        "reciprocal_required": False,
        "automatic_submit_allowed": False,
        "final_action_verified": True,
        "final_submit_selector": "#submit",
        "final_submit_text": "Submit product",
        "submission_request": {"verified": True, "method": "POST", "host": "site.example", "path": "/api/submit"},
        "dispatch_timeout_ms": 100,
    }

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context()
            html = """<form onsubmit="event.preventDefault();fetch('/api/submit',{method:'POST'});document.body.innerHTML='WYRPlay submission received'"><input id=name><input id=url><button id=submit>Submit product</button></form>"""
            await ctx.route(
                "https://site.example/**", lambda r: r.fulfill(status=200, content_type="text/html", body=html)
            )
            page = await ctx.new_page()
            await page.goto(adapter["submit_url"])
            await page.locator("#name").fill("WYRPlay")
            await page.locator("#url").fill("https://www.wyrplay.com/")
            api = SheetAPI()
            api.row[8:10] = ["Original qualification note", "Original provenance"]
            job = {
                "mode": "live",
                "runtime_root": str(tmp_path),
                "backlink_id": "site.example",
                "domain": "site.example",
                "row": 2,
                "runtime_approved": True,
                "approval_expires_at": "2999-01-01T00:00:00+00:00",
            }
            result = await execute_ready(page, adapter, pack, api, job)
            assert result["outcome"] == "PENDING" and api.row[4] == "1"
            assert adapter["automatic_submit_allowed"] is False
            assert "Original qualification note" in api.row[8] and "Original provenance" in api.row[9]
            with pytest.raises(ValueError):
                await execute_ready(page, adapter, pack, api, job)
            assert api.writes == 1
            await ctx.close()
            await browser.close()

    asyncio.run(run())


def test_headed_handoff_requires_explicit_owner_action_and_one_key(tmp_path):
    from backlink_submitter import batch_worker as worker

    called = []
    job = {
        "backlink_id": "human.example",
        "domain": "human.example",
        "submit_url": "https://human.example/submit",
        "runtime_root": str(tmp_path),
        "owner_human_action": False,
        "row": 2,
    }
    with pytest.raises(ValueError):
        asyncio.run(worker.handoff(job, None, None))
    assert called == []


def test_non_applicable_writes_only_project_state_not_blacklist(tmp_path):
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import record_non_submit

    api = SheetAPI()
    job = {
        "project_id": "wyrplay",
        "backlink_id": "site.example",
        "domain": "site.example",
        "row": 2,
        "submit_url": "https://site.example/submit",
        "runtime_root": str(tmp_path),
        "mode": "live",
    }
    record_non_submit(job, {"outcome": "NOT_APPLICABLE", "reason": "AI_ONLY"}, api, api.row.copy())
    assert api.row[3] == "不适用" and api.row[4] == "" and api.writes == 1
    with pytest.raises(ValueError):
        from backlink_submitter.sheets import append_global_blacklist

        append_global_blacklist(api, job, {"outcome": "GLOBAL_BLACKLIST", "reason": "AI_ONLY"})


def test_dry_ready_requires_live_final_semantics_and_no_unknown_required_fields(tmp_path):
    from playwright.async_api import async_playwright

    from backlink_submitter.batch_worker import readonly_ready

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context()
            p = await ctx.new_page()
            await p.set_content(
                "<input id=name required><input id=url required><button id=submit>Submit product</button>"
            )
            adapter = {
                "fields": {"Product / App Name": "#name", "Website URL": "#url"},
                "final_submit_selector": "#submit",
                "final_submit_text": "Submit product",
                "login_required": False,
            }
            assert (await readonly_ready(p, adapter))["outcome"] == "READY_TO_SUBMIT"
            await p.locator("#submit").evaluate("e=>e.innerText='Pay now'")
            assert (await readonly_ready(p, adapter))["reason"] == "FINAL_ACTION_CHANGED"
            await p.locator("#submit").evaluate("e=>e.innerText='Submit product'")
            await p.evaluate("document.body.insertAdjacentHTML('beforeend','<input required id=founder>')")
            assert (await readonly_ready(p, adapter))["outcome"] == "OWNER_INPUT_REQUIRED"
            await ctx.close()
            await browser.close()

    asyncio.run(run())


def test_global_positive_finding_appends_only_blacklist_with_exact_readback(tmp_path):
    from test_contracts import SheetAPI

    from backlink_submitter.sheets import append_global_blacklist

    m = batch()

    class API(SheetAPI):
        def __init__(self):
            super().__init__()
            self.blacklist = [m.MASTER_HEADER]
            self.address = None

        def get(self, **kw):
            self.address = kw["range"]
            return self

        def append(self, **kw):
            assert kw["range"] == "黑名单!A:R"
            self.blacklist.append(kw["body"]["values"][0])
            self.address = "append"
            return self

        def execute(self):
            if self.address == "append":
                return {"updates": {"updatedRange": "黑名单!A2:R2"}}
            if self.address == "黑名单!A:R":
                return {"values": self.blacklist}
            if self.address == "黑名单!A2:R2":
                return {"values": [self.blacklist[-1]]}
            return {"values": [self.row]}

    api = API()
    before = api.row.copy()
    finding = {
        "outcome": "GLOBAL_BLACKLIST",
        "reason": "PAYMENT_ONLY",
        "source_url": "https://site.example/rules",
        "checked_at": "2026-10-08T00:00:00+00:00",
        "marker": "Paid submissions only",
    }
    candidate = {
        "backlink_id": "site.example",
        "domain": "site.example",
        "row": 2,
        "submit_url": "https://site.example/submit",
    }
    assert append_global_blacklist(api, candidate, finding) == "黑名单!A2:R2"
    assert api.row == before
    assert api.blacklist[-1][0:2] == ["site.example", "site.example"]
    assert append_global_blacklist(api, candidate, finding) is None
    assert len(api.blacklist) == 2


def test_crash_dispatch_receipt_consumed_once_without_second_click(tmp_path):
    from test_contracts import SheetAPI

    from backlink_submitter import batch as m
    from backlink_submitter.contracts import save_evidence

    api = SheetAPI()
    intent = tmp_path / "submit-intents/wyrplay/site.example.json"
    save_evidence(
        intent,
        {
            "project_id": "wyrplay",
            "backlink_id": "site.example",
            "prior_attempts": "",
            "dispatch_confirmed": True,
            "attempt_increment": 1,
            "dispatch": {"method": "POST", "host": "site.example", "path": "/submit"},
        },
    )
    job = {
        "mode": "live",
        "runtime_root": str(tmp_path),
        "backlink_id": "site.example",
        "row": 2,
        "evidence_dir": str(tmp_path / "checks"),
    }
    failure = {
        "backlink_id": "site.example",
        "outcome": "TEMPORARILY_UNAVAILABLE",
        "reason": "WORKER_CRASH_OR_INVALID_RESULT",
    }
    result = asyncio.run(m.recover_worker_result(job, failure, api))
    assert result["reason"] == "SUBMIT_RESULT_UNCONFIRMED" and api.row[4] == "1" and api.row[3] == "需人工核查"
    asyncio.run(m.recover_worker_result(job, failure, api))
    assert api.writes == 1 and api.row[4] == "1"


def test_dry_worker_missing_owner_fact_closes_without_click_or_sheet_write(tmp_path):
    from shutil import copytree

    from playwright.async_api import async_playwright
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import run_site
    from backlink_submitter.contracts import load_project

    packroot = tmp_path / "pack"
    copytree(Path(__file__).resolve().parents[1] / "projects/wyrplay", packroot)
    adapter = {
        "domain": "site.example",
        "submit_url": "https://site.example/submit",
        "required_fields": ["Founder name"],
        "fields": {"Founder name": "#founder"},
    }
    (packroot / "adapters/site.example.json").write_text(json.dumps(adapter))
    pack = load_project("wyrplay", packroot)
    api = SheetAPI()
    job = {
        "mode": "dry-run",
        "runtime_root": str(tmp_path),
        "project_id": "wyrplay",
        "row": 2,
        "backlink_id": "site.example",
        "domain": "site.example",
        "submit_url": "https://site.example/submit",
    }

    async def run():
        async with async_playwright() as pw:
            return await run_site(job, pack, api, pw)

    result = asyncio.run(run())
    assert result["outcome"] == "OWNER_INPUT_REQUIRED" and api.writes == 0
    assert not (tmp_path / "submit-intents/wyrplay/site.example.json").exists()


@pytest.mark.parametrize("status", ["成功", "审核中", "历史未验证"])
def test_fresh_protected_status_does_not_open_browser_or_resubmit(tmp_path, status):
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import run_site

    api = SheetAPI()
    api.row[3] = status
    job = {
        "project_id": "wyrplay",
        "backlink_id": "site.example",
        "domain": "site.example",
        "row": 2,
        "runtime_root": str(tmp_path),
    }
    result = asyncio.run(run_site(job, None, api, None))
    assert result["reason"] == "PROTECTED_EXISTING_STATUS" and api.writes == 0


def test_dry_and_live_refuse_changed_final_action_before_intent(tmp_path):
    from playwright.async_api import async_playwright
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import execute_ready
    from backlink_submitter.contracts import load_project

    pack = load_project("wyrplay", Path(__file__).resolve().parents[1] / "projects/wyrplay")
    adapter = {
        "domain": "site.example",
        "submit_url": "https://site.example/submit",
        "fields": {"Product / App Name": "#name", "Website URL": "#url"},
        "required_fields": ["Product / App Name", "Website URL"],
        "free_verified": True,
        "qualification": "QUALIFIED_A",
        "final_action_verified": True,
        "final_submit_selector": "#submit",
        "final_submit_text": "Submit product",
        "login_required": False,
        "submission_request": {"verified": True, "method": "POST", "host": "site.example", "path": "/api/submit"},
    }

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await ctx.route("https://site.example/**", lambda r: r.fulfill(status=200, body="fixture"))
            await page.goto("https://site.example/submit")
            await page.set_content("<input id=name><input id=url><button id=submit>Pay now</button>")
            await page.locator("#name").fill("WYRPlay")
            await page.locator("#url").fill("https://www.wyrplay.com/")
            adapter["dispatch_timeout_ms"] = 100
            job = {
                "mode": "live",
                "runtime_approved": True,
                "runtime_root": str(tmp_path),
                "row": 2,
                "backlink_id": "site.example",
                "approval_expires_at": "2999-01-01T00:00:00+00:00",
            }
            api = SheetAPI()
            with pytest.raises(ValueError):
                await execute_ready(page, adapter, pack, api, job)
            assert api.writes == 0 and not (tmp_path / "submit-intents/wyrplay/site.example.json").exists()
            await ctx.close()
            await browser.close()

    asyncio.run(run())


def test_dry_browser_blocks_post_requests_without_any_submit_intent(tmp_path):
    from playwright.async_api import async_playwright

    from backlink_submitter.batch_worker import readonly_requests

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(service_workers="block")
            await ctx.route("**/*", readonly_requests)
            page = await ctx.new_page()
            await page.set_content("<title>Fixture</title>")
            result = await page.evaluate(
                "fetch('https://site.example/api/submit',{method:'POST'}).then(()=>false).catch(()=>true)"
            )
            assert result is True
            await ctx.close()
            await browser.close()

    asyncio.run(run())


def test_late_e1_followup_updates_state_without_increment_or_reclick(tmp_path):
    from playwright.async_api import async_playwright
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import followup_proofs
    from backlink_submitter.contracts import save_evidence

    api = SheetAPI()
    api.row[3:5] = ["需人工核查", "1"]
    adapter = {
        "domain": "site.example",
        "submit_url": "https://site.example/submit",
        "submission_request": {"verified": True, "method": "POST", "host": "site.example", "path": "/api/submit"},
    }
    job = {
        "backlink_id": "site.example",
        "row": 2,
        "runtime_root": str(tmp_path),
        "evidence_dir": str(tmp_path / "check"),
    }
    save_evidence(
        tmp_path / "submit-intents/wyrplay/site.example.json",
        {
            "project_id": "wyrplay",
            "backlink_id": "site.example",
            "attempt_increment": 1,
            "dispatch_confirmed": True,
            "dispatch": {"method": "POST", "host": "site.example", "path": "/api/submit"},
        },
    )

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context()
            p = await ctx.new_page()
            await ctx.route(
                "https://site.example/**", lambda r: r.fulfill(status=200, body="WYRPlay submission received")
            )
            await p.goto(adapter["submit_url"])
            result = await followup_proofs(p, adapter, api, job, before_receipts=[])
            assert result["outcome"] == "PENDING" and result["receipt"]["evidence_code"] == "E1"
            assert api.row[4] == "1" and api.writes == 1
            await ctx.close()
            await browser.close()

    asyncio.run(run())
