"""Bounded adapter flow. No real adapter currently permits final Submit; no batch runner."""

import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

from .contracts import (
    CONTACT,
    PROJECT,
    TARGET,
    classify,
    field_value,
    now,
    save_evidence,
    submit_once,
    validate_payload,
)
from .sheets import full_row, is_blacklisted, write_outcome


async def human_boundary(page):
    text = (await page.locator("body").inner_text(timeout=10000)).casefold()
    markers = [
        "verify you are human",
        "checking your browser",
        "verification required",
        "unusual traffic",
        "two-step verification",
        "verify it’s you",
        "enter your password",
        "confirm your device",
    ]
    challenge = await page.locator('iframe[src*="challenges.cloudflare.com"],iframe[src*="recaptcha"]').count()
    if challenge or any(marker in text for marker in markers) or await page.locator('input[type="password"]').count():
        raise ValueError("HUMAN_VERIFICATION_REQUIRED: no bypass/retry")


async def fill_fields(page, adapter, pack):
    await human_boundary(page)
    for field, selector in adapter["fields"].items():
        value = field_value(
            pack, field, required=field in adapter.get("required_fields", []), platform=adapter["domain"]
        )
        if isinstance(value, dict):
            raise ValueError("OWNER_INPUT_REQUIRED: " + field)
        if value:
            control = page.locator(selector)
            if await control.evaluate("(e)=>e.tagName") == "SELECT":
                await control.select_option(label=value, timeout=10000)
            else:
                await control.fill(value, timeout=10000)
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
    if host.removeprefix("www.") != domain.removeprefix("www."):
        raise ValueError("Page is not the official adapter domain")
    intent_path = Path(runtime) / "submit-intents" / PROJECT / (backlink_id + ".json")
    if intent_path.exists():
        raise ValueError("Existing intent; no automatic duplicate")
    await human_boundary(page)
    if blacklisted or is_blacklisted(api, backlink_id, domain):
        raise ValueError("Blacklisted platform; no Submit")
    prior = full_row(api, row)
    if prior[:2] != [PROJECT, backlink_id]:
        raise ValueError("Joint key mismatch before any Submit")
    required_unknown = await page.locator("input[required],select[required],textarea[required]").evaluate_all(
        "nodes=>nodes.filter(e=>e.type==='checkbox'?!e.checked:e.type==='file'?!e.files.length:!e.value.trim()).map(e=>e.name||e.id||'unidentified mandatory field')"
    )
    values = await page.locator("input:not([type=password]),textarea,select").evaluate_all(
        "nodes=>nodes.map(e=>({name:e.name||e.id,value:e.type==='file'?[...e.files].map(f=>f.name):e.value}))"
    )
    validate_payload(values)  # inspect real form, not only the selected pack fields
    for field, selector in adapter["fields"].items():
        if field in {"Product / App Name", "Website URL", "Public Contact Email"}:
            if await page.locator(selector).input_value(timeout=10000) != pack["fields"][field]:
                raise ValueError("Actual DOM identity mismatch")
    if not all(k in adapter["fields"] for k in ["Product / App Name", "Website URL"]):
        raise ValueError("Required identity mapping missing")
    # Selectors and taxonomy have to be qualified before this point; never infer an AI category.
    categories = [v["value"] for v in values if re.search(r"category|tags|product_type", v["name"], re.I)]
    if re.search(r"\b(?:AI Tool|AI Generator|LLM|GPT)\b", str(categories), re.I):
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
        )
    except ValueError:
        raise  # gate refusal: no submission result exists
    except Exception:
        error = "Submit action response unconfirmed; inspect intent; no automatic retry"
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
    )
    save_evidence(site / "evidence.json", checkpoint)
    after_saved = ""
    try:
        after = await page.locator("body").inner_text(timeout=10000)
        await page.screenshot(path=str(after_path), full_page=True, timeout=10000)
        after_saved = str(after_path)
        if increment:
            result = classify(before, after, submitted=True)
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
    )
    evidence_path = save_evidence(site / "evidence.json", evidence)
    # Store only observed receipt excerpt, not raw HTML/session/OTP values.
    (site / "dom_excerpt.txt").write_text("\n".join(evidence["dom_evidence"]), encoding="utf-8")
    write_outcome(
        api,
        row,
        backlink_id,
        result,
        reason=result["reason"],
        summary=f"{result['evidence_code'] or 'NO_EVIDENCE'} | {evidence_path}",
        attempt_increment=increment,
        expected_prior=prior,
        attempt_receipt=intent_path,
    )
    return result
