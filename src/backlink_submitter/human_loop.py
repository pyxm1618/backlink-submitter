"""Serial Owner handoff using existing profiles, workers and the formal Sheet queue."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from .batch import RUNTIME, official_url, resume_candidate, run_pool, select_candidates
from .contracts import TARGET, now, save_evidence, validate_dispatch_metadata


async def poll_verification(check, *, interval=5, timeout=600):
    if interval <= 0 or not 0 < timeout <= 600:
        raise ValueError("Human wait must be bounded at ten minutes")
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        try:
            result = await asyncio.wait_for(check(), remaining)
        except TimeoutError:
            break
        if result["outcome"] != "HUMAN_VERIFICATION_REQUIRED":
            return result
        await asyncio.sleep(min(interval, max(0, deadline - asyncio.get_running_loop().time())))
    return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_WAIT_TIMEOUT"}


def verified_matcher(adapter):
    matcher = adapter.get("submission_request", {}) if adapter else {}
    if not matcher.get("verified") or not adapter.get("final_action_verified"):
        return None
    validate_dispatch_metadata({k: matcher.get(k) for k in ["method", "host", "path"]})
    if matcher["host"].removeprefix("www.") != adapter["domain"].removeprefix("www."):
        raise ValueError("Human final matcher host differs from verified platform")
    return matcher


async def human_submit_guard(route, matcher, auth_guard=None):
    if auth_guard is not None:
        await auth_guard.route(route)
        return
    request = route.request
    url = urlparse(request.url)
    # Unknown final endpoint => read-only. Never guess that an arbitrary POST is login.
    if (matcher is None and request.method not in {"GET", "HEAD", "OPTIONS"}) or (
        matcher and url.hostname == matcher["host"] and url.path == matcher["path"]
    ):
        await route.abort()
    else:
        await route.continue_()


async def recheck_handoff(job, pack, api, playwright):
    from .batch_worker import inspect_page, readonly_ready, site_context
    from .candidates import action_result
    from .discovery import discover
    from .sheets import full_row, is_blacklisted
    from .workflow import human_boundary

    if job.get("owner_human_action") is not True or not job.get("resume"):
        raise ValueError("Human loop needs explicit Owner execution")
    prior = full_row(api, job["row"])
    if (
        prior[:2] != ["wyrplay", job["backlink_id"]]
        or prior[3] != "去人工"
        or prior[4] not in {"", "0"}
        or is_blacklisted(api, job["backlink_id"], job["domain"])
        or (Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")).exists()
    ):
        raise ValueError("Protected joint key cannot open human-loop browser")
    if not official_url(job["submit_url"], job["domain"]):
        raise ValueError("Human URL lacks official provenance")
    path = pack["root"] / "adapters" / (job["domain"] + ".json")
    adapter = json.loads(path.read_text()) if path.is_file() else None
    matcher = verified_matcher(adapter)
    async with site_context(playwright, Path(job["runtime_root"]) / "profiles" / job["domain"], headed=True) as ctx:
        from .automation import AuthGuard

        auth = AuthGuard(job["domain"], matcher)
        auth.phase = "AUTH"
        page = await ctx.new_page()

        async def guard(route):
            await auth.refresh_route(route, page)

        await ctx.route("**/*", guard)
        await page.goto(job["submit_url"], wait_until="domcontentloaded", timeout=20000)

        async def check():
            if page.is_closed():
                return {"outcome": "需人工核查", "reason": "HUMAN_WINDOW_CLOSED"}
            try:
                await human_boundary(page)
            except ValueError:
                return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_VERIFICATION_REQUIRED"}
            if not official_url(page.url, job["domain"]):
                return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "OWNER_LOGIN_REQUIRED"}
            if adapter:
                result = await inspect_page(page, adapter, pack)
                return result or await readonly_ready(page, adapter)
            # Discovery has its own readonly guard. It may prove READY but cannot Submit.
            return await discover(page, pack, job)

        result = await poll_verification(check, interval=5, timeout=job.get("human_timeout", 600))
    result = action_result(result, job.get("channel_basis"))
    return dict(
        result,
        backlink_id=job["backlink_id"],
        headed_context_closed=True,
        submit=0,
        attempt_increment=0,
        sheet_writes=0,
        next_command="resume --project wyrplay --backlink-id " + job["backlink_id"],
        final_endpoint_guarded=bool(matcher),
        phase_bound_auth=True,
        final_submit_blocked=True,
    )


async def record_ready_handoff(api, item, result, runtime, evidence_path):
    from .batch_worker import sheet_writer
    from .sheets import full_row, write_outcome

    if result.get("outcome") != "READY_TO_SUBMIT":
        raise ValueError("Only the existing headless chain's verified READY can update the action")
    async with sheet_writer(runtime):
        prior = full_row(api, item["row"])
        if (
            prior[:2] != ["wyrplay", item["backlink_id"]]
            or prior[3] != "去人工"
            or prior[4] not in {"", "0"}
            or prior[7]
            or prior[6] != TARGET
            or (Path(runtime) / "submit-intents/wyrplay" / (item["backlink_id"] + ".json")).exists()
        ):
            raise ValueError("Fresh human queue key/state/Attempt/intent changed")
        write_outcome(
            api,
            item["row"],
            item["backlink_id"],
            {"project_id": "wyrplay", "status": "待提交", "evidence_code": "", "result_url": ""},
            reason=prior[8] + "\n[人工验证完成] 现有 headless 链已核验就绪条件；真实提交仍需 Owner 单次授权",
            summary=prior[9] + "\n待提交；仅动作状态更新，Attempt 不变 | " + str(evidence_path),
            expected_prior=prior,
            attempt_increment=0,
        )
    return {
        "backlink_id": item["backlink_id"],
        "row": item["row"],
        "status": "待提交",
        "attempt_increment": 0,
        "A_J_verified": True,
    }


async def human_loop(pack, *, owner_human_action=False, limit=1):
    import fcntl
    import secrets

    from .sheets import read_candidate_tables, service

    if not owner_human_action or type(limit) is not int or limit < 1:
        raise ValueError("Owner must explicitly start human-loop with a positive limit")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / "batch-run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another batch/profile operation is active") from None
        api = service(writable=True)
        candidates = select_candidates(read_candidate_tables(api), RUNTIME)
        queue = [x for x in candidates if x["prior_status"] == "去人工"][:limit]
        directory = RUNTIME / ("human-loop-" + secrets.token_hex(6))
        directory.mkdir(mode=0o700)
        results = []
        receipts = []
        # Await each one-process pool to completion (and group reclamation) before next window.
        for item in queue:
            hint = RUNTIME / "human-queue" / (item["backlink_id"] + ".json")
            if not hint.is_file():
                results.append(
                    {
                        "backlink_id": item["backlink_id"],
                        "action_status": "去人工",
                        "action_reason": "缺少安全恢复入口，请先单站核验",
                        "submit": 0,
                    }
                )
                continue
            job = dict(
                resume_candidate(candidates, item["backlink_id"], RUNTIME),
                mode="human-loop",
                runtime_root=str(RUNTIME),
                evidence_dir=str(directory / item["domain"]),
                owner_human_action=True,
                human_timeout=600,
            )
            from .automation import OWNER_REASONS
            from .candidates import action_result

            # Old 去人工 rows may be ordinary login/technical gaps. Headless goes first.
            automatic = dict(job, mode="dry-run", owner_human_action=False)
            initial = await run_pool(
                [automatic], runtime=directory / item["domain"] / "automatic", concurrency=1, timeout=90
            )
            if initial[0].get("reason") not in OWNER_REASONS:
                result = [action_result(initial[0], item.get("channel_basis"))]
                evidence = save_evidence(directory / (item["backlink_id"] + ".json"), result[0])
                if result[0].get("outcome") == "READY_TO_SUBMIT":
                    receipts.append(await record_ready_handoff(api, item, result[0], RUNTIME, evidence))
                results.extend(result)
                continue
            result = await run_pool([job], runtime=directory / item["domain"] / "workers", concurrency=1, timeout=630)
            if result[0].get("reason") in {"WORKER_TIMEOUT", "WORKER_CRASH_OR_INVALID_RESULT"}:
                result[0].update(
                    action_status="去人工",
                    action_reason="人工核验未完成或窗口异常；保持去人工，可稍后重新处理",
                    submit=0,
                )
            if result[0].get("headed_context_closed") and result[0]["outcome"] == "READY_TO_SUBMIT":
                # The headed window has closed before the existing headless chain checks every gate again.
                headless_job = dict(job, mode="dry-run", owner_human_action=False)
                rechecked = await run_pool(
                    [headless_job], runtime=directory / item["domain"] / "recheck", concurrency=1, timeout=90
                )
                from .candidates import action_result

                result = [
                    dict(
                        action_result(rechecked[0], item.get("channel_basis")),
                        headed_context_closed=True,
                        submit=0,
                        sheet_writes=0,
                        next_command="resume --project wyrplay --backlink-id " + item["backlink_id"],
                    )
                ]
            evidence = save_evidence(directory / (item["backlink_id"] + ".json"), result[0])
            if result[0].get("outcome") == "READY_TO_SUBMIT" and result[0].get("headed_context_closed"):
                receipts.append(await record_ready_handoff(api, item, result[0], RUNTIME, evidence))
            results.extend(result)
        report = {
            "project_id": "wyrplay",
            "checked_at": now(),
            "results": results,
            "submit": 0,
            "sheet_writes": len(receipts),
            "submission_result_writes": 0,
            "ready_readbacks": receipts,
            "headed_max": 1,
            "runtime": str(directory),
        }
        save_evidence(directory / "report.json", report)
        return report
