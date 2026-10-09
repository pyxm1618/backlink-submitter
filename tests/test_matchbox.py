"""Matchbox's observed listing form: real DOM behavior with no external submission."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from playwright.async_api import async_playwright

from backlink_submitter.contracts import load_project

SPEC = {
    "selector": "#founder-request-notes",
    "fields": ["Product / App Name", "Website URL"],
    "separator": "\n",
    "required": True,
}
HANDLER = 'async function j(e){e.preventDefault(),b({kind:"submitting"});try{let e=await fetch("/api/waitlist",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({email:m,interest_type:"founder_listing",notes:h})});if(!e.ok){let t=await e.json().catch(()=>({}));throw Error(t.error??"Something went wrong.")}b({kind:"success"})}catch(e){b({kind:"error",message:(0,x.userErrorMessage)(e)})}}'
BUNDLE = (
    'function y({prefill:e,defaultOpen:a=!1}){let m="",h=e;'
    + HANDLER
    + 'return (0,t.jsxs)("form",{onSubmit:j,children:[(0,t.jsx)(Textarea,{id:"founder-request-notes",required:!0,value:h}),(0,t.jsx)(Input,{id:"founder-request-email",type:"email",required:!0,value:m}),(0,t.jsx)(Button,{type:"submit",children:"Add my product"})]})}'
)
FORM = '<form><label for="founder-request-notes">Product name + website</label><textarea id="founder-request-notes" required></textarea><label for="founder-request-email">Your email</label><input id="founder-request-email" type="email" required><button type="submit">Add my product</button></form>'
HTML = """<p>It's a catalog of small, useful products.</p><p>Listings stay free forever - including claiming and editing your matching data.</p><button type="button">Request a listing →</button><section id="panel"></section><script src="/client.js" type="text/plain"></script><script>
let m="",h="";
HANDLER
function s(open){if(open){document.querySelector('#panel').innerHTML=FORM;let f=document.querySelector('form');f.__reactProps$fixture={onSubmit:j};f.addEventListener('submit',j);}}
let button=document.querySelector('button');const reveal=()=>s(!0);button.__reactProps$fixture={onClick:reveal};button.addEventListener('click',reveal);
</script>""".replace("HANDLER", HANDLER).replace("FORM", json.dumps(FORM))


async def browser_case(tmp_path, *, html=HTML, bundle=BUNDLE, domain="askmatchbox.com", prepare=False, tamper=False):
    from backlink_submitter.batch_worker import prepare_form
    from backlink_submitter.discovery import discover
    from backlink_submitter.workflow import verify_identity

    pack = dict(load_project("wyrplay", Path("projects/wyrplay")), root=tmp_path)
    forwarded = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(service_workers="block")

        async def route(r):
            forwarded.append(r.request.method)
            await r.fulfill(
                content_type="text/javascript" if r.request.url.endswith("/client.js") else "text/html; charset=utf-8",
                body=bundle if r.request.url.endswith("/client.js") else html,
            )

        await ctx.route("**/*", route)

        class Response:
            ok = True
            status = 200
            url = f"https://{domain}/client.js"

            async def text(self):
                return bundle

        async def script_get(self, url, **kwargs):
            assert url == f"https://{domain}/client.js"
            forwarded.append("GET")
            return Response()

        with patch.object(type(ctx.request), "get", script_get):
            page = await ctx.new_page()
            try:
                result = await discover(page, pack, {"domain": domain, "submit_url": f"https://{domain}/founders"})
                path = tmp_path / f"adapters/{domain}.json"
                adapter = json.loads(path.read_text()) if path.exists() else None
                value = None
                if prepare and adapter:
                    await prepare_form(page, adapter, pack)
                    value = await page.locator("#founder-request-notes").input_value()
                    if tamper:
                        await page.locator("#founder-request-notes").fill("WYRPlay\nhttps://other.example/")
                        with pytest.raises(ValueError, match="identity"):
                            await verify_identity(page, adapter, pack)
                # All mutating page requests must be stopped, even after discovery.
                await page.evaluate(
                    "async()=>{for(const method of ['POST','PUT','PATCH','DELETE'])await fetch('/probe',{method}).catch(()=>{});}"
                )
            finally:
                await ctx.close()
                assert browser.contexts == []
                await browser.close()
    assert not list(tmp_path.rglob("submit-intents"))
    return result, adapter, forwarded, value


def test_matchbox_reveal_bound_handler_composed_identity_ready(tmp_path):
    result, adapter, requests, value = asyncio.run(browser_case(tmp_path, prepare=True, tamper=True))
    assert result["outcome"] == "READY_TO_SUBMIT", result
    assert adapter["composed_fields"]["Product name + website"] == SPEC
    assert adapter["fields"] == {"Public Contact Email": "#founder-request-email"}
    assert adapter["final_submit_text"] == "Add my product"
    assert adapter["submission_request"] == {
        "method": "POST",
        "host": "askmatchbox.com",
        "path": "/api/waitlist",
        "verified": True,
    }
    assert adapter["automatic_submit_allowed"] is False
    assert "taxonomy" not in adapter
    assert value == "WYRPlay\nhttps://www.wyrplay.com/"
    assert set(requests) == {"GET"}


@pytest.mark.parametrize(
    "bundle",
    [
        HANDLER,
        BUNDLE.replace("onSubmit:j", "onSubmit:other"),
        BUNDLE.replace("founder_listing", "newsletter"),
        BUNDLE.replace("value:h", "value:other"),
    ],
)
def test_unbound_or_newsletter_bundle_cannot_be_matchbox_adapter(tmp_path, bundle):
    result, adapter, requests, _ = asyncio.run(browser_case(tmp_path, bundle=bundle))
    assert result["outcome"] != "READY_TO_SUBMIT"
    assert adapter is None
    assert set(requests) == {"GET"}


def test_add_my_product_does_not_expand_other_platform_rules(tmp_path):
    result, adapter, _, _ = asyncio.run(browser_case(tmp_path, domain="other.example"))
    assert result["outcome"] != "READY_TO_SUBMIT"
    assert adapter is None


@pytest.mark.parametrize(
    "change",
    [
        {"fields": ["Founder Name", "Website URL"]},
        {"fields": ["Website URL", "Product / App Name"]},
        {"separator": "{description}"},
        {"fields": ["Product / App Name", "Website URL", "Medium Description"]},
    ],
)
def test_composed_fields_reject_free_text_and_non_identity_sources(change):
    from backlink_submitter.contracts import composed_value

    pack = load_project("wyrplay", Path("projects/wyrplay"))
    with pytest.raises(ValueError):
        composed_value(pack, dict(SPEC, **change))


def test_composed_fields_reject_contaminated_pack():
    from backlink_submitter.contracts import composed_value

    pack = load_project("wyrplay", Path("projects/wyrplay"))
    pack = dict(pack, fields=dict(pack["fields"], **{"Product / App Name": "Quick I Ching"}))
    with pytest.raises(ValueError):
        composed_value(pack, SPEC)


def test_composed_adapter_gate_requires_complete_identity():
    from backlink_submitter.batch import adapter_gate

    pack = load_project("wyrplay", Path("projects/wyrplay"))
    adapter = {
        "domain": "askmatchbox.com",
        "required_fields": ["Product name + website"],
        "composed_fields": {"Product name + website": SPEC},
        "fields": {},
        "submission_request": {"method": "POST", "host": "askmatchbox.com", "path": "/api/waitlist", "verified": True},
        "free_verified": True,
        "final_action_verified": True,
        "final_submit_selector": "form button",
        "final_submit_text": "Add my product",
        "qualification": "QUALIFIED_B",
    }
    assert adapter_gate(adapter, pack) is None
    broken = dict(adapter, composed_fields={})
    assert adapter_gate(broken, pack) is not None


@pytest.mark.parametrize(
    "replacement",
    [
        FORM.replace("</form>", '<input name="founder" required></form>'),
        FORM.replace("</form>", '<select name="category" required><option>AI Tool</option></select></form>'),
        FORM.replace("Add my product", "Add"),
        FORM.replace("</form>", '<button type="submit">Add my product</button></form>'),
        '<form><input type="email" required><button type="submit">Add my product</button></form>',
    ],
)
def test_matchbox_requires_exact_listing_shape_and_no_unverified_taxonomy(tmp_path, replacement):
    html = HTML.replace(json.dumps(FORM), json.dumps(replacement))
    result, adapter, requests, _ = asyncio.run(browser_case(tmp_path, html=html))
    assert result["outcome"] != "READY_TO_SUBMIT"
    assert adapter is None
    assert set(requests) == {"GET"}


def test_safe_reveal_blocks_mutating_effects(tmp_path):
    html = HTML.replace(
        "if(open){",
        "if(open){for(const method of ['POST','PUT','PATCH','DELETE'])fetch('/effect',{method}).catch(()=>{});",
    )
    result, adapter, requests, _ = asyncio.run(browser_case(tmp_path, html=html))
    assert result["outcome"] == "READY_TO_SUBMIT"
    assert adapter is not None
    assert set(requests) == {"GET"}


@pytest.mark.parametrize("unbound", [False, True])
def test_reused_adapter_reveals_and_rechecks_actual_handler(tmp_path, unbound):
    from backlink_submitter.batch_worker import inspect_page, prepare_form

    _, adapter, _, _ = asyncio.run(browser_case(tmp_path))

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            ctx = await browser.new_context(service_workers="block")

            async def route(r):
                assert r.request.method == "GET"
                await r.fulfill(content_type="text/html; charset=utf-8", body=HTML)

            await ctx.route("**/*", route)
            page = await ctx.new_page()

            class Response:
                ok = True
                status = 200
                url = "https://askmatchbox.com/client.js"

                async def text(self):
                    return HANDLER if unbound else BUNDLE

            async def get(self, url, **kwargs):
                assert url == "https://askmatchbox.com/client.js"
                return Response()

            try:
                with patch.object(type(ctx.request), "get", get):
                    await page.goto("https://askmatchbox.com/founders")
                    pack = load_project("wyrplay", Path("projects/wyrplay"))
                    result = await inspect_page(page, adapter, pack)
                    if unbound:
                        assert result is not None and result["reason"] == "DISPATCH_MATCHER_UNVERIFIED"
                    else:
                        assert result is None
                        await prepare_form(page, adapter, pack)
                        assert (
                            await page.locator("#founder-request-notes").input_value()
                            == "WYRPlay\nhttps://www.wyrplay.com/"
                        )
            finally:
                await ctx.close()
                assert browser.contexts == []
                await browser.close()

    asyncio.run(run())


def test_matchbox_rejects_additional_write_code_in_bound_handler():
    from backlink_submitter.matchbox import bound_handler

    changed = HANDLER.replace("e.preventDefault(),", 'e.preventDefault(),navigator.sendBeacon("/other", "unexpected"),')
    assert not bound_handler(BUNDLE.replace(HANDLER, changed), changed)
