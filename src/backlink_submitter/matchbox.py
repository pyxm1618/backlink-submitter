"""Only Matchbox's observed founder_listing form, not a general SPA discovery rule."""

import hashlib
import re

from playwright.async_api import Error as BrowserError

from .batch import adapter_gate, official_url
from .contracts import composed_value, now
from .workflow import human_boundary

DOMAIN = "askmatchbox.com"
SOURCE = "https://askmatchbox.com/founders"
NOTES = "#founder-request-notes"
EMAIL = "#founder-request-email"
FINAL = 'form:has(#founder-request-notes):has(#founder-request-email) button[type="submit"]'
# Pin only the audited function, not the whole bundle. Handler changes require review.
VERIFIED_HANDLER_SHA256 = "955ba6c35e730e967a6a907032b0343cc0c23b0353e8e10bd09c48e0a2e5a25e"
FREE = "Listings stay free forever - including claiming and editing your matching data."


def block_end(text, start):
    """Find the end of one observed JS brace block; never evaluate downloaded JS."""
    depth = 0
    quote = None
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {'"', "'", "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


async def reveal_listing(page, adapter=None):
    from .discovery import readonly_route

    if page.url != SOURCE or adapter and adapter.get("domain") != DOMAIN:
        raise ValueError("FORM_OR_SELECTOR_CHANGED")
    if await page.locator(NOTES).count() == 1:
        return
    # This route is present even for a later LIVE preparation; remove only our own
    # guard afterwards. The enclosing discovery/dry-run guard remains installed.
    await page.route("**/*", readonly_route)
    try:
        button = page.get_by_role("button", name="Request a listing →", exact=True)
        await button.wait_for(state="visible", timeout=10000)
        if await button.count() != 1 or await button.get_attribute("type") != "button":
            raise ValueError("FORM_OR_SELECTOR_CHANGED")
        await page.wait_for_function(
            """()=>{const es=[...document.querySelectorAll('button')].filter(e=>e.innerText.trim()==='Request a listing →');
            if(es.length!==1)return false;const e=es[0],k=Object.keys(e).find(k=>k.startsWith('__reactProps'));
            return k&&typeof e[k]?.onClick==='function';}""",
            timeout=10000,
        )
        handler = await button.evaluate("e=>e[Object.keys(e).find(k=>k.startsWith('__reactProps'))].onClick.toString()")
        if not re.fullmatch(r"\(\)=>[a-zA-Z_$][\w$]*\(!0\)", handler):
            raise ValueError("FORM_OR_SELECTOR_CHANGED")
        await button.click(timeout=10000)
        await page.locator(NOTES).wait_for(state="visible", timeout=10000)
        await human_boundary(page)
    finally:
        await page.unroute("**/*", readonly_route)


def bound_handler(script, handler):
    """Require the live form handler AND its same-component React render binding."""
    if hashlib.sha256(handler.encode()).hexdigest() != VERIFIED_HANDLER_SHA256:
        return False
    signature = re.match(r"async function ([\w$]+)\(([\w$]+)\)\{", handler)
    if not signature or script.count(handler) != 1 or handler.count("fetch(") != 1:
        return False
    if not handler.startswith(signature[0] + signature[2] + ".preventDefault()"):
        return False
    request = re.search(
        r'fetch\("/api/waitlist",\{method:"POST",headers:\{"content-type":"application/json"\},'
        r'body:JSON.stringify\(\{email:([\w$]+),interest_type:"founder_listing",notes:([\w$]+)\}\)\}\)',
        handler,
    )
    if not request:
        return False
    components = []
    for match in re.finditer(r"function [\w$]+\(\{prefill:[\w$]+,defaultOpen:[\w$]+=!1\}\)\{", script):
        end = block_end(script, match.end() - 1)
        if end:
            components.append(script[match.start() : end])
    matched = []
    for component in components:
        if component.count(handler) != 1:
            continue
        forms = list(re.finditer(r'"form",\{onSubmit:' + re.escape(signature[1]) + r",", component))
        if len(forms) != 1:
            continue
        end = block_end(component, forms[0].start() + len('"form",'))
        if not end:
            continue
        form = component[forms[0].start() : end]
        notes = 'id:"founder-request-notes",required:!0,value:' + request[2]
        email = 'id:"founder-request-email",type:"email",required:!0,value:' + request[1]
        if notes in form and email in form and 'type:"submit"' in form and '"Add my product"' in form:
            matched.append(component)
    return len(matched) == 1


async def handler_evidence(page, form):
    handler = await form.evaluate(
        """e=>{const k=Object.keys(e).find(k=>k.startsWith('__reactProps'));
        return k&&typeof e[k]?.onSubmit==='function'?e[k].onSubmit.toString():null;}"""
    )
    if not handler:
        return None
    sources = await page.locator("script[src]").evaluate_all("es=>es.map(e=>e.src)")
    for source in dict.fromkeys(sources):
        if not official_url(source, DOMAIN):
            continue
        response = await page.request.get(source, timeout=8000, max_redirects=0)
        if not response.ok or not official_url(response.url, DOMAIN):
            continue
        script = await response.text()
        if len(script) > 2_000_000 or not bound_handler(script, handler):
            continue
        return {
            "kind": "matchbox_bound_react_listing_handler",
            "source_url": source,
            "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
            "handler_sha256": hashlib.sha256(handler.encode()).hexdigest(),
            "form_selectors": [NOTES, EMAIL],
            "react_binding": "form.onSubmit -> observed live handler -> fetch",
            "request_discriminator": {"interest_type": "founder_listing"},
            "method": "POST",
            "host": DOMAIN,
            "path": "/api/waitlist",
        }
    return None


async def verified_listing_form(page):
    form = page.locator("form:has(#founder-request-notes):has(#founder-request-email)")
    if await form.count() != 1:
        return None, None
    actual = await form.locator("input,textarea,select").evaluate_all(
        "es=>es.map(e=>({id:e.id,type:e.type,required:e.required,labels:[...e.labels||[]].map(l=>l.innerText.trim())}))"
    )
    expected = [
        {"id": "founder-request-notes", "type": "textarea", "required": True, "labels": ["Product name + website"]},
        {"id": "founder-request-email", "type": "email", "required": True, "labels": ["Your email"]},
    ]
    final = page.locator(FINAL)
    if (
        actual != expected
        or await final.count() != 1
        or not await final.is_visible()
        or not await final.is_enabled()
        or (await final.inner_text()).strip() != "Add my product"
    ):
        return None, None
    return form, actual


async def inspect_matchbox(page, adapter):
    from .discovery import review

    await reveal_listing(page, adapter)
    text = await page.locator("body").inner_text()
    form, _ = await verified_listing_form(page)
    if form is None or FREE not in text or "catalog of small, useful products" not in text:
        return review("MATCHBOX_REQUIRED_FORM_CHANGED")
    proof = await handler_evidence(page, form)
    if not proof or adapter.get("submission_request") != {
        "method": "POST",
        "host": DOMAIN,
        "path": "/api/waitlist",
        "verified": True,
    }:
        return review("DISPATCH_MATCHER_UNVERIFIED")
    return None


async def discover_matchbox(page, pack, job):
    from .batch_worker import prepare_form, readonly_ready
    from .discovery import navigate, persist_adapter, review

    visited = []
    try:
        url = job.get("submit_url") or "https://askmatchbox.com/"
        visited.append(url)
        failure = await navigate(page, url, DOMAIN)
        if failure:
            return dict(failure, discovery_visited=visited)
        if page.url != SOURCE:
            link = page.get_by_role("link", name="List a product →", exact=True)
            await link.wait_for(state="visible", timeout=10000)
            if await link.count() != 1 or await link.get_attribute("href") != "/founders":
                return dict(review("OFFICIAL_SUBMIT_URL_UNCONFIRMED"), discovery_visited=visited)
            visited.append(SOURCE)
            failure = await navigate(page, SOURCE, DOMAIN)
            if failure:
                return dict(failure, discovery_visited=visited)
        await reveal_listing(page)
        text = await page.locator("body").inner_text()
        if FREE not in text or "catalog of small, useful products" not in text:
            return dict(review("QUALIFICATION_FREE_OR_LOGIN_UNVERIFIED"), discovery_visited=visited)
        form, actual = await verified_listing_form(page)
        if form is None:
            return dict(review("MATCHBOX_REQUIRED_FORM_CHANGED"), discovery_visited=visited)
        proof = await handler_evidence(page, form)
        if not proof:
            return dict(review("DISPATCH_MATCHER_UNVERIFIED"), discovery_visited=visited)
        spec = {"selector": NOTES, "fields": ["Product / App Name", "Website URL"], "separator": "\n", "required": True}
        composed_value(pack, spec)
        adapter = {
            "domain": DOMAIN,
            "submit_url": SOURCE,
            "automatic_submit_allowed": False,
            "reveal_action": {"button_text": "Request a listing →", "type": "button", "readonly_required": True},
            "fields": {"Public Contact Email": EMAIL},
            "composed_fields": {"Product name + website": spec},
            "required_fields": ["Product name + website", "Public Contact Email"],
            "final_submit_selector": FINAL,
            "final_submit_text": "Add my product",
            "final_action_verified": True,
            "free_verified": True,
            "login_required": False,
            "reciprocal_required": False,
            "qualification": "QUALIFIED_B",
            "submission_request": {"method": "POST", "host": DOMAIN, "path": "/api/waitlist", "verified": True},
            "provenance": {
                "verified_at": now(),
                "official_source": SOURCE,
                "free_evidence": FREE,
                "suitability_evidence": "catalog of small, useful products",
                "field_evidence": actual,
                "dispatch_evidence": proof,
                "final_action_evidence": {"selector": FINAL, "text": "Add my product", "unique_count": 1},
            },
        }
        gate = adapter_gate(adapter, pack)
        if gate:
            return dict(gate, discovery_visited=visited)
        await prepare_form(page, adapter, pack)
        ready = await readonly_ready(page, adapter)
        if ready["outcome"] != "READY_TO_SUBMIT":
            return dict(ready, discovery_visited=visited)
        path = persist_adapter(pack, DOMAIN, adapter)
        if not path:
            return dict(review("ADAPTER_REVIEW_REQUIRED"), discovery_visited=visited)
        return dict(
            ready,
            reason="MATCHBOX_DISCOVERY_ADAPTER_VERIFIED",
            generated_adapter=str(path),
            submit_url=SOURCE,
            discovery_visited=visited,
        )
    except BrowserError:
        return dict(review("MATCHBOX_FORM_OR_HANDLER_UNAVAILABLE"), discovery_visited=visited)
    except ValueError as exc:
        if str(exc).startswith("HUMAN_VERIFICATION_REQUIRED"):
            return {
                "outcome": "HUMAN_VERIFICATION_REQUIRED",
                "reason": "HUMAN_VERIFICATION_REQUIRED",
                "discovery_visited": visited,
            }
        if str(exc) == "FORM_OR_SELECTOR_CHANGED":
            return dict(review("FORM_OR_SELECTOR_CHANGED"), discovery_visited=visited)
        raise
