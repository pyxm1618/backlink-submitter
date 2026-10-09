import asyncio

import pytest
from test_batch import snapshot

from backlink_submitter.batch import select_candidates


def test_news_homepage_is_not_submission_entry(tmp_path):
    s = snapshot()
    s["master"][-1] = ["unknown.example", "unknown.example", "https://unknown.example/"]
    item = select_candidates(s, tmp_path)[-1]
    assert not item["process"]
    assert item["reason"] == "NO_POSITIVE_CHANNEL_FACT"
    assert item["coverage"] == "unknown"  # exclusion from browser is not rejection


@pytest.mark.parametrize("path", ["/submit", "/write-for-us", "/contribute", "/submit-a-guest-post/"])
def test_explicit_publishing_entries_are_candidates(tmp_path, path):
    s = snapshot()
    s["master"][-1][2] = "https://unknown.example" + path
    item = select_candidates(s, tmp_path)[-1]
    assert item["process"]
    assert item["channel_basis"]["kind"] == "official_entry"


def test_platform_type_positive_but_project_execution_not_shared(tmp_path):
    s = snapshot()
    s["master"][-1] = ["unknown.example", "unknown.example", ""] + [""] * 13 + ["产品目录", ""]
    s["execution"].insert(1, ["quickiching", "unknown.example", "unknown.example", "成功", "3"])
    item = select_candidates(s, tmp_path)[-1]
    assert item["process"] and item["prior_attempt"] == "" and item["prior_status"] == ""
    assert item["channel_basis"]["kind"] == "platform_type"


@pytest.mark.parametrize(
    "reason",
    [
        "HUMAN_VERIFICATION_REQUIRED",
        "OWNER_LOGIN_REQUIRED",
        "CAPTCHA",
        "UNMAPPED_REQUIRED_FIELDS",
        "DISPATCH_MATCHER_UNVERIFIED",
        "ADAPTER_REVIEW_REQUIRED",
    ],
)
def test_human_actions_have_clear_chinese_status(reason):
    from backlink_submitter.candidates import action_result

    r = action_result(
        {"outcome": "需人工核查", "reason": reason},
        {"kind": "official_entry", "source_url": "https://example.com/submit"},
    )
    assert r["action_status"] == "去人工"
    assert r["action_reason"] and reason not in r["action_reason"]
    assert r["coverage"] == "deferred"


def test_unknown_without_channel_not_falsely_rejected():
    from backlink_submitter.candidates import action_result

    r = action_result({"outcome": "需人工核查", "reason": "OFFICIAL_SUBMIT_URL_UNCONFIRMED"}, None)
    assert r["coverage"] == "unknown"
    assert r["action_status"] is None


def test_positive_project_mismatch_not_global_and_temporary_is_actionable():
    from backlink_submitter.candidates import action_result

    assert action_result({"outcome": "NOT_APPLICABLE", "reason": "AI_ONLY"}, None)["action_status"] == "不适用"
    assert (
        action_result({"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "HTTP_UNAVAILABLE_NOT_PERMANENT_PROOF"}, None)[
            "action_status"
        ]
        == "暂时不可用"
    )


def test_official_nonchannel_observation_supports_project_disposition():
    from backlink_submitter.candidates import observed_channel

    obs = observed_channel(
        "https://example.com/",
        "University medical research and patient care",
        [{"text": "Admissions", "url": "https://example.com/admissions"}],
        [],
    )
    assert not obs["confirmed"]
    assert obs["site_purpose"] == "学校/研究机构"


def test_human_poll_resolved_and_timeout_release():
    from backlink_submitter.human_loop import poll_verification

    async def scenario():
        calls = []

        async def check():
            calls.append(1)
            return {"outcome": "HUMAN_VERIFICATION_REQUIRED"} if len(calls) == 1 else {"outcome": "READY_TO_SUBMIT"}

        result = await poll_verification(check, interval=0.001, timeout=0.1)
        assert result["outcome"] == "READY_TO_SUBMIT" and len(calls) == 2

        async def blocked():
            return {"outcome": "HUMAN_VERIFICATION_REQUIRED"}

        assert (await poll_verification(blocked, interval=0.001, timeout=0.005))["reason"] == "HUMAN_WAIT_TIMEOUT"

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "GET"])
def test_human_guard_blocks_verified_final_even_manual(method):
    from backlink_submitter.human_loop import human_submit_guard

    class Route:
        request = type("Request", (), {"method": method, "url": "https://example.com/api/submit?variant=1"})()
        aborted = False

        async def abort(self):
            self.aborted = True

        async def continue_(self):
            raise AssertionError("Final submit endpoint must never be released")

    route = Route()
    asyncio.run(human_submit_guard(route, {"method": "POST", "host": "example.com", "path": "/api/submit"}))
    assert route.aborted


def test_unknown_matcher_never_guesses_login_post():
    from backlink_submitter.human_loop import human_submit_guard, verified_matcher

    assert verified_matcher({"submission_request": {"verified": False}}) is None

    class Route:
        request = type("Request", (), {"method": "POST", "url": "https://example.com/login"})()

        async def abort(self):
            self.aborted = True

        async def continue_(self):
            raise AssertionError("Unknown matcher cannot open write requests")

    route = Route()
    asyncio.run(human_submit_guard(route, None))
    assert route.aborted


def test_human_loop_serial_single_worker_and_formal_queue(tmp_path, monkeypatch):
    import backlink_submitter.human_loop as module
    import backlink_submitter.sheets as sheets

    s = snapshot()
    for r in s["execution"][1:]:
        if r[0] == "wyrplay" and r[1] in {"ready.example", "unknown.example"}:
            r[3] = "去人工"

    async def ready_receipt(api, item, result, runtime, evidence):
        return {"backlink_id": item["backlink_id"], "A_J_verified": True, "attempt_increment": 0}

    monkeypatch.setattr(module, "record_ready_handoff", ready_receipt)
    monkeypatch.setattr(module, "RUNTIME", tmp_path)
    monkeypatch.setattr(sheets, "service", lambda **kwargs: object())
    monkeypatch.setattr(sheets, "read_candidate_tables", lambda api: s)
    queue = tmp_path / "human-queue"
    queue.mkdir()
    import json

    for key in ["ready.example", "unknown.example"]:
        (queue / (key + ".json")).write_text(
            json.dumps(
                {"project_id": "wyrplay", "backlink_id": key, "domain": key, "submit_url": "https://" + key + "/submit"}
            )
        )
    active = maximum = 0
    visited = []

    async def pool(jobs, **kwargs):
        nonlocal active, maximum
        assert kwargs["concurrency"] == 1 and len(jobs) == 1
        active += 1
        maximum = max(maximum, active)
        visited.append(jobs[0]["backlink_id"])
        await asyncio.sleep(0.001)
        active -= 1
        return [
            {
                "backlink_id": jobs[0]["backlink_id"],
                "outcome": "READY_TO_SUBMIT",
                "reason": "FORM_READY",
                "headed_context_closed": True,
                "submit": 0,
            }
        ]

    monkeypatch.setattr(module, "run_pool", pool)
    report = asyncio.run(module.human_loop({"root": tmp_path}, owner_human_action=True, limit=2))
    assert (
        visited == ["ready.example", "ready.example", "unknown.example", "unknown.example"]
        and maximum == 1
        and active == 0
    )
    assert report["submit"] == 0 and report["sheet_writes"] == 2
    with pytest.raises(ValueError):
        asyncio.run(module.human_loop({"root": tmp_path}, owner_human_action=False))


@pytest.mark.parametrize("resolved", [True, False])
def test_human_context_rechecked_and_closed_on_timeout(tmp_path, monkeypatch, resolved):
    import json
    from contextlib import asynccontextmanager

    from backlink_submitter import batch_worker, discovery, sheets, workflow

    assert callable(discovery.discover)  # Load its real boundary before the orchestration-only mock.
    from backlink_submitter.human_loop import recheck_handoff

    adapters = tmp_path / "adapters"
    adapters.mkdir()
    adapter = {
        "domain": "example.com",
        "final_action_verified": True,
        "submission_request": {"verified": True, "method": "POST", "host": "example.com", "path": "/api/submit"},
    }
    (adapters / "example.com.json").write_text(json.dumps(adapter))
    monkeypatch.setattr(
        sheets, "full_row", lambda api, row: ["wyrplay", "example.com", "example.com", "去人工", "", "", "", "", "", ""]
    )
    monkeypatch.setattr(sheets, "is_blacklisted", lambda *args: False)
    state = {"open": 0, "closed": 0, "checks": 0}

    class Page:
        url = "https://example.com/submit"

        async def goto(self, *args, **kwargs):
            return None

        def is_closed(self):
            return False

    class Context:
        async def route(self, *args):
            return None

        async def new_page(self):
            return Page()

    @asynccontextmanager
    async def context(*args, **kwargs):
        assert kwargs["headed"] is True
        state["open"] += 1
        try:
            yield Context()
        finally:
            state["open"] -= 1
            state["closed"] += 1

    async def boundary(page):
        state["checks"] += 1
        if not resolved:
            raise ValueError("HUMAN_VERIFICATION_REQUIRED")

    async def inspect(*args):
        return None

    async def ready(*args):
        return {"outcome": "READY_TO_SUBMIT", "reason": "FORM_READY"}

    monkeypatch.setattr(batch_worker, "site_context", context)
    monkeypatch.setattr(workflow, "human_boundary", boundary)
    monkeypatch.setattr(batch_worker, "inspect_page", inspect)
    monkeypatch.setattr(batch_worker, "readonly_ready", ready)
    job = {
        "backlink_id": "example.com",
        "domain": "example.com",
        "row": 2,
        "runtime_root": str(tmp_path),
        "owner_human_action": True,
        "resume": True,
        "submit_url": "https://example.com/submit",
        "human_timeout": 0.01,
        "channel_basis": {"kind": "official_entry"},
    }
    result = asyncio.run(recheck_handoff(job, {"root": tmp_path}, object(), object()))
    assert state["closed"] == 1 and state["open"] == 0 and state["checks"] > 0
    assert result["action_status"] == ("待提交" if resolved else "去人工")
    assert result["submit"] == result["attempt_increment"] == result["sheet_writes"] == 0


def test_long_wait_only_allowed_for_single_explicit_human_worker(tmp_path):
    from backlink_submitter.batch import run_pool

    with pytest.raises(ValueError):
        asyncio.run(run_pool([{"mode": "dry-run"}], runtime=tmp_path, timeout=630))
    with pytest.raises(ValueError):
        asyncio.run(
            run_pool([{"mode": "human-loop", "owner_human_action": True}], runtime=tmp_path, concurrency=2, timeout=630)
        )


def test_single_human_worker_accepts_ten_minute_deadline(tmp_path):
    import sys

    from backlink_submitter.batch import run_pool

    script = tmp_path / "worker.py"
    script.write_text(
        "import json,sys\nfrom pathlib import Path\nj=json.loads(Path(sys.argv[1]).read_text())\nPath(j['result_path']).write_text(json.dumps({'backlink_id':j['backlink_id'],'outcome':'HUMAN_VERIFICATION_REQUIRED','reason':'HUMAN_WAIT_TIMEOUT'}))\n"
    )
    jobs = [{"mode": "human-loop", "owner_human_action": True, "backlink_id": "a.example", "domain": "a.example"}]
    result = asyncio.run(
        run_pool(jobs, runtime=tmp_path / "run", concurrency=1, timeout=630, command=[sys.executable, str(script)])
    )
    assert result[0]["reason"] == "HUMAN_WAIT_TIMEOUT"


def test_unmapped_required_field_has_actual_name(tmp_path):
    from test_discovery import FORM, fixture_discover

    html = FORM.replace(
        '<button id="final"', '<label for="founder">Founder name</label><input id="founder" required><button id="final"'
    )
    result, requests = asyncio.run(fixture_discover(tmp_path, html))
    assert result["missing_fields"] == ["Founder name"]
    assert all(method == "GET" for method, _ in requests)


@pytest.mark.parametrize(
    "body,link",
    [
        (
            "Tech giants contribute resources to science",
            {"text": "Tech Giants Contribute $2 Billion", "url": "https://example.com/news/ai-contribution"},
        ),
        (
            "Our CRM builds your own private community",
            {"text": "Community features", "url": "https://example.com/features/community"},
        ),
        (
            "A 2015 guest post about arts education",
            {"text": "Guest post: Arts Education", "url": "https://example.com/2015/guest-post-arts"},
        ),
        (
            "SNSの投稿をファクトチェック",
            {"text": "インフルエンザの投稿を検証", "url": "https://example.com/factcheck/influenza"},
        ),
    ],
)
def test_content_words_and_saas_features_are_not_channel_proof(body, link):
    from backlink_submitter.candidates import observed_channel

    assert not observed_channel("https://example.com/", body, [link], [])["confirmed"]


def test_human_ready_hands_back_to_existing_headless_chain(tmp_path, monkeypatch):
    import json

    import backlink_submitter.human_loop as module
    import backlink_submitter.sheets as sheets

    s = snapshot()
    s["execution"][-1][3] = "去人工"

    async def ready_receipt(api, item, result, runtime, evidence):
        return {"backlink_id": item["backlink_id"], "A_J_verified": True, "attempt_increment": 0}

    monkeypatch.setattr(module, "record_ready_handoff", ready_receipt)
    monkeypatch.setattr(module, "RUNTIME", tmp_path)
    monkeypatch.setattr(sheets, "service", lambda **kwargs: object())
    monkeypatch.setattr(sheets, "read_candidate_tables", lambda api: s)
    (tmp_path / "human-queue").mkdir()
    (tmp_path / "human-queue/unknown.example.json").write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "unknown.example",
                "domain": "unknown.example",
                "submit_url": "https://unknown.example/submit",
            }
        )
    )
    modes = []

    async def pool(jobs, **kwargs):
        modes.append(jobs[0]["mode"])
        return [
            {
                "backlink_id": "unknown.example",
                "outcome": "READY_TO_SUBMIT",
                "reason": "FORM_READY",
                "headed_context_closed": True,
                "submit": 0,
            }
        ]

    monkeypatch.setattr(module, "run_pool", pool)
    asyncio.run(module.human_loop({"root": tmp_path}, owner_human_action=True))
    assert modes == ["human-loop", "dry-run"]


def test_legacy_comment_success_is_not_verified_channel(tmp_path):
    s = snapshot()
    s["master"][-1] = ["unknown.example", "unknown.example", "https://unknown.example/wp-comments-post.php"] + [""] * 15
    s["master"][-1][7] = "免费"
    s["master"][-1][12] = "2026-09-27T00:00:00+00:00"
    s["master"][-1][13] = "发现客座文章/博客投稿通道 (Write for us / Guest Post); 自动提交成功，进入审核"
    assert not select_candidates(s, tmp_path)[-1]["process"]


def test_channel_fact_needs_traceable_official_source(tmp_path):
    s = snapshot()
    r = ["unknown.example", "unknown.example", ""] + [""] * 15
    r[7], r[12], r[13] = (
        "免费",
        "2026-09-27T00:00:00+00:00",
        "发现明确的客座文章/博客投稿通道 (Write for us / Guest Post)",
    )
    s["master"][-1] = r
    assert not select_candidates(s, tmp_path)[-1]["process"]
    r[13] = "官方已核验免费 Guest Post 渠道：https://unknown.example/editorial-guidelines"
    assert select_candidates(s, tmp_path)[-1]["channel_basis"]["kind"] == "verified_platform_fact"


def test_human_worker_failure_stays_in_manual_queue(tmp_path, monkeypatch):
    import json

    import backlink_submitter.human_loop as module
    import backlink_submitter.sheets as sheets

    s = snapshot()
    s["execution"][-1][3] = "去人工"

    async def ready_receipt(api, item, result, runtime, evidence):
        return {"backlink_id": item["backlink_id"], "A_J_verified": True, "attempt_increment": 0}

    monkeypatch.setattr(module, "record_ready_handoff", ready_receipt)
    monkeypatch.setattr(module, "RUNTIME", tmp_path)
    monkeypatch.setattr(sheets, "service", lambda **kwargs: object())
    monkeypatch.setattr(sheets, "read_candidate_tables", lambda api: s)
    (tmp_path / "human-queue").mkdir()
    (tmp_path / "human-queue/unknown.example.json").write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "unknown.example",
                "domain": "unknown.example",
                "submit_url": "https://unknown.example/submit",
            }
        )
    )

    async def pool(jobs, **kwargs):
        return [{"backlink_id": "unknown.example", "outcome": "TEMPORARILY_UNAVAILABLE", "reason": "WORKER_TIMEOUT"}]

    monkeypatch.setattr(module, "run_pool", pool)
    report = asyncio.run(module.human_loop({"root": tmp_path}, owner_human_action=True))
    assert report["results"][0]["action_status"] == "去人工"
    assert report["sheet_writes"] == report["submit"] == 0


def test_observed_chinese_login_instruction_is_actionable(tmp_path):
    from test_discovery import fixture_discover

    result, requests = asyncio.run(
        fixture_discover(
            tmp_path, '<meta charset="utf-8"><h1>投稿须知</h1><p>需要登录才能访问！</p><a href="/login">登录</a>'
        )
    )
    assert result["outcome"] == "HUMAN_VERIFICATION_REQUIRED"
    assert result["reason"] == "OWNER_LOGIN_REQUIRED"
    assert all(method == "GET" for method, _ in requests)


def test_unconfirmed_channel_note_is_not_positive_fact(tmp_path):
    s = snapshot()
    r = ["unknown.example", "unknown.example", ""] + [""] * 15
    r[7], r[12], r[13] = (
        "免费",
        "2026-09-27T00:00:00+00:00",
        "未验证 Guest Post 渠道，需要人工确认：https://unknown.example/about",
    )
    s["master"][-1] = r
    assert not select_candidates(s, tmp_path)[-1]["process"]


def test_ready_human_handoff_updates_formal_action_without_attempt(tmp_path):
    from test_contracts import SheetAPI

    from backlink_submitter.human_loop import record_ready_handoff

    api = SheetAPI()
    api.row[3] = "去人工"
    prior = api.row.copy()
    item = {"backlink_id": "site.example", "row": 2}
    receipt = asyncio.run(
        record_ready_handoff(api, item, {"outcome": "READY_TO_SUBMIT"}, tmp_path, tmp_path / "proof.json")
    )
    assert api.writes == 1 and api.row[3] == "待提交" and api.row[4] == prior[4]
    assert api.row[:3] == prior[:3] and api.row[7] == "" and receipt["attempt_increment"] == 0
    assert receipt["A_J_verified"] is True
    with pytest.raises(ValueError):
        asyncio.run(record_ready_handoff(api, item, {"outcome": "READY_TO_SUBMIT"}, tmp_path, tmp_path / "proof.json"))


def test_temporary_is_not_permanent_dead_end_but_needs_explicit_resume(tmp_path):
    import json

    from backlink_submitter.batch import resume_candidate

    s = snapshot()
    s["execution"][-1][3] = "暂时不可用"
    items = select_candidates(s, tmp_path)
    assert not items[-1]["process"]  # no automatic retries in a new bulk window
    (tmp_path / "human-queue").mkdir()
    (tmp_path / "human-queue/unknown.example.json").write_text(
        json.dumps(
            {
                "project_id": "wyrplay",
                "backlink_id": "unknown.example",
                "domain": "unknown.example",
                "submit_url": "https://unknown.example/submit",
            }
        )
    )
    assert resume_candidate(items, "unknown.example", tmp_path)["resume"] is True
    items[-1]["prior_attempt"] = "1"
    with pytest.raises(ValueError):
        resume_candidate(items, "unknown.example", tmp_path)
