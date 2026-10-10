"""One headless station per process; human handoff is an explicit single-station command."""

import asyncio
import fcntl
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from .batch import adapter_gate, assessment_result, official_url
from .browser import isolated_profile, verify_listing
from .contracts import (
    RECEIPTS,
    classify,
    email_pending,
    field_value,
    load_project,
    now,
    save_evidence,
    timestamp,
    tracking_pending,
    validate_payload,
)
from .sheets import append_global_blacklist, full_row, is_blacklisted, service, write_outcome
from .workflow import fill_fields, human_boundary, run_submission, validate_final_form, verify_identity


@asynccontextmanager
async def sheet_writer(runtime):
    # All batch workers and recovery paths serialize official writes, across processes.
    path = Path(runtime) / "sheet-writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@asynccontextmanager
async def site_context(playwright, profile, *, headed=False, browser=None):
    root = isolated_profile(profile)
    if (root / "SingletonLock").exists() or (root / "SingletonLock").is_symlink():
        raise ValueError("PROFILE_IN_USE")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    context = None
    try:
        if browser:
            if headed:
                raise ValueError("Headed handoff requires the dedicated persistent profile")
            context = await browser.new_context(service_workers="block")
        else:
            context = await playwright.chromium.launch_persistent_context(
                str(root),
                channel="chrome",
                headless=not headed,
                service_workers="block",
                ignore_default_args=["--use-mock-keychain"],
            )
        if not browser:
            context._backlink_profile = str(root)
        yield context
    finally:
        if context:
            await asyncio.wait_for(context.close(), 10)


async def inspect_page(page, adapter, pack):
    if adapter.get("reveal_action"):
        from .matchbox import inspect_matchbox

        changed = await inspect_matchbox(page, adapter)
        if changed:
            return changed
    try:
        await human_boundary(page)
    except ValueError:
        return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_VERIFICATION_REQUIRED"}
    if not official_url(page.url, adapter["domain"]):
        return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "OWNER_LOGIN_REQUIRED"}
    if adapter.get("authenticated_selector"):
        if await page.locator(adapter["authenticated_selector"]).count() != 1:
            return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "OWNER_LOGIN_REQUIRED"}
    selectors = list(adapter.get("fields", {}).values()) + [
        s["selector"] for s in adapter.get("composed_fields", {}).values()
    ]
    for selector in selectors:
        if await page.locator(selector).count() != 1:
            return {"outcome": "需人工核查", "reason": "FORM_OR_SELECTOR_CHANGED"}
    return None


def record_non_submit(job, result, api, prior):
    from .candidates import action_result

    result = action_result(result, job.get("channel_basis"))
    runtime = Path(job["runtime_root"])
    evidence = {
        **result,
        "project_id": "wyrplay",
        "backlink_id": job["backlink_id"],
        "domain": job["domain"],
        "submit_url": job["submit_url"],
        "row": job["row"],
        "checked_at": now(),
        "submit": 0,
        "attempt_increment": 0,
    }
    path = save_evidence(Path(job.get("evidence_dir", runtime / "checks")) / (job["backlink_id"] + ".json"), evidence)
    if result.get("action_status") in {"去人工", "暂时不可用"}:
        resume_url = job["submit_url"]
        if not official_url(resume_url, job["domain"]):
            resume_url = next(
                (u for u in reversed(result.get("discovery_visited", [])) if official_url(u, job["domain"])), ""
            )
        save_evidence(
            runtime / "human-queue" / (job["backlink_id"] + ".json"),
            dict(
                evidence,
                submit_url=resume_url,
                resume_step="RECHECK_FORM",
                profile_path=str(runtime / "profiles" / job["domain"]),
            ),
        )
    if job["mode"] != "live":
        return
    if result["outcome"] == "GLOBAL_BLACKLIST":
        append_global_blacklist(api, job, result)
        return
    status = result.get("action_status")
    if status is None:
        raise ValueError("Unreviewed channel cannot receive a guessed production action")
    outcome = {"project_id": "wyrplay", "status": status, "evidence_code": "", "result_url": ""}
    write_outcome(
        api,
        job["row"],
        job["backlink_id"],
        outcome,
        reason=prior[8] + "\n[本次行动] " + result["action_reason"],
        summary=prior[9] + "\n" + status + " | " + str(path),
        expected_prior=prior,
    )


async def prepare_form(page, adapter, pack):
    await fill_fields(page, adapter, pack)
    for selector in adapter.get("ordinary_checkboxes", []):
        await page.locator(selector).check(timeout=10000)
    for field, choice in adapter.get("choice_fields", {}).items():
        value = field_value(
            pack, choice["confirmed_fact"], required=choice.get("required", False), platform=adapter["domain"]
        )

        def norm(s):
            return re.sub(r"[^a-z0-9]", "", s.casefold())

        if isinstance(value, dict) or norm(value) != norm(choice["option_label"]):
            raise ValueError("OWNER_INPUT_REQUIRED")
        control = page.locator(choice["control_selector"])
        if await control.count() != 1 or not choice.get("checked_verified"):
            raise ValueError("FORM_OR_SELECTOR_CHANGED")
        if not await control.is_checked():
            await page.locator(choice["click_selector"]).click(timeout=10000)
        if not await control.is_checked():
            raise ValueError("REQUIRED_FIELD_UNCONFIRMED")
    taxonomy = adapter.get("taxonomy")
    if taxonomy and taxonomy.get("native_select"):
        if (
            taxonomy.get("category")
            not in {"Games", "Gaming", "Entertainment", "Party Games", "Social Games", "Web Application"}
            or taxonomy.get("option_text") != taxonomy["category"]
            or not taxonomy.get("option_verified")
        ):
            raise ValueError("TAXONOMY_UNVERIFIED")
        control = page.locator(taxonomy["control_selector"])
        await control.select_option(label=taxonomy["option_text"], timeout=10000)
        if await control.input_value() != taxonomy["option_value"]:
            raise ValueError("TAXONOMY_UNCONFIRMED")
    elif taxonomy:
        if taxonomy.get("category") not in {
            "Gaming",
            "Games",
            "Entertainment",
            "Party Games",
            "Social Games",
            "Web Application",
        } or not taxonomy.get("selected_verified"):
            raise ValueError("TAXONOMY_UNVERIFIED")
        container = page.locator(taxonomy["selected_container_selector"])
        if taxonomy["selected_text"] not in await container.inner_text():
            await page.locator(taxonomy["control_selector"]).press(taxonomy["open_key"])
            option = page.locator(taxonomy["option_selector"]).filter(has_text=taxonomy["option_text"])
            if await option.count() != 1:
                raise ValueError("TAXONOMY_SELECTOR_CHANGED")
            await option.click(timeout=10000)
        if taxonomy["selected_text"] not in await container.inner_text():
            raise ValueError("TAXONOMY_UNCONFIRMED")
    if adapter.get("image_selector"):
        asset = (pack["root"] / adapter["image_asset"]).resolve()
        if asset not in [p.resolve() for p in pack["screenshots"]]:
            raise ValueError("Unapproved image asset")
        await page.locator(adapter["image_selector"]).set_input_files(str(asset), timeout=10000)
    if adapter.get("logo_required") and not await page.locator(adapter["logo_selector"]).evaluate(
        "(e)=>e.files.length>0"
    ):
        raise ValueError("REQUIRED_UPLOAD_MISSING")
    await human_boundary(page)
    final = page.locator(adapter["final_submit_selector"])
    if (
        await final.count() != 1
        or not await final.is_enabled()
        or not await final.is_visible()
        or (await final.inner_text()).strip() != adapter["final_submit_text"]
    ):
        raise ValueError("FINAL_ACTION_CHANGED")
    await validate_final_form(page, adapter, pack, repair=True)
    values = await page.locator("input:not([type=password]),select,textarea").evaluate_all(
        "es=>es.map(e=>e.type==='file'?[...e.files].map(f=>f.name):e.value)"
    )
    validate_payload(values)
    await verify_identity(page, adapter, pack)


async def execute_ready(page, adapter, pack, api, job):
    if job["mode"] != "live" or job.get("runtime_approved") is not True:
        raise ValueError("No runtime Owner LIVE grant")
    # A copy applies the scoped runtime grant; never modify the committed adapter.
    gate = adapter_gate(adapter, pack)
    if gate:
        raise ValueError(gate["reason"])
    if not job.get("approval_expires_at") or timestamp(job["approval_expires_at"]) <= timestamp(now()):
        raise ValueError("Runtime Owner grant expired/missing")
    runtime_adapter = dict(adapter, automatic_submit_allowed=True)
    async with sheet_writer(job["runtime_root"]):
        prior = full_row(api, job["row"])
        intent = Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")
        if prior[:2] != ["wyrplay", job["backlink_id"]] or prior[4] not in {"", "0"} or intent.exists():
            raise ValueError("Joint key/attempt/intent blocks Submit")
        live_gate = await readonly_ready(page, adapter)
        if live_gate["outcome"] != "READY_TO_SUBMIT":
            raise ValueError(live_gate["reason"])
        if prior[3] != "待提交":
            if prior[3] in {"成功", "审核中", "历史未验证"} or prior[7]:
                raise ValueError("Existing state blocks Submit")
            ready = {"project_id": "wyrplay", "status": "待提交", "result_url": "", "evidence_code": ""}
            write_outcome(
                api,
                job["row"],
                job["backlink_id"],
                ready,
                reason=prior[8] + "\n[Batch] LIVE_OWNER_AUTHORIZED_READY",
                summary=prior[9] + "\nAll current form gates passed; Attempt unchanged",
                expected_prior=prior,
            )
        live_gate = await readonly_ready(page, adapter)
        if live_gate["outcome"] != "READY_TO_SUBMIT":
            raise ValueError(live_gate["reason"])
        if timestamp(job["approval_expires_at"]) <= timestamp(now()):
            raise ValueError("Runtime Owner grant expired")
        before_text = (await page.locator("body").inner_text(timeout=10000)).casefold()
        before_receipts = [marker for marker in RECEIPTS if marker in before_text]
        result = await run_submission(
            page,
            runtime_adapter,
            pack,
            api,
            row=job["row"],
            backlink_id=job["backlink_id"],
            runtime=job["runtime_root"],
            allow_submit=True,
            blacklisted=False,
        )
    return {
        "outcome": {"成功": "SUCCESS", "审核中": "PENDING"}.get(result["status"], "需人工核查"),
        "reason": result["reason"],
        "receipt": result,
        "before_receipts": before_receipts,
        "coverage": "approved" if result["evidence_code"] else "deferred",
    }


async def followup_proofs(page, adapter, api, job, *, before_receipts, connector=None):
    """Observed URLs only; proof upgrade never increments Attempt a second time."""
    intent = Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")
    receipt = json.loads(intent.read_text())
    if receipt.get("dispatch_confirmed") is not True:
        return None
    expected_dispatch = (
        {key: adapter["submission_request"][key] for key in ("method", "host", "path")}
        if adapter.get("submission_request")
        else receipt["dispatch"]
    )
    if (
        receipt.get("project_id"),
        receipt.get("backlink_id"),
        receipt.get("attempt_increment"),
        receipt.get("dispatch"),
    ) != ("wyrplay", job["backlink_id"], 1, expected_dispatch):
        raise ValueError("Followup proof requires matching persisted dispatch")
    # Bound observation time; no repeat action and no fabricated email fallback.
    await page.wait_for_timeout(1000)
    text = await page.locator("body").inner_text(timeout=10000)
    proof = (
        classify("\n".join(before_receipts), text, submitted=True).get("proof")
        if official_url(page.url, adapter["domain"])
        else None
    )
    tracking = tracking_pending(
        page.url, text, previous_url=adapter["submit_url"], submitted=True, domain=adapter["domain"]
    )
    proof = tracking or proof
    links = await page.locator("a[href]").evaluate_all("es=>es.map(e=>e.href).filter(x=>/wyrplay/i.test(x))")
    # Anonymous E4 uses a separate browser, never the authenticated profile.
    from playwright.async_api import async_playwright

    links = [url for url in links if official_url(url, adapter["domain"])]
    if official_url(page.url, adapter["domain"]) and page.url != adapter["submit_url"]:
        links.insert(0, page.url)
    if links:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            try:
                for url in list(dict.fromkeys(links))[:3]:
                    if official_url(url, adapter["domain"]):
                        public = await verify_listing(browser, url)
                        if public:
                            proof = public
                            break
            finally:
                await asyncio.wait_for(browser.close(), 10)
    if not proof and connector is not None:
        recipient = "support@wyrplay.com"
        try:
            messages = await connector(
                "search_messages",
                {
                    "query": f"to:{recipient} from:{job['domain']} after:{int(timestamp(receipt['started_at']).timestamp())} -in:spam -in:trash",
                    "max_results": 5,
                },
            )
        except (ConnectionError, OSError):
            save_evidence(
                Path(job["evidence_dir"]) / "post-mail-check.json", {"outcome": "EMAIL_CONFIRMATION_UNAVAILABLE"}
            )
            messages = None
        matched = [
            p
            for m in messages or []
            if (p := email_pending(m, domain=job["domain"], recipient=recipient, started_at=receipt["started_at"]))
        ]
        if len(matched) == 1:
            proof = matched[0]
    if not proof:
        return None
    result = (
        classify("\n".join(before_receipts), " ".join(proof["dom_evidence"]), submitted=True)
        if proof.get("evidence_code") == "E1"
        else classify("", "", submitted=True, proof=proof)
    )
    if result["status"] not in {"审核中", "成功"}:
        return None
    path = save_evidence(Path(job["evidence_dir"]) / "followup-proof.json", proof)
    async with sheet_writer(job["runtime_root"]):
        prior = full_row(api, job["row"])
        if prior[:2] != ["wyrplay", job["backlink_id"]] or prior[4] != "1":
            raise ValueError("Followup joint key/Attempt changed")
        if prior[3] == "成功" or prior[3] == "审核中" and result["status"] == "审核中":
            return None
        write_outcome(
            api,
            job["row"],
            job["backlink_id"],
            result,
            reason=prior[8] + "\n[Batch followup] " + result["reason"],
            summary=prior[9] + "\n" + result["evidence_code"] + " | " + str(path),
            expected_prior=prior,
            attempt_increment=0,
        )
    return {
        "outcome": "SUCCESS" if result["status"] == "成功" else "PENDING",
        "reason": result["reason"],
        "receipt": result,
        "coverage": "approved",
    }


async def run_live_discovery(job, pack, api, playwright, prior, *, connector=None):
    """Keep the same session from discovery through its single final action."""
    from .discovery import discover

    async def submit(page, adapter):
        try:
            await prepare_form(page, adapter, pack)
        except ValueError as exc:
            if str(exc).startswith(("FORM_VALIDATION_UNRESOLVED", "APPROVED_TEXT_DOES_NOT_FIT")):
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "FORM_VALIDATION_UNRESOLVED",
                    "validation_fields": str(exc).split(":", 1)[-1].strip().split(", "),
                    "reached_submit": True,
                    "submit_clicked": False,
                    "filled_fields": list(adapter["fields"]),
                    "automation_pending": True,
                }
            raise
        result = await execute_ready(page, adapter, pack, api, dict(job, submit_url=page.url))
        final = (
            await followup_proofs(
                page, adapter, api, job, before_receipts=result["before_receipts"], connector=connector
            )
            or result
        )
        intent = json.loads(
            (Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")).read_text()
        )
        return dict(
            final,
            filled_fields=list(adapter["fields"]),
            reached_submit=True,
            submit_clicked=True,
            dispatch_confirmed=intent["dispatch_confirmed"],
            dispatch=intent["dispatch"],
            attempt_increment=intent["attempt_increment"],
        )

    profile = Path(job["runtime_root"]) / "profiles" / job["domain"]
    opened_at = now()
    async with site_context(playwright, profile) as context:
        result = await discover(await context.new_page(), pack, job, on_ready=submit, connector=connector)
    if result.get("reason") == "GOOGLE_SESSION_UNAVAILABLE":
        owner_profile = Path("~/.backlink-autofill/browser-profile").expanduser()
        if owner_profile.is_dir():
            profile_lock = pack.setdefault("owner_profile_lock", asyncio.Lock())
            async with profile_lock:
                async with site_context(playwright, owner_profile) as context:
                    result = await discover(await context.new_page(), pack, job, on_ready=submit, connector=connector)
    if job.get("owner_human_action") and result.get("owner_action_proof") and not pack.get("human_window_used"):
        from .automation import AuthGuard, fill_known_controls, owner_boundary

        pack["human_window_used"] = True
        async with site_context(playwright, profile, headed=True) as context:
            page = await context.new_page()
            auth = AuthGuard(job["domain"])
            auth.phase = "AUTH"

            async def guard(route):
                await auth.refresh_route(route, page)

            await page.route("**/*", guard)
            await page.goto(result.get("submit_url") or job["submit_url"], wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(800)
            result["filled_fields"] = await fill_known_controls(page, pack, job["domain"])
            print(json.dumps({"human_wait": job["backlink_id"], "reason": result["reason"]}), flush=True)
            for _ in range(24):
                await asyncio.sleep(5)
                if page.is_closed():
                    break
                if await owner_boundary(page) is None:
                    await page.unroute("**/*", guard)
                    result = await discover(
                        page,
                        pack,
                        dict(job, submit_url=page.url, resume_in_place=True),
                        on_ready=submit,
                        connector=connector,
                    )
                    result["human_resumed"] = True
                    break
            else:
                result["human_wait_timed_out"] = True
    result.update(browser_opened_at=opened_at, browser_closed_at=now())
    if not (Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")).exists():
        async with sheet_writer(job["runtime_root"]):
            record_non_submit(dict(job, submit_url=result.get("submit_url", "")), result, api, prior)
    result.setdefault("coverage", "deferred")
    return result


async def run_site(job, pack, api, playwright, *, connector=None):
    prior = full_row(api, job["row"])
    if prior[:2] != ["wyrplay", job["backlink_id"]] or prior[4] not in {"", "0"}:
        return {"outcome": "需人工核查", "reason": "FRESH_JOINT_KEY_OR_ATTEMPT_BLOCK", "coverage": "deferred"}
    if is_blacklisted(api, job["backlink_id"], job["domain"]):
        return {"outcome": "GLOBAL_BLACKLIST", "reason": "FRESH_BLACKLIST_BLOCK", "coverage": "confirmed_reject"}
    if (
        prior[3] in {"成功", "审核中", "历史未验证"}
        or prior[7]
        or re.search(r"SUBMIT_(?:RESULT|DISPATCH)_UNCONFIRMED", prior[8])
    ):
        return {"outcome": "需人工核查", "reason": "PROTECTED_EXISTING_STATUS", "coverage": "deferred"}
    if (Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")).exists():
        return {"outcome": "需人工核查", "reason": "PERSISTENT_SUBMIT_INTENT", "coverage": "deferred"}
    if job["mode"] == "live":
        return await run_live_discovery(job, pack, api, playwright, prior, connector=connector)
    adapter_path = pack["root"] / "adapters" / (job["domain"] + ".json")
    if not adapter_path.is_file():
        from .discovery import discover

        profile = Path(job["runtime_root"]) / "profiles" / job["domain"]
        async with site_context(playwright, profile) as ctx:
            opened_at = now()
            result = await discover(await ctx.new_page(), pack, job)
        owner_profile = Path("~/.backlink-autofill/browser-profile").expanduser()
        if result.get("reason") == "GOOGLE_SESSION_UNAVAILABLE" and owner_profile.is_dir():
            # The initial station context is already closed. Reuse the existing Owner session
            # without cookie export or another simultaneous browser. Serialize this one profile.
            with (Path(job["runtime_root"]) / "owner-oauth-profile.lock").open("a") as profile_lock:
                try:
                    fcntl.flock(profile_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    result = {
                        "outcome": "TEMPORARILY_UNAVAILABLE",
                        "reason": "OWNER_SESSION_PROFILE_BUSY",
                        "automation_pending": True,
                    }
                else:
                    try:
                        async with site_context(playwright, owner_profile) as owner_ctx:
                            result = await discover(await owner_ctx.new_page(), pack, job)
                    except ValueError as exc:
                        if str(exc) != "PROFILE_IN_USE":
                            raise
                        result = {
                            "outcome": "TEMPORARILY_UNAVAILABLE",
                            "reason": "OWNER_SESSION_PROFILE_BUSY",
                            "automation_pending": True,
                        }
        result.update(browser_opened_at=opened_at, browser_closed_at=now())
        recovery_job = dict(job, submit_url=result.get("submit_url", job["submit_url"]))
        if result["outcome"] != "READY_TO_SUBMIT" or job["mode"] == "dry-run":
            async with sheet_writer(job["runtime_root"]):
                record_non_submit(recovery_job, result, api, prior)
        if result["outcome"] != "READY_TO_SUBMIT" or job["mode"] == "dry-run":
            return dict(
                result,
                coverage="approved"
                if result["outcome"] == "READY_TO_SUBMIT"
                else "confirmed_reject"
                if result["outcome"] == "GLOBAL_BLACKLIST"
                else "deferred"
                if result["outcome"] != "需人工核查"
                else "unknown",
            )
        job = recovery_job
    adapter = json.loads(adapter_path.read_text())
    # A generated, official-provenance entry is reusable when the master URL is blank;
    # a conflicting existing master URL still stops for review, never silently changes.
    if (
        not job["submit_url"]
        and adapter.get("provenance", {}).get("official_source") == adapter.get("submit_url")
        and official_url(adapter.get("submit_url", ""), job["domain"])
    ):
        job = dict(job, submit_url=adapter["submit_url"])
    if adapter.get("domain") != job["domain"] or adapter.get("submit_url") != job["submit_url"]:
        return {"outcome": "需人工核查", "reason": "ADAPTER_OFFICIAL_URL_MISMATCH", "coverage": "unknown"}
    gate = None if adapter.get("assessment") else adapter_gate(adapter, pack)
    if gate:
        async with sheet_writer(job["runtime_root"]):
            record_non_submit(job, gate, api, prior)
        return dict(gate, coverage="deferred")
    profile = Path(job["runtime_root"]) / "profiles" / job["domain"]
    try:
        async with site_context(playwright, profile) as ctx:
            if job["mode"] == "dry-run":
                await ctx.route("**/*", readonly_requests)
            page = await ctx.new_page()
            url = adapter.get("assessment", {}).get("source_url", adapter["submit_url"])
            if not official_url(url, job["domain"]):
                raise ValueError("Unofficial adapter URL")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            result = await inspect_page(page, adapter, pack)
            if (not response or response.status >= 400) and (
                not result or result["outcome"] != "HUMAN_VERIFICATION_REQUIRED"
            ):
                result = {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "HTTP_UNAVAILABLE_NOT_PERMANENT_PROOF"}
            elif not result and adapter.get("assessment"):
                result = assessment_result(
                    adapter["assessment"], await page.locator("body").inner_text(), domain=job["domain"]
                )
            elif not result:
                if job["mode"] == "dry-run":
                    # Readonly: field facts, mappings, session and final semantics; LIVE rechecks actual filled DOM.
                    result = await readonly_ready(page, adapter)
                else:
                    await prepare_form(page, adapter, pack)
                    result = await execute_ready(page, adapter, pack, api, job)
                    result = (
                        await followup_proofs(page, adapter, api, job, before_receipts=result["before_receipts"])
                        or result
                    )
                    return result
            # Context is released before recording a manual task/write.
    except ValueError as exc:
        reason = str(exc)
        allowed = {
            "HUMAN_VERIFICATION_REQUIRED",
            "OWNER_INPUT_REQUIRED",
            "PROFILE_IN_USE",
            "FORM_OR_SELECTOR_CHANGED",
            "FINAL_ACTION_CHANGED",
            "REQUIRED_FIELD_UNCONFIRMED",
            "TAXONOMY_UNCONFIRMED",
            "TAXONOMY_SELECTOR_CHANGED",
            "TAXONOMY_UNVERIFIED",
            "REQUIRED_UPLOAD_MISSING",
        }
        if reason.split(":")[0] not in allowed:
            raise
        result = {
            "outcome": reason if reason in {"HUMAN_VERIFICATION_REQUIRED", "OWNER_INPUT_REQUIRED"} else "需人工核查",
            "reason": reason.split(":")[0],
        }
    async with sheet_writer(job["runtime_root"]):
        record_non_submit(job, result, api, prior)
    return dict(
        result,
        coverage="approved"
        if result["outcome"] == "READY_TO_SUBMIT"
        else "confirmed_reject"
        if result["outcome"] == "GLOBAL_BLACKLIST"
        else "deferred"
        if result["outcome"] != "需人工核查"
        else "unknown",
    )


async def main(path):
    job = json.loads(Path(path).read_text())
    if (
        job.get("project_id") != "wyrplay"
        or not re.fullmatch(r"[a-zA-Z0-9_.-]+", job["backlink_id"])
        or not re.fullmatch(r"[a-z0-9.-]+", job["domain"])
    ):
        raise ValueError("Unsafe worker identity")
    pack = load_project("wyrplay", Path(__file__).resolve().parents[2] / "projects/wyrplay")
    if (
        job["mode"] not in {"dry-run", "live", "handoff", "human-loop"}
        or job["mode"] == "live"
        and job.get("runtime_approved") is not True
    ):
        raise ValueError("No scoped runtime approval")
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        api = service(writable=job["mode"] == "live")
        if job["mode"] == "human-loop":
            from .human_loop import recheck_handoff

            result = await recheck_handoff(job, pack, api, pw)
        else:
            result = await handoff(job, api, pw) if job["mode"] == "handoff" else await run_site(job, pack, api, pw)
    save_evidence(job["result_path"], dict(result, backlink_id=job["backlink_id"]))


async def handoff(job, api, playwright):
    if job.get("owner_human_action") is not True or not job.get("resume"):
        raise ValueError("Headed browser requires explicit Owner human action for a queued single station")
    prior = full_row(api, job["row"])
    if (
        prior[:2] != ["wyrplay", job["backlink_id"]]
        or prior[3] not in {"", "待提交", "需人工核查", "去人工"}
        or prior[4] not in {"", "0"}
        or is_blacklisted(api, job["backlink_id"], job["domain"])
    ):
        raise ValueError("Protected row cannot open submission handoff")
    if (Path(job["runtime_root"]) / "submit-intents/wyrplay" / (job["backlink_id"] + ".json")).exists():
        raise ValueError("Existing submit intent cannot handoff for resubmission")
    if not official_url(job["submit_url"], job["domain"]):
        raise ValueError("Handoff URL must be the official verified entry")
    async with site_context(playwright, Path(job["runtime_root"]) / "profiles" / job["domain"], headed=True) as ctx:
        # Guard every request to the verified final endpoint, including manually clicked buttons.
        pack_root = Path(__file__).resolve().parents[2] / "projects/wyrplay"
        adapter_path = pack_root / "adapters" / (job["domain"] + ".json")
        from .human_loop import verified_matcher

        adapter = json.loads(adapter_path.read_text()) if adapter_path.is_file() else None
        matcher = verified_matcher(adapter)

        from .automation import AuthGuard

        auth = AuthGuard(job["domain"], matcher)
        auth.phase = "AUTH"
        page = await ctx.new_page()

        async def no_submit(route):
            await auth.refresh_route(route, page)

        await ctx.route("**/*", no_submit)
        closed = asyncio.Event()
        ctx.on("close", lambda _: closed.set())
        await page.goto(job["submit_url"], wait_until="domcontentloaded", timeout=20000)
        print(
            "Owner human handoff open for "
            + job["domain"]
            + "; final dispatch is blocked. Close dedicated window when finished.",
            flush=True,
        )
        await asyncio.wait_for(closed.wait(), 180)
    return {
        "outcome": "需人工核查",
        "reason": "HUMAN_ACTION_FINISHED_RECHECK_REQUIRED",
        "backlink_id": job["backlink_id"],
        "submit": 0,
    }


async def readonly_requests(route):
    if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
        await route.abort()
    else:
        await route.fallback()


async def readonly_ready(page, adapter):
    if adapter.get("login_required") is not False and not adapter.get("authenticated_selector"):
        return {"outcome": "需人工核查", "reason": "SESSION_PROOF_UNVERIFIED"}
    final = page.locator(adapter["final_submit_selector"])
    if (
        await final.count() != 1
        or not await final.is_visible()
        or not await final.is_enabled()
        or (await final.inner_text()).strip() != adapter["final_submit_text"]
    ):
        return {"outcome": "需人工核查", "reason": "FINAL_ACTION_CHANGED"}
    selectors = list(adapter.get("fields", {}).values()) + adapter.get("ordinary_checkboxes", [])
    selectors += adapter.get("submitted_controls", [])
    selectors += [s["selector"] for s in adapter.get("composed_fields", {}).values()]
    selectors += [c["control_selector"] for c in adapter.get("choice_fields", {}).values()]
    selectors += [adapter[k] for k in ["logo_selector", "image_selector", "screenshots_selector"] if adapter.get(k)]
    if adapter.get("taxonomy"):
        selectors.append(adapter["taxonomy"]["control_selector"])
    for selector in selectors:
        if await page.locator(selector).count() != 1:
            return {"outcome": "需人工核查", "reason": "FORM_OR_SELECTOR_CHANGED"}
    unknown = await page.locator("input[required],textarea[required],select[required]").evaluate_all(
        "(es, ss)=>es.filter(e=>!ss.some(s=>e.matches(s))).length", selectors
    )
    if unknown:
        return {
            "outcome": "OWNER_INPUT_REQUIRED",
            "reason": "UNMAPPED_REQUIRED_FIELDS",
            "required_unknown_count": unknown,
        }
    return {"outcome": "READY_TO_SUBMIT", "reason": "READONLY_ADAPTER_FORM_GATE_PASSED", "coverage": "approved"}


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
