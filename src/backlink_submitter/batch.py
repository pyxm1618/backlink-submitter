"""Ordered three-table selection and a bounded, process-isolated worker pool."""

import asyncio
import json
import os
import re
import signal
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .contracts import (
    composed_value,
    field_value,
    identity_mapped,
    now,
    safe_artifact,
    save_evidence,
    timestamp,
    validate_dispatch_metadata,
)

MASTER_HEADER = [
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
EXECUTION_HEADER = [
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
OUTCOMES = {
    "SUCCESS",
    "PENDING",
    "NOT_APPLICABLE",
    "GLOBAL_BLACKLIST",
    "HUMAN_VERIFICATION_REQUIRED",
    "OWNER_INPUT_REQUIRED",
    "TEMPORARILY_UNAVAILABLE",
    "READY_TO_SUBMIT",
    "需人工核查",
    "历史未验证",
    "被拒绝",
    "提交失败",
}
GLOBAL_REASONS = {"SPAM", "PBN", "MALICIOUS", "PERMANENTLY_UNAVAILABLE", "PAYMENT_ONLY", "NO_EXTERNAL_LINK_CHANNEL"}
RUNTIME = Path("~/.backlink-autofill/runtime/wyrplay").expanduser()


def official_url(url, domain):
    p = urlparse(url)
    return (
        p.scheme == "https"
        and p.hostname
        and p.hostname.removeprefix("www.") == domain.removeprefix("www.")
        and not (p.query or p.fragment or p.username or p.password)
    )


def select_candidates(snapshot, runtime):
    for key, header in [("master", MASTER_HEADER), ("blacklist", MASTER_HEADER), ("execution", EXECUTION_HEADER)]:
        if not snapshot[key] or snapshot[key][0] != header:
            raise ValueError("Official table header mismatch: " + key)
    rows = {}
    for number, raw in enumerate(snapshot["execution"][1:], 2):
        if not raw or raw[0] != "wyrplay":
            continue
        row = raw + [""] * (10 - len(raw))
        if len(row) != 10 or not row[1] or row[1] in rows:
            raise ValueError("Missing/duplicate WYRPlay joint key")
        rows[row[1]] = (number, row)
    blocked_keys = {r[0] for r in snapshot["blacklist"][1:] if r}
    blocked_domains = {r[1].lower().removeprefix("www.") for r in snapshot["blacklist"][1:] if len(r) > 1}
    candidates = []
    seen = set()
    for master_number, raw in enumerate(snapshot["master"][1:], 2):
        if not raw:
            continue
        key = raw[0]
        if key in seen:
            raise ValueError("Duplicate master key; ambiguous platform facts")
        seen.add(key)
        if key not in rows:
            continue  # no automatic creation of WYRPlay rows
        number, row = rows.pop(key)
        m = raw + [""] * (18 - len(raw))
        domain = m[1].lower().removeprefix("www.")
        item = {
            "project_id": "wyrplay",
            "backlink_id": key,
            "domain": domain,
            "row": number,
            "master_row": master_number,
            "submit_url": m[2],
            "prior_status": row[3],
            "prior_attempt": row[4],
            "process": False,
            "outcome": "需人工核查",
            "reason": "UNKNOWN_PLATFORM",
            "coverage": "unknown",
        }
        if key in blocked_keys or domain in blocked_domains:
            item.update(outcome="GLOBAL_BLACKLIST", reason="EXISTING_GLOBAL_BLACKLIST", coverage="confirmed_reject")
        elif row[3] not in {"", "待提交"}:
            item.update(
                outcome={"成功": "SUCCESS", "审核中": "PENDING", "不适用": "NOT_APPLICABLE"}.get(row[3], "需人工核查"),
                reason="PROTECTED_EXISTING_STATUS",
                coverage="deferred",
            )
        elif row[4] not in {"", "0"}:
            item.update(reason="EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY", coverage="deferred")
        elif not re.fullmatch(r"[a-zA-Z0-9_.-]+", key) or not re.fullmatch(r"[a-z0-9.-]+", domain):
            item.update(reason="INVALID_PLATFORM_KEY", coverage="unknown", submit_url="")
        elif (Path(runtime) / "submit-intents/wyrplay" / (key + ".json")).exists():
            item.update(reason="PERSISTENT_SUBMIT_INTENT", coverage="deferred")
        elif m[5] in {"失效", "已排除", "不适用"} or m[14] in {"失效", "已排除", "不适用"}:
            item.update(
                outcome="TEMPORARILY_UNAVAILABLE", reason="HISTORICAL_PLATFORM_EXCLUSION_REVIEW", coverage="deferred"
            )
        elif not official_url(m[2], domain):
            item.update(process=True, reason="REQUIRES_OFFICIAL_ENTRY_DISCOVERY", submit_url="")
        else:
            item.update(process=True, reason="REQUIRES_ADAPTER_AND_LIVE_CHECKS")
        # No raw legacy notes, emails, URLs with credentials or other project rows persist.
        if not official_url(item["submit_url"], domain):
            item["submit_url"] = ""
        candidates.append(item)
    for key, (number, row) in sorted(rows.items(), key=lambda x: x[1][0]):
        candidates.append(
            {
                "project_id": "wyrplay",
                "backlink_id": key,
                "domain": row[2],
                "row": number,
                "master_row": None,
                "submit_url": "",
                "prior_status": row[3],
                "prior_attempt": row[4],
                "process": False,
                "outcome": "需人工核查",
                "reason": "MASTER_FACTS_MISSING",
                "coverage": "unknown",
            }
        )
    return candidates


def adapter_gate(adapter, pack):
    for field in adapter.get("required_fields", []):
        if field in adapter.get("composed_fields", {}):
            composed_value(pack, adapter["composed_fields"][field])
            continue
        taxonomy = adapter.get("taxonomy", {})
        if field == "Category" and (
            taxonomy.get("selected_verified") or taxonomy.get("native_select") and taxonomy.get("option_verified")
        ):
            continue
        value = field_value(pack, field, required=True, platform=adapter["domain"])
        if isinstance(value, dict):
            return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "OWNER_INPUT_REQUIRED", "missing_field": field}
        if field not in adapter.get("fields", {}) and field not in adapter.get("choice_fields", {}):
            return {"outcome": "需人工核查", "reason": "REQUIRED_FIELD_MAPPING_UNVERIFIED"}
    matcher = adapter.get("submission_request", {})
    if not matcher.get("verified"):
        return {"outcome": "需人工核查", "reason": "DISPATCH_MATCHER_UNVERIFIED"}
    validate_dispatch_metadata({k: matcher.get(k) for k in ("method", "host", "path")})
    if matcher["host"].removeprefix("www.") != adapter["domain"].removeprefix("www."):
        raise ValueError("Dispatch matcher is not platform host")
    if not all(
        adapter.get(k) for k in ["free_verified", "final_action_verified", "final_submit_selector", "final_submit_text"]
    ):
        return {"outcome": "需人工核查", "reason": "EXECUTION_CONDITIONS_UNVERIFIED"}
    if adapter.get("reciprocal_required") or adapter.get("qualification") not in {
        "QUALIFIED_A",
        "QUALIFIED_B",
        "QUALIFIED_C",
    }:
        return {"outcome": "需人工核查", "reason": "QUALIFICATION_OR_RECIPROCAL_REVIEW"}
    if not identity_mapped(adapter, pack):
        return {"outcome": "需人工核查", "reason": "IDENTITY_MAPPING_UNVERIFIED"}
    return None


def assessment_result(finding, text, *, domain):
    if finding.get("outcome") not in {"NOT_APPLICABLE", "GLOBAL_BLACKLIST"} or not finding.get("reason"):
        raise ValueError("Invalid qualification finding")
    if finding["outcome"] == "GLOBAL_BLACKLIST" and finding["reason"] not in GLOBAL_REASONS:
        raise ValueError("Project mismatch is not a global blacklist reason")
    if not official_url(finding.get("source_url", ""), domain) or not finding.get("checked_at"):
        raise ValueError("Positive official provenance required")
    timestamp(finding["checked_at"])
    if not finding.get("marker") or finding["marker"] not in text:
        raise ValueError("Qualification evidence changed; preserve unknown")
    result = {k: finding[k] for k in ["outcome", "reason", "source_url", "marker"]}
    result["checked_at"] = now()
    safe_artifact(result)
    return result


def validate_live_grant(path, candidates, repo):
    if not path or Path(path).resolve().is_relative_to(Path(repo).resolve()):
        raise ValueError("LIVE requires an external Owner grant, never a committed global switch")
    grant = json.loads(Path(path).read_text())
    if (grant.get("project_id"), grant.get("mode"), grant.get("owner_confirmed")) != ("wyrplay", "LIVE", True):
        raise ValueError("Owner LIVE grant identity/mode mismatch")
    if timestamp(grant["expires_at"]) <= timestamp(now()):
        raise ValueError("Owner LIVE grant expired")
    keys = grant.get("backlink_ids")
    if not isinstance(keys, list) or not keys or any(not isinstance(k, str) for k in keys):
        raise ValueError("Owner grant must explicitly scope platform keys")
    if not set(keys) <= {x["backlink_id"] for x in candidates}:
        raise ValueError("Grant contains keys outside official joined pool")
    return set(keys)


async def terminate_group(process):
    # Each child (and its Chrome descendants) owns a new process group. Never touch Owner Chrome.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        if sig == signal.SIGTERM:
            await asyncio.sleep(0.15)
    await asyncio.wait_for(process.wait(), 5)


async def run_pool(jobs, *, runtime, concurrency=2, timeout=90, command=None):
    if type(concurrency) is not int or not 1 <= concurrency <= 4 or not 0 < timeout <= 270:
        raise ValueError("Concurrency must be 1..4; worker deadline at most 270 seconds")
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    command = command or [sys.executable, "-m", "backlink_submitter.batch_worker"]
    queue: asyncio.Queue = asyncio.Queue(maxsize=concurrency * 2)
    locks: dict[str, asyncio.Lock] = {}
    results: dict[int, Any] = {}

    async def worker():
        while True:
            task = await queue.get()
            if task is None:
                queue.task_done()
                return
            index, original = task
            job = dict(original, result_path=str(runtime / f"{index}-result.json"))
            process = None
            try:
                async with locks.setdefault(job["domain"], asyncio.Lock()):
                    path = save_evidence(runtime / f"{index}-job.json", job)
                    try:
                        process = await asyncio.create_subprocess_exec(
                            *command,
                            str(path),
                            start_new_session=True,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await asyncio.wait_for(process.wait(), timeout)
                        if process.returncode != 0:
                            raise RuntimeError("WORKER_CRASH")
                        result = json.loads(Path(job["result_path"]).read_text())
                        if result.get("backlink_id") != job["backlink_id"] or result.get("outcome") not in OUTCOMES:
                            raise ValueError("Invalid worker boundary result")
                        safe_artifact(result)
                        results[index] = result
                    except (TimeoutError, RuntimeError, ValueError, OSError) as exc:
                        results[index] = {
                            "backlink_id": job["backlink_id"],
                            "outcome": "TEMPORARILY_UNAVAILABLE",
                            "reason": "WORKER_TIMEOUT"
                            if isinstance(exc, TimeoutError)
                            else "WORKER_CRASH_OR_INVALID_RESULT",
                            "coverage": "deferred",
                            "error_type": type(exc).__name__,
                        }
                    finally:
                        if process:
                            await terminate_group(process)
            finally:
                queue.task_done()

    for job in jobs:
        safe_artifact(job)

    async def produce():
        for index, job in enumerate(jobs):
            await queue.put((index, job))
        for _ in range(concurrency):
            await queue.put(None)

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    producer = asyncio.create_task(produce())
    try:
        await asyncio.gather(producer, *workers)
    finally:
        for task in [producer, *workers]:
            task.cancel()
        await asyncio.gather(producer, *workers, return_exceptions=True)
    return [results[i] for i in range(len(jobs))]


def coverage_report(results):
    states = Counter(item.get("coverage", "unknown") for item in results)
    if len(results) != sum(states.values()) or not set(states) <= {
        "approved",
        "deferred",
        "confirmed_reject",
        "unknown",
    }:
        raise ValueError("Coverage counts do not reconcile")
    return {key: states[key] for key in ["approved", "deferred", "confirmed_reject", "unknown"]}


def resume_candidate(candidates, key, runtime):
    matches = [x for x in candidates if x["backlink_id"] == key]
    if len(matches) != 1 or not re.fullmatch(r"[a-zA-Z0-9_.-]+", key):
        raise ValueError("Resume requires one official WYRPlay joint key")
    hint = Path(runtime) / "human-queue" / (key + ".json")
    if not hint.is_file():
        raise ValueError("No human handoff hint for selected joint key")
    item = dict(matches[0])
    saved = json.loads(hint.read_text())
    if saved.get("project_id") != "wyrplay" or saved.get("backlink_id") != key or saved.get("domain") != item["domain"]:
        raise ValueError("Human hint identity mismatch")
    if (
        item["prior_status"] not in {"", "待提交", "需人工核查"}
        or item["prior_attempt"] not in {"", "0"}
        or item["outcome"] == "GLOBAL_BLACKLIST"
    ):
        raise ValueError("Protected/attempted/blacklisted row cannot resume")
    if (Path(runtime) / "submit-intents/wyrplay" / (key + ".json")).exists():
        raise ValueError("Persistent intent cannot resume submission")
    saved_url = saved.get("submit_url", "")
    if not official_url(saved_url, item["domain"]):
        raise ValueError("Resume URL changed; review required")
    if item["submit_url"] and saved_url != item["submit_url"] and not saved.get("discovery_visited"):
        raise ValueError("Resume URL changed; review required")
    if saved.get("discovery_visited") and saved_url not in saved["discovery_visited"]:
        raise ValueError("Resume URL lacks observed official discovery provenance")
    item["submit_url"] = saved_url
    item.update(resume=True, process=True)
    return item


async def recover_worker_result(job, result, api):
    """Crash reconciliation uses the existing single-use receipt; never clicks again."""
    from .batch_worker import record_non_submit, sheet_writer
    from .contracts import classify
    from .sheets import full_row, write_outcome

    intent = Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")
    if job["mode"] != "live":
        return result
    if not intent.is_file():
        async with sheet_writer(job["runtime_root"]):
            prior = full_row(api, job["row"])
            if (
                prior[:2] != ["wyrplay", job["backlink_id"]]
                or prior[3] not in {"", "待提交"}
                or prior[4] not in {"", "0"}
            ):
                return dict(result, outcome="需人工核查", reason="WORKER_CRASH_FRESH_STATE_REVIEW")
            record_non_submit(job, result, api, prior)
        return result
    receipt = json.loads(intent.read_text())
    async with sheet_writer(job["runtime_root"]):
        prior = full_row(api, job["row"])
        if prior[:2] != ["wyrplay", job["backlink_id"]]:
            raise ValueError("Crash reconciliation joint key changed")
        if intent.with_suffix(".sheet-intent").exists():
            # An ambiguous old write may have succeeded; do not reuse the +1 receipt.
            return dict(result, outcome="需人工核查", reason="PERSISTENT_INTENT_WRITE_REVIEW_REQUIRED")
        if prior[3] != "待提交" or prior[4] != receipt.get("prior_attempts"):
            raise ValueError("Crash reconciliation prior state changed")
        increment = int(receipt.get("dispatch_confirmed") is True)
        reason = "SUBMIT_RESULT_UNCONFIRMED" if increment else "SUBMIT_DISPATCH_UNCONFIRMED"
        outcome = classify("", "", submitted=True)
        outcome["reason"] = reason
        evidence = save_evidence(
            Path(job["evidence_dir"]) / "crash-recovery.json",
            {
                "project_id": "wyrplay",
                "backlink_id": job["backlink_id"],
                "reason": reason,
                "dispatch_confirmed": bool(increment),
                "dispatch": receipt.get("dispatch"),
                "attempt_increment": increment,
            },
        )
        write_outcome(
            api,
            job["row"],
            job["backlink_id"],
            outcome,
            reason=prior[8] + "\n[Batch crash] " + reason,
            summary=prior[9] + "\n" + str(evidence),
            attempt_increment=increment,
            attempt_receipt=intent if increment else None,
            expected_prior=prior,
        )
    return dict(result, outcome="需人工核查", reason=reason, coverage="deferred")


async def run_batch(
    pack,
    *,
    mode="dry-run",
    concurrency=2,
    limit=None,
    start_after=None,
    approval=None,
    resume_key=None,
    owner_human_action=False,
):
    import fcntl
    import secrets

    from .sheets import read_candidate_tables, service

    if mode not in {"dry-run", "live", "handoff"} or limit is not None and limit < 1:
        raise ValueError("Invalid batch mode/limit")
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise ValueError("Concurrency must be 1..4")
    if mode == "handoff" and (not owner_human_action or not resume_key):
        raise ValueError("Headed handoff requires explicit Owner action and one key")
    runtime = RUNTIME
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "batch-run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("BATCH_IN_USE: no parallel runs/profile conflicts") from None
        api = service(writable=mode == "live")
        candidates = select_candidates(read_candidate_tables(api), runtime)
        original_total = len(candidates)
        if resume_key:
            candidates = [resume_candidate(candidates, resume_key, runtime)]
            original_total = 1
        grant = validate_live_grant(approval, candidates, pack["root"].parents[1]) if mode == "live" else set()
        if mode == "live":
            # A grant is run-scoped and consumed once, even if the run later crashes.
            with Path(approval).with_suffix(".used").open("x") as stream:
                stream.write(now())
        run_id = now().replace("-", "").replace(":", "").split(".")[0].replace("T", "-")
        directory = runtime / ("batch-" + run_id + "-" + secrets.token_hex(3))
        directory.mkdir(mode=0o700)
        save_evidence(directory / "candidates.json", candidates)
        jobs: list[dict[str, Any]] = []
        deferred = []
        passed_cursor = start_after is None
        if start_after and start_after not in {x["backlink_id"] for x in candidates}:
            raise ValueError("Cursor key absent from official candidate pool")
        for item in candidates:
            key = item["backlink_id"]
            if not passed_cursor:
                deferred.append(dict(item, process=False, reason="CURSOR_DEFERRED", coverage="deferred"))
                passed_cursor = key == start_after
                continue
            if not item["process"]:
                deferred.append(item)
                continue
            if mode == "live" and key not in grant:
                deferred.append(dict(item, process=False, reason="OUTSIDE_OWNER_LIVE_SCOPE", coverage="deferred"))
                continue
            if limit is not None and len(jobs) >= limit:
                deferred.append(dict(item, process=False, reason="RUN_LIMIT_DEFERRED", coverage="deferred"))
                continue
            job = dict(
                item,
                mode=mode,
                runtime_root=str(runtime),
                evidence_dir=str(directory / item["domain"]),
                runtime_approved=mode == "live",
                approval_expires_at=json.loads(Path(approval).read_text())["expires_at"] if mode == "live" else None,
                owner_human_action=owner_human_action,
            )
            jobs.append(job)
        if mode == "handoff":
            print(
                "Opening only the selected dedicated browser for Owner human action. Final Submit is blocked; close that window when done, then run single-station resume.",
                file=sys.stderr,
                flush=True,
            )
        worker_results = await run_pool(
            jobs,
            runtime=directory / "workers",
            concurrency=1 if mode == "handoff" else concurrency,
            timeout=210 if mode == "handoff" else 90,
        )
        for i, result in enumerate(worker_results):
            if result.get("reason") in {"WORKER_TIMEOUT", "WORKER_CRASH_OR_INVALID_RESULT"}:
                worker_results[i] = await recover_worker_result(jobs[i], result, api)
        by_key = {x["backlink_id"]: x for x in deferred}
        by_key.update({x["backlink_id"]: x for x in worker_results})
        results = [by_key[x["backlink_id"]] for x in candidates]
        if len(results) != original_total:
            raise ValueError("Batch coverage mismatch")
        save_evidence(directory / "results.json", results)
        browser_events = []
        for result in worker_results:
            if result.get("browser_opened_at") and result.get("browser_closed_at"):
                browser_events.extend([(result["browser_opened_at"], 1), (result["browser_closed_at"], -1)])
        active = maximum = 0
        for _, change in sorted(browser_events):
            active += change
            maximum = max(maximum, active)
        report = {
            "project_id": "wyrplay",
            "mode": mode,
            "candidate_total": original_total,
            "workers_started": len(jobs),
            "concurrency": 1 if mode == "handoff" else concurrency,
            "same_domain_max": 1,
            "observed_browser_max": maximum,
            "browser_intervals_recorded": len(browser_events) // 2,
            "worker_groups_reclaimed": True,
            "window_outcomes": dict(Counter(x["outcome"] for x in worker_results)),
            "window_reasons": dict(Counter(x["reason"] for x in worker_results)),
            "coverage": coverage_report(results),
            "outcomes": dict(Counter(x["outcome"] for x in results)),
            "reasons": dict(Counter(x["reason"] for x in results)),
            "submit": 0 if mode != "live" else "See protected per-key receipts",
            "sheet_writes": 0 if mode != "live" else "See precise readback evidence",
            "runtime": str(directory),
            "rollout_started": mode == "live",
        }
        save_evidence(directory / "report.json", report)
        return report
