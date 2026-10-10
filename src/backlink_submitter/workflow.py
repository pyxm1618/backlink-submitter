"""Protected single-station adapter flow; runtime authorization is supplied by the caller."""

import asyncio
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Error as BrowserError

from .contracts import (
    CONTACT,
    PROJECT,
    RECEIPTS,
    TARGET,
    classify,
    composed_value,
    field_value,
    fitting_field_value,
    identity_mapped,
    now,
    save_evidence,
    submit_once,
    validate_payload,
)
from .sheets import full_row, is_blacklisted, write_outcome


async def human_boundary(page):
    from .automation import owner_boundary

    boundary = await owner_boundary(page)
    if boundary:
        raise ValueError(boundary["reason"])


async def control_value(control):
    if await control.evaluate("e=>e.isContentEditable||!['INPUT','SELECT','TEXTAREA'].includes(e.tagName)"):
        return (await control.inner_text()).strip()
    return await control.input_value(timeout=10000)


async def fill_fields(page, adapter, pack):
    await human_boundary(page)
    if adapter.get("review_page"):
        await verify_identity(page, adapter, pack)
        return {"logo": False, "screenshots": 0}
    if adapter.get("rich_text_editor") == "hackstack":
        from .hackstack import fill_form

        return await fill_form(page, pack)
    if adapter.get("rich_text_editor") == "telegraph":
        from .publication import fill_publication

        await fill_publication(page, pack)
        return {"logo": False, "screenshots": 0}
    for field, selector in adapter["fields"].items():
        value = field_value(
            pack, field, required=field in adapter.get("required_fields", []), platform=adapter["domain"]
        )
        if isinstance(value, dict):
            raise ValueError("OWNER_INPUT_REQUIRED: " + field)
        if value:
            control = page.locator(selector)
            value = fitting_field_value(pack, field, value, await control.evaluate("e=>e.maxLength"))
            if await control.evaluate("(e)=>e.tagName") == "SELECT":
                await control.select_option(label=value, timeout=10000)
            else:
                await control.fill(value, timeout=10000)
    for spec in adapter.get("composed_fields", {}).values():
        await page.locator(spec["selector"]).fill(composed_value(pack, spec), timeout=10000)
    uploaded = {"logo": False, "screenshots": 0}
    if adapter.get("logo_selector"):
        logo = pack["logo_svg"] if adapter.get("logo_format") == "svg" else pack["logo_png"]
        await page.locator(adapter["logo_selector"]).set_input_files(str(logo), timeout=10000)
        uploaded["logo"] = True
    if adapter.get("screenshots_selector"):
        assets = pack["screenshots"][: adapter.get("screenshot_limit", 5)]
        await page.locator(adapter["screenshots_selector"]).set_input_files([str(p) for p in assets], timeout=10000)
        uploaded["screenshots"] = len(assets)
    return uploaded


async def verify_identity(page, adapter, pack):
    if not identity_mapped(adapter, pack):
        raise ValueError("Required identity mapping missing")
    for field, selector in adapter.get("fields", {}).items():
        if field in {"Product / App Name", "Website URL", "Public Contact Email"}:
            if await control_value(page.locator(selector)) != pack["fields"][field]:
                raise ValueError("Actual DOM identity mismatch")
    for spec in adapter.get("composed_fields", {}).values():
        expected = composed_value(pack, spec)
        actual = await page.locator(spec["selector"]).input_value(timeout=10000)
        validate_payload(actual)
        if actual != expected or "WYRPlay" not in actual or TARGET not in actual:
            raise ValueError("Actual DOM composed identity mismatch")


async def validate_final_form(page, adapter, pack, *, repair=False):
    """Inspect the current form; fix approved values before consuming its one Submit."""
    final = page.locator(adapter["final_submit_selector"])
    await final.evaluate(
        "e=>{const f=e.form||e.closest('form')||e.closest('[role=dialog]')||document.body;f.setAttribute('data-backlink-final-form','current')}"
    )
    form = page.locator('[data-backlink-final-form="current"]')
    if repair:
        from .automation import fill_known_controls

        await fill_known_controls(page, pack, adapter["domain"])
        preferred = ["Games", "Gaming", "Entertainment", "Party Games", "Social Games", "Web Application"]
        for select in await form.locator('select[name*="cat" i],select[id*="categor" i]').all():
            if not await select.is_visible():
                continue
            options = await select.locator("option").all_text_contents()
            chosen = next((p for p in preferred if p in options), None)
            if chosen:
                await select.select_option(label=chosen)
        for control in await form.locator("input[type=checkbox],input[type=radio]").all():
            name = await control.get_attribute("name") or ""
            if not re.search(r"^(?:cat(?:egor(?:y|ies))?)(?:\[\])?$", name, re.I):
                continue
            label = await control.evaluate("e=>[...e.labels||[]].map(l=>l.innerText.trim()).join(' ')")
            if label in preferred and await control.is_visible():
                await control.check()
                break
    invalid = await form.locator("input,textarea,select").evaluate_all("""es=>es.filter(e=>{
      const visible=!!(e.getClientRects().length);const required=e.required||e.getAttribute('aria-required')==='true';
      if(e.disabled)return false;
      if(e.type==='radio'&&required&&visible)return ![...es].some(c=>c.name===e.name&&c.type==='radio'&&c.checked);
      if(e.type==='checkbox'&&required&&visible)return !e.checked;
      if(e.type==='file'&&required&&visible)return !e.files.length;
      if(required&&visible&&!e.value.trim())return true;
      return e.willValidate&&!e.checkValidity();
    }).map(e=>e.name||e.id||'unidentified required control')""")
    errors = await form.locator(
        '[role="alert"],.invalid-feedback,.field-error,.error-message,[aria-invalid="true"]'
    ).evaluate_all(
        "es=>es.filter(e=>e.getClientRects().length&&(e.getAttribute('aria-invalid')==='true'||/required|invalid|must (?:enter|select|fill)|missing|too (?:short|long)|went wrong|error/i.test(e.innerText))).map(e=>e.getAttribute('data-field')||e.id||'visible validation error')"
    )
    category_missing = await form.locator(
        'select[name*="cat" i],input[name="cat[]"],input[name="categories"],input[name="category"]'
    ).evaluate_all(
        "es=>es.some(e=>e.getClientRects().length)&&!es.some(e=>e.tagName==='SELECT'?e.value.trim():e.checked)"
    )
    for field, selector in adapter.get("fields", {}).items():
        if field in {"Short Description", "Medium Description", "Long Description", "One-line Pitch / Tagline"}:
            if not await control_value(page.locator(selector)):
                invalid.append(field)
    await verify_identity(page, adapter, pack)
    if invalid or errors or category_missing:
        raise ValueError(
            "FORM_VALIDATION_UNRESOLVED: " + ", ".join(invalid + errors + (["Category"] if category_missing else []))
        )
    return {"native_valid": True, "visible_required_valid": True, "visible_errors": 0, "identity_verified": True}


async def submission_response(response, domain, native_action):
    """Keep response metadata and fixed receipt markers; never persist provider JSON."""
    from urllib.parse import unquote_to_bytes

    request = response.request
    parsed = urlparse(request.url)
    if request.method not in {"POST", "PUT", "PATCH"} or (parsed.hostname or "").removeprefix(
        "www."
    ) != domain.removeprefix("www."):
        return None
    outgoing = unquote_to_bytes(request.post_data_buffer or b"").lower()
    if not (b"wyrplay" in outgoing and b"wyrplay.com" in outgoing) and request.url != native_action:
        return None
    result = {"method": request.method, "host": parsed.hostname, "path": parsed.path, "status": response.status}
    if response.status >= 400 or "application/json" not in response.headers.get("content-type", ""):
        return result
    try:
        payload = await asyncio.wait_for(response.json(), 3)
    except (ValueError, TimeoutError, BrowserError):
        return dict(result, response_parse="unavailable")
    if (
        not isinstance(payload, dict)
        or payload.get("errors")
        or payload.get("error")
        or payload.get("success") is False
    ):
        return result
    words = " ".join(str(payload.get(k, "")) for k in ["status", "message", "detail"]).casefold()
    marker = next((r for r in RECEIPTS if r in words), None)
    if payload.get("status") in {"pending", "review", "moderation"}:
        marker = "pending review"
    if response.status == 201 and payload.get("id"):
        marker = marker or "submission received"
    if marker:
        result["receipt_marker"] = marker
    return result


async def run_submission(page, adapter, pack, api, *, row, backlink_id, runtime, allow_submit, blacklisted):
    """Owner-authorized single platform only. Evidence is persisted before Sheets mutation."""
    domain = adapter["domain"]
    if not re.fullmatch(r"[a-z0-9.-]+", domain) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", backlink_id):
        raise ValueError("Unsafe domain/backlink key")
    if not allow_submit or not adapter.get("automatic_submit_allowed") or not adapter.get("final_action_verified"):
        raise ValueError("Final Submit not authorized/verified for this adapter")
    if not adapter.get("free_verified") or adapter.get("reciprocal_required"):
        raise ValueError("Free eligibility/reciprocal Owner decision required")
    host = urlparse(page.url).hostname or ""
    if host.removeprefix("www.") != domain.removeprefix("www.") and not host.endswith(
        "." + domain.removeprefix("www.")
    ):
        raise ValueError("Page is not the official adapter domain")
    intent_path = Path(runtime) / "submit-intents" / PROJECT / (backlink_id + ".json")
    if intent_path.exists():
        raise ValueError("Existing intent; no automatic duplicate")
    await human_boundary(page)
    await validate_final_form(page, adapter, pack)
    if blacklisted or is_blacklisted(api, backlink_id, domain):
        raise ValueError("Blacklisted platform; no Submit")
    prior = full_row(api, row)
    if prior[:2] != [PROJECT, backlink_id]:
        raise ValueError("Joint key mismatch before any Submit")
    required_unknown: list[str] = []
    values = await page.locator("input:not([type=password]),textarea,select").evaluate_all(
        "nodes=>nodes.filter(e=>!['checkbox','radio'].includes(e.type)||e.checked).map(e=>({name:e.name||e.id,value:e.type==='file'?[...e.files].map(f=>f.name):e.value}))"
    )
    validate_payload(values)  # inspect real form, not only the selected pack fields
    await verify_identity(page, adapter, pack)
    # Selectors and taxonomy have to be qualified before this point; never infer an AI category.
    categories = [v["value"] for v in values if re.search(r"category|tags|product_type", v["name"], re.I)]
    if re.search(r"\b(?:AI|AI Tool|AI Generator|LLM|GPT)\b", str(categories), re.I):
        raise ValueError("WYRPlay AI category prohibited")
    runtime = Path(runtime)
    run_id = now().replace("-", "").replace(":", "").split(".")[0].replace("T", "-") + "-" + secrets.token_hex(3)
    site = runtime / run_id / domain
    site.mkdir(parents=True)
    started = now()
    before = await page.locator("body").inner_text(timeout=10000)
    before_path, after_path = site / "before.png", site / "after.png"
    await page.screenshot(path=str(before_path), full_page=True, timeout=10000)
    intent_path = runtime / "submit-intents" / PROJECT / (backlink_id + ".json")
    increment = 0
    error = None
    native_action = await page.locator(adapter["final_submit_selector"]).evaluate(
        "e=>(e.form||e.closest('form'))?.action||''"
    )
    response_tasks: list[asyncio.Task] = []

    def observe_response(response):
        if len(response_tasks) < 20:
            response_tasks.append(asyncio.create_task(submission_response(response, domain, native_action)))

    page.on("response", observe_response)
    try:
        increment = await submit_once(
            intent_path,
            payload={"name": "WYRPlay", "url": TARGET, "email": CONTACT, "ai_product": False},
            click=lambda: page.locator(adapter["final_submit_selector"]).click(timeout=30000),
            project_id=PROJECT,
            prior_status=prior[3],
            final_action=True,
            qualified=adapter["qualification"] in {"QUALIFIED_A", "QUALIFIED_B", "QUALIFIED_C"},
            blacklisted=blacklisted,
            human_verification=False,
            missing_required=required_unknown,
            backlink_id=backlink_id,
            prior_attempts=prior[4],
            page=page,
            submission_request=adapter.get("submission_request"),
            dispatch_timeout_ms=adapter.get("dispatch_timeout_ms", 30000),
            before_submit={
                "url": urlparse(page.url)._replace(query="", fragment="").geturl(),
                "form_values": [
                    {"field": field, "value": await control_value(page.locator(selector))}
                    for field, selector in adapter.get("fields", {}).items()
                ],
                "screenshot": str(before_path),
                "time": started,
                "platform_id": backlink_id,
            },
        )
        # SPA responses can arrive after the click promise and request event.
        await page.wait_for_timeout(1200)
    except ValueError:
        raise  # gate refusal: no submission result exists
    except Exception:
        error = "Submit action response unconfirmed; inspect intent; no automatic retry"
    finally:
        page.remove_listener("response", observe_response)
    responses = [r for r in await asyncio.gather(*response_tasks) if r]
    receipt = json.loads(intent_path.read_text())
    result = classify(before, "", submitted=True)
    if not increment:
        result["reason"] = "SUBMIT_DISPATCH_UNCONFIRMED"
    checkpoint = dict(
        result,
        run_id=run_id,
        project_id=PROJECT,
        domain=domain,
        submit_url=adapter["submit_url"],
        started_at=started,
        finished_at=now(),
        action="true_submit" if increment else "submit_dispatch_unconfirmed",
        final_url=urlparse(page.url)._replace(query="", fragment="").geturl(),
        listing_url="",
        tracking_url="",
        dom_evidence=[],
        email_message_id=None,
        screenshot_before=str(before_path),
        screenshot_after="",
        error=error,
        attempt_increment=increment,
        dispatch_confirmed=receipt["dispatch_confirmed"],
        dispatch=receipt["dispatch"],
        response_observations=responses,
    )
    save_evidence(site / "evidence.json", checkpoint)
    after_saved = ""
    try:
        await page.wait_for_timeout(1200)
        after = await page.locator("body").inner_text(timeout=10000)
        await page.screenshot(path=str(after_path), full_page=True, timeout=10000)
        after_saved = str(after_path)
        if increment:
            result = classify(before, after, submitted=True)
            markers = [r["receipt_marker"] for r in responses if r.get("receipt_marker") and r["status"] < 400]
            if not result["evidence_code"] and markers:
                result = classify(before, " ".join(markers), submitted=True)
    except Exception:
        error = "Post-submit observation failed; persisted intent/checkpoint; no automatic retry"
    # E2/E3/E4 can be added by the dedicated proof functions, never by generic page.url.
    evidence = dict(
        result,
        run_id=run_id,
        domain=domain,
        submit_url=adapter["submit_url"],
        started_at=started,
        finished_at=now(),
        action="true_submit" if increment else "submit_dispatch_unconfirmed",
        final_url=urlparse(page.url)._replace(query="", fragment="").geturl(),
        listing_url="",
        tracking_url="",
        dom_evidence=result.get("proof", {}).get("dom_evidence", []),
        email_message_id=None,
        screenshot_before=str(before_path),
        screenshot_after=after_saved,
        error=error,
        attempt_increment=increment,
        dispatch_confirmed=receipt["dispatch_confirmed"],
        dispatch=receipt["dispatch"],
        response_observations=responses,
    )
    evidence_path = save_evidence(site / "evidence.json", evidence)
    # Store only observed receipt excerpt, not raw HTML/session/OTP values.
    (site / "dom_excerpt.txt").write_text("\n".join(evidence["dom_evidence"]), encoding="utf-8")
    write_outcome(
        api,
        row,
        backlink_id,
        result,
        reason=prior[8] + "\n" + result["reason"],
        summary=prior[9] + "\n" + f"{result['evidence_code'] or 'NO_EVIDENCE'} | {evidence_path}",
        attempt_increment=increment,
        expected_prior=prior,
        attempt_receipt=intent_path,
    )
    return result
