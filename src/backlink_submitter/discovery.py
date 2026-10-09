"""Discover observed official pages and continue authorized LIVE in the same context."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import Error as BrowserError

from .automation import AuthGuard, advance_local_step, automatic_authentication, owner_boundary
from .batch import adapter_gate, official_url
from .contracts import field_value, now, safe_artifact

ENTRY = re.compile(
    r"\b(submit|add (?:a |your )?(?:product|startup|tool|website)|list your product|launch|contribute|guest post|write for us|publish|community|directory|sign in|log in|login|register)\b|提交|收录|投稿|发布|登录",
    re.I,
)
FINAL = re.compile(r"^(?:submit|add|list|publish)(?: (?:your |a )?(?:product|startup|tool|website|listing))?$", re.I)

# These are exact positive policy statements, not absence-of-evidence heuristics.
POLICIES = [
    ("we only accept ai tools", "NOT_APPLICABLE", "AI_ONLY"),
    ("only ai tools are accepted", "NOT_APPLICABLE", "AI_ONLY"),
    ("all submissions require payment. no free submissions", "GLOBAL_BLACKLIST", "PAYMENT_ONLY"),
    ("this service has permanently closed", "GLOBAL_BLACKLIST", "PERMANENTLY_UNAVAILABLE"),
    ("we are a private blog network selling backlinks", "GLOBAL_BLACKLIST", "PBN"),
]


def review(reason, **metadata):
    return {"outcome": "需人工核查", "reason": reason, **metadata}


async def readonly_route(route):
    if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
        await route.abort()
    else:
        await route.fallback()


async def navigate(page, url, domain):
    if not official_url(url, domain):
        return review("OFFICIAL_SUBMIT_URL_UNCONFIRMED")
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(800)
        boundary = await owner_boundary(page)
        if boundary and boundary["reason"] != "OWNER_PASSWORD_REQUIRED":
            return dict(
                boundary, owner_action_proof={"kind": "visible_verification_challenge", "reason": boundary["reason"]}
            )
    except ValueError:
        return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_VERIFICATION_REQUIRED"}
    except BrowserError:
        return {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "OFFICIAL_PAGE_UNAVAILABLE"}
    if not official_url(page.url, domain):
        return {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "AUTH_REDIRECT_UNCONFIRMED", "automation_pending": True}
    if not response or response.status >= 400:
        return {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "HTTP_UNAVAILABLE_NOT_PERMANENT_PROOF"}
    return None


async def qualify(page, domain):
    text = (await page.locator("body").inner_text(timeout=10000)).casefold()
    for marker, outcome, reason in POLICIES:
        if re.search(r"(?:^|[.!?\n]\s*)" + re.escape(marker) + r"(?:[.!?\n]|$)", text):
            return {"outcome": outcome, "reason": reason, "source_url": page.url, "marker": marker, "checked_at": now()}
    if "需要登录才能访问" in text or re.search(
        r"(?:sign in|log in|login|create an account) (?:to|required to) (?:submit|add|list|launch)", text
    ):
        return review("AUTH_CONTINUATION_REQUIRED", automation_pending=True)
    title = (await page.title()).casefold()
    if "astrology, tarot, bazi" in title and "directory" in title:
        return {
            "outcome": "NOT_APPLICABLE",
            "reason": "PROJECT_CATEGORY_MISMATCH",
            "source_url": page.url,
            "marker": await page.title(),
            "checked_at": now(),
        }
    return None


async def controls(page, form):
    # Only stable, unique attributes observed in the current DOM; never nth()/position.
    return await form.locator("input,select,textarea").evaluate_all("""es=>es.map(e=>({
      tag:e.tagName, type:e.type, required:e.required, disabled:e.disabled,
      observed_index:(()=>{const i=[...document.querySelectorAll("input,select,textarea")].indexOf(e);e.setAttribute("data-backlink-control",String(i));return i})(),
      id:e.id, name:e.name, model:e.getAttribute('wire:model')||'', placeholder:e.getAttribute('placeholder')||'',
      aria:e.getAttribute('aria-label')||'', labels:[...e.labels||[]].length?[...e.labels].map(l=>l.innerText.trim()):[e.parentElement?.tagName!=="FORM"?e.parentElement?.querySelector("label")?.innerText.trim()||"":""].filter(Boolean),
      accept:e.accept||'', multiple:!!e.multiple, maxLength:e.maxLength,
      legend:e.closest('fieldset')?.querySelector('legend')?.innerText.trim()||'',
      options:e.tagName==='SELECT'?[...e.options].map(o=>({text:o.text.trim(),value:o.value,disabled:o.disabled})):[]
    }))""")


async def selector_for(page, control):
    for attribute, value in [
        ("id", control["id"]),
        ("name", control["name"]),
        ("wire\\:model", control.get("model", "")),
        ("placeholder", control["placeholder"]),
        ("aria-label", control["aria"]),
    ]:
        if value and len(value) < 150 and re.fullmatch(r"[\w .:/?()-]+", value):
            selector = "[" + attribute + "=" + json.dumps(value) + "]"
            if await page.locator(selector).count() == 1:
                return selector
    if type(control.get("observed_index")) is int:
        selector = '[data-backlink-control="' + str(control["observed_index"]) + '"]'
        if await page.locator(selector).count() == 1:
            return selector
    return None


def semantic_field(control):
    terms = [
        re.sub(r"[\s*：:]+$", "", t.casefold().strip())
        for t in [
            *control["labels"],
            control["aria"],
            control["placeholder"],
            control["name"],
            control.get("id", ""),
            control.get("model", ""),
        ]
    ]
    names = {
        "Product / App Name": {
            "project name",
            "software name",
            "product / software name",
            "site name",
            "product name",
            "startup name",
            "app name",
            "tool name",
            "product_name",
            "startup_name",
            "product",
            "产品名称",
            "网站名称",
        },
        "Website URL": {
            "website",
            "website url",
            "product url",
            "url",
            "website_url",
            "website link",
            "site url",
            "官网",
            "网站",
            "网址",
        },
        "Public Contact Email": {
            "e-mail address",
            "your email",
            "contact email",
            "email",
            "email address",
            "e-mail",
            "your email",
            "邮箱",
            "电子邮箱",
        },
        "One-line Pitch / Tagline": {"tagline", "one line pitch", "one-line pitch"},
        "Short Description": {"short description"},
        "Operator / Legal Owner": {"your name", "contact name"},
        "Jurisdiction / Country": {"country", "country (optional)"},
        "Medium Description": {"description", "product description", "startup description"},
    }
    names.update(
        {
            "Funding": {"funding", "funding stage"},
            "Founder structure": {"founder structure", "founders"},
            "Founder Name": {"founder", "founder name"},
            "Phone": {"phone", "phone number"},
            "Founded Date": {"founded date", "founding date"},
        }
    )
    matches = {field for field, aliases in names.items() if any(term.casefold().strip() in aliases for term in terms)}
    return next(iter(matches)) if len(matches) == 1 else None


async def dispatch_matcher(page, form, final, domain):
    from .handler_proof import bound_submit_handlers, matcher_from_handler

    handlers = await bound_submit_handlers(page, form)
    clicks = await final.evaluate(
        "e=>{let h=[];for(let n=e;n;n=n.parentElement){for(const k of Object.keys(n)){if(k.startsWith('__reactProps$')&&n[k].onClick)h.push(Function.prototype.toString.call(n[k].onClick))}}return h}"
    )
    if clicks:
        if len(clicks) == 1:
            proof = matcher_from_handler(clicks[0], page.url, domain)
            if proof:
                return proof
        return None, None
    if handlers is None:
        return None, None
    if len(handlers) == 1:
        proof = matcher_from_handler(handlers[0], page.url, domain)
        if proof:
            return proof
    method = (await form.get_attribute("method") or "").upper()
    action = await form.get_attribute("action")
    if (
        await form.get_attribute("onsubmit")
        or await final.get_attribute("onclick")
        or await final.get_attribute("formaction")
        or await final.get_attribute("formmethod")
    ):
        return None, None
    scripts = await page.locator("script:not([src])").all_text_contents()
    sources = [(page.url, script) for script in scripts]
    # Read only small, observed official scripts; do not invent bundle URLs.
    for url in (await page.locator("script[src]").evaluate_all("es=>es.map(e=>e.src)"))[:3]:
        if not official_url(url, domain):
            continue
        try:
            response = await page.request.get(url, timeout=8000, max_redirects=0)
            if response.ok and official_url(response.url, domain):
                content = await response.text()
                if len(content) <= 500_000:
                    sources.append((url, content))
        except BrowserError:
            continue  # An unavailable script is unverified, never a matcher fallback.
    if len(sources) != len(scripts) + await page.locator("script[src]").count() and handlers:
        return None, None
    form_id = await form.get_attribute("id")
    if form_id and (
        not re.fullmatch(r"[a-zA-Z0-9_-]+", form_id)
        or await page.locator("[id=" + json.dumps(form_id) + "]").count() != 1
    ):
        return None, None
    # Deliberately narrow grammar: an observed form's submit listener, preventDefault,
    # exactly one literal fetch endpoint/method. Complex/minified handlers require review.
    bindings = []
    for source, script in sources:
        if not form_id:
            continue
        pattern = (
            r"document\.querySelector\(['\"]#"
            + re.escape(form_id)
            + r"['\"]\)\.addEventListener\(['\"]submit['\"],\s*(?:async\s*)?\((\w+)\)\s*=>\s*\{\s*"
            + r"\1\.preventDefault\(\);\s*(?:await\s+)?fetch\(['\"]([^'\"]+)['\"],\s*"
            + r"\{\s*method:\s*['\"](POST|PUT|PATCH)['\"]\s*\}\);\s*\}\);"
        )
        matched = re.fullmatch(pattern, script.strip(), re.S)
        if matched:
            url = urljoin(page.url, matched[2])
            if not official_url(url, domain):
                return None, None
            bindings.append(
                (
                    matched[3],
                    url,
                    {
                        "kind": "official_submit_listener",
                        "source_url": source,
                        "script_sha256": hashlib.sha256(script.encode()).hexdigest(),
                        "form_id": form_id,
                    },
                )
            )
    if len(bindings) == 1 and len([s for _, s in sources if s.strip()]) == 1:
        method, url, evidence = bindings[0]
    elif bindings:
        return None, None
    else:
        # Any script or inline event handler that could override a native form makes
        # the native matcher uncertain. Never claim native proof for a hydrated SPA.
        if (
            handlers
            or await form.get_attribute("onsubmit")
            or await final.get_attribute("onclick")
            or await final.get_attribute("formaction")
            or await final.get_attribute("formmethod")
        ):
            return None, None
        if method != "POST" or not action or not official_url(urljoin(page.url, action), domain):
            return None, None
        url = urljoin(page.url, action)
        evidence = {
            "kind": "native_form",
            "source_url": page.url,
            "method_attribute": method,
            "action_attribute": action,
        }
    parsed = urlparse(url)
    return {"method": method, "host": parsed.hostname, "path": parsed.path or "/", "verified": True}, evidence


async def build_adapter(page, pack, domain, *, first_submit=False):
    forms = page.locator("form").filter(has=page.locator('button[type="submit"],input[type="submit"]'))
    candidates = []
    for candidate in await forms.all():
        if await candidate.is_visible() and any(
            semantic_field(c) in {"Product / App Name", "Website URL"} for c in await controls(page, candidate)
        ):
            candidates.append(candidate)
    if len(candidates) != 1:
        return review("ADAPTER_REVIEW_REQUIRED"), None
    form = candidates[0]
    final = form.locator('button[type="submit"],input[type="submit"]')
    if await final.count() != 1 or not await final.is_visible() or not await final.is_enabled():
        return review("ADAPTER_REVIEW_REQUIRED"), None
    # Existing final-action engine reads inner_text; input[value] finals need review.
    text = ((await final.inner_text()) or (await final.get_attribute("value")) or "").strip()
    if not FINAL.fullmatch(text):
        return review("FINAL_ACTION_UNVERIFIED"), None
    final_control = {
        "id": await final.get_attribute("id") or "",
        "name": await final.get_attribute("name") or "",
        "placeholder": "",
        "aria": await final.get_attribute("aria-label") or "",
    }
    final_selector = await selector_for(page, final_control)
    if not final_selector:
        observed_selector = "button:text-is(" + json.dumps(text) + ")"
        if await page.locator(observed_selector).count() == 1:
            final_selector = observed_selector
        else:
            return review("FINAL_SELECTOR_UNVERIFIED"), None
    adapter = {
        "domain": domain,
        "submit_url": page.url,
        "automatic_submit_allowed": False,
        "fields": {},
        "required_fields": [],
        "final_submit_selector": final_selector,
        "final_submit_text": text,
        "final_action_verified": True,
        "reciprocal_required": False,
    }
    evidence = []
    for control in await controls(page, form):
        if control["disabled"] or control["type"] in {"hidden", "submit", "button"}:
            continue
        selector = await selector_for(page, control)
        semantic = " ".join([*control["labels"], control["name"], control["placeholder"], control["aria"]]).casefold()
        field = semantic_field(control)
        if control["tag"] == "SELECT" and any(
            t.casefold() in {"category", "categories", "taxonomy"}
            for t in [*control["labels"], control["name"], control["aria"]]
        ):
            options = [
                o
                for o in control["options"]
                if not o["disabled"]
                and o["text"] in {"Games", "Gaming", "Entertainment", "Party Games", "Social Games", "Web Application"}
            ]
            if not selector or not options or adapter.get("taxonomy"):
                return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "TAXONOMY_UNCONFIRMED"}, None
            option = options[0]
            adapter["taxonomy"] = {
                "category": option["text"],
                "native_select": True,
                "control_selector": selector,
                "option_text": option["text"],
                "option_value": option["value"],
                "option_verified": True,
                "selected_verified": await page.locator(selector).input_value() == option["value"],
            }
            adapter["required_fields"].append("Category")
        elif control["type"] == "file":
            accept = control["accept"].casefold()
            png_allowed = not accept or any(t in accept for t in ["image/*", "image/png", ".png"])
            svg_allowed = not accept or any(t in accept for t in ["image/*", "image/svg+xml", ".svg"])
            if not selector:
                return review("UPLOAD_CONTROL_UNRESOLVED"), None
            if "logo" in semantic and not adapter.get("logo_selector"):
                format_name = "png" if png_allowed else "svg" if svg_allowed else None
                if not format_name:
                    return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "OFFICIAL_ASSET_FORMAT_UNSUPPORTED"}, None
                size_match = re.search(r"max(?:imum)?\s*(\d+)\s*kb", semantic, re.I)
                if size_match and pack["logo_" + format_name].stat().st_size > int(size_match[1]) * 1024:
                    if svg_allowed and pack["logo_svg"].stat().st_size <= int(size_match[1]) * 1024:
                        format_name = "svg"
                    else:
                        return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "OFFICIAL_ASSET_SIZE_UNSUPPORTED"}, None
                adapter.update(logo_selector=selector, logo_format=format_name, logo_required=control["required"])
            elif re.search(r"screenshot|product image|preview image", semantic) and png_allowed:
                if control["multiple"]:
                    adapter.update(screenshots_selector=selector, screenshot_limit=5)
                else:
                    adapter.update(
                        image_selector=selector, image_asset=str(pack["screenshots"][0].relative_to(pack["root"]))
                    )
            elif control["required"]:
                return {
                    "outcome": "OWNER_INPUT_REQUIRED",
                    "reason": "OFFICIAL_ASSET_REQUIRED",
                    "missing_fields": control["labels"],
                }, None
            else:
                continue
        elif field and selector and control["type"] not in {"checkbox", "radio", "password"}:
            value = field_value(pack, field, required=control["required"], platform=domain)
            if isinstance(value, dict):
                return {
                    "outcome": "OWNER_INPUT_REQUIRED",
                    "reason": "OWNER_FACT_REQUIRED",
                    "missing_fields": [field],
                }, None
            if (
                control["maxLength"] > 0
                and len(value) > control["maxLength"]
                or field in adapter["fields"]
                or not await page.locator(selector).evaluate(
                    "(e,v)=>{const c=e.cloneNode(true); c.value=v; return c.checkValidity();}", value
                )
            ):
                return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "REQUIRED_FACT_OR_CONSTRAINT_UNCONFIRMED"}, None
            adapter["fields"][field] = selector
            if control["required"]:
                adapter["required_fields"].append(field)
        elif control["required"] or control["type"] in {"checkbox", "radio"}:
            if (
                control["type"] == "checkbox"
                and selector
                and re.search(r"terms|privacy|服务条款|隐私", semantic)
                and not re.search(
                    r"authoriz|certif|exclusive|licen[cs]e|payment|charge|marketing|授权|独家|收费", semantic
                )
            ):
                adapter.setdefault("ordinary_checkboxes", []).append(selector)
                continue
            if (
                control["type"] == "checkbox"
                and control["required"]
                and re.search(r"terms|privacy|consent|authoriz|服务条款|隐私|授权", semantic)
            ):
                return {
                    "outcome": "OWNER_INPUT_REQUIRED",
                    "reason": "OWNER_AUTHORIZATION_REQUIRED",
                    "missing_fields": control["labels"] or [control["name"]],
                }, None
            label = next(
                (
                    t.strip()
                    for t in [
                        *control["labels"],
                        control["aria"],
                        control["placeholder"],
                        control["name"],
                        control["id"],
                    ]
                    if t.strip()
                ),
                "未标注的必填控件（需人工查看）",
            )
            return {
                "outcome": "OWNER_INPUT_REQUIRED",
                "reason": "UNMAPPED_REQUIRED_FIELDS",
                "missing_fields": [label],
            }, None
        else:
            continue
        evidence.append(
            {
                "selector": selector,
                "labels": control["labels"],
                "name": control["name"],
                "placeholder": control["placeholder"],
                "aria": control["aria"],
                "required": control["required"],
                "options": control["options"],
                "accept": control["accept"],
            }
        )
    if not all(k in adapter["fields"] for k in ["Product / App Name", "Website URL"]):
        return review("FIELD_OR_TAXONOMY_UNVERIFIED"), None
    body = (await page.locator("body").inner_text()).casefold()
    free = next(
        (
            s
            for s in [
                "submit your product for free",
                "free submissions",
                "list your product for free",
                "submit for free",
                "free listing",
                "免费收录",
                "免费提交",
            ]
            if s in body
        ),
        None,
    )
    suitability = next(
        (
            s
            for s in [
                "we accept games",
                "games and web applications",
                "all web applications are welcome",
                "websites of all categories",
                "all types of websites",
            ]
            if s in body
        ),
        None,
    )
    login = next(
        (s for s in ["no account required", "no login required", "submit without signing up"] if s in body), None
    )
    if (
        (not free and not first_submit)
        or (not suitability and not first_submit)
        or re.search(r"(?:badge|reciprocal|backlink).{0,30}(?:required|mandatory)", body)
        or "no free submissions" in body
    ):
        return review("QUALIFICATION_FREE_OR_LOGIN_UNVERIFIED"), None
    if adapter.get("logo_selector") and not first_submit:
        return review("UPLOAD_SIZE_CONSTRAINT_REVIEW_REQUIRED"), None
    if first_submit:
        matcher, dispatch = None, {"kind": "observe_first_real_submit"}
    else:
        matcher, dispatch = await dispatch_matcher(page, form, final, domain)
    if not matcher and not first_submit:
        return review("DISPATCH_MATCHER_UNVERIFIED"), None
    if (
        first_submit
        and not free
        and re.search(r"(?:payment required|no free submissions|paid listing only|checkout to submit)", body, re.I)
    ):
        return review("FREE_PATH_REQUIRES_PAGE_REVIEW"), None
    adapter.update(free_verified=True, login_required=False, qualification="QUALIFIED_B")
    if matcher:
        adapter["submission_request"] = matcher
    adapter["provenance"] = {
        "verified_at": now(),
        "official_source": page.url,
        "field_evidence": evidence,
        "final_action_evidence": {"selector": final_selector, "text": text, "unique_count": 1},
        "dispatch_evidence": dispatch,
        "free_evidence": free,
        "suitability_evidence": suitability,
        "login_evidence": login or "Current listing form accessible in this platform session",
    }
    from .batch_worker import readonly_ready

    gate = adapter_gate(adapter, pack)
    if not gate:
        readiness = await readonly_ready(page, adapter)
        gate = readiness if readiness["outcome"] != "READY_TO_SUBMIT" else None
    return (gate, None) if gate else ({"outcome": "READY_TO_SUBMIT", "reason": "DISCOVERY_ADAPTER_VERIFIED"}, adapter)


def persist_adapter(pack, domain, adapter):
    safe_artifact(adapter)
    path = Path(pack["root"]) / "adapters" / (domain + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".discovery")
    try:
        with staged.open("x") as stream:
            stream.write(json.dumps(adapter, ensure_ascii=False, indent=2) + "\n")
        try:
            import os

            os.link(staged, path)
        finally:
            staged.unlink()
    except FileExistsError:
        return None
    return path


async def discover(page, pack, job, *, connector=None, on_ready=None):
    domain = job["domain"]

    if domain == "askmatchbox.com":
        from .matchbox import discover_matchbox

        async def matchbox_readonly(route):
            request = route.request
            if (
                request.is_navigation_request()
                and request.frame == page.main_frame
                and not official_url(request.url, domain)
            ):
                await route.abort()
            else:
                await readonly_route(route)

        await page.route("**/*", matchbox_readonly)
        return await discover_matchbox(page, pack, job)
    guard = AuthGuard(domain)
    guard.live = on_ready is not None
    await page.route("**/*", guard.route)
    counters = {"automatic_login": 0, "automatic_oauth": 0, "automatic_email_verification": 0}
    steps = 0

    async def finish(result, **extra):
        # Never save auth URL, OAuth code, email body or OTP.
        guard.phase = "DISCOVERY"
        safe_url = page.url if official_url(page.url, domain) else "https://" + domain + "/"
        page_title = await page.title()
        field_labels = await page.locator("input,select,textarea").evaluate_all(
            "es=>es.filter(e=>e.type!=='hidden'&&e.type!=='password').map(e=>({type:e.type,name:e.name,label:[...e.labels||[]].map(l=>l.innerText.trim()).join(' ')}))"
        )
        return dict(
            result,
            **extra,
            page_title=page_title,
            observed_fields=field_labels,
            opened=bool(visited),
            submit_url=safe_url,
            automatic_steps=steps,
            automatic_login=counters["automatic_login"],
            automatic_oauth=counters["automatic_oauth"],
            automatic_email_verification=counters["automatic_email_verification"],
            blocked_business_writes=guard.blocked_writes,
            auth_requests=guard.auth_requests,
        )

    observed_clicks: dict[str, str] = {}
    visited: list[str] = []
    queue = [job["submit_url"]] if official_url(job.get("submit_url", ""), domain) else []
    home = "https://" + domain + "/"
    queue.append(home)
    last = review("OFFICIAL_SUBMIT_URL_UNCONFIRMED")
    # At most five observed official pages per candidate, inside the existing worker deadline.
    while queue and len(visited) < 5:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.append(url)
        if job.get("resume_in_place") and len(visited) == 1 and page.url == url:
            failure = None
        elif url in observed_clicks:
            targets = page.get_by_role("link", name=observed_clicks[url], exact=True)
            visible = [target for target in await targets.all() if await target.is_visible()]
            if visible:
                await visible[0].click(timeout=10000)
                await page.wait_for_timeout(800)
                failure = None
            else:
                failure = await navigate(page, url, domain)
        else:
            failure = await navigate(page, url, domain)
        if failure:
            last = failure
            if failure["outcome"] == "HUMAN_VERIFICATION_REQUIRED":
                return await finish(failure, discovery_visited=visited)
            continue
        authentication = await automatic_authentication(page, pack, guard, counters=counters, connector=connector)
        if authentication:
            return await finish(authentication, discovery_visited=visited)
        if domain == "telegra.ph" and on_ready is not None:
            from .publication import publication_adapter

            adapter = await publication_adapter(page)
            if adapter:
                guard.phase = "FINAL_SUBMIT"
                return await finish(await on_ready(page, adapter), discovery_visited=visited)
        qualification = await qualify(page, domain)
        if qualification and qualification["reason"] != "AUTH_CONTINUATION_REQUIRED":
            return await finish(qualification, discovery_visited=visited)
        for _ in range(4):
            if not await advance_local_step(page, pack, guard):
                break
            steps += 1
        if domain == "ebool.com" and on_ready is not None:
            from .ebool import review_adapter

            adapter = await review_adapter(page, pack)
            if adapter:
                guard.phase = "FINAL_SUBMIT"
                return await finish(await on_ready(page, adapter), discovery_visited=visited)
        if domain == "thehackstack.com" and on_ready is not None:
            from .hackstack import form_adapter

            adapter = await form_adapter(page, pack)
            if adapter:
                guard.phase = "FINAL_SUBMIT"
                return await finish(await on_ready(page, adapter), discovery_visited=visited)
        if await page.locator("form").count():
            result, adapter = await build_adapter(page, pack, domain, first_submit=on_ready is not None)
            if adapter:
                if on_ready is not None:
                    guard.phase = "FINAL_SUBMIT"
                    return await finish(await on_ready(page, adapter), discovery_visited=visited)
                path = persist_adapter(pack, domain, adapter)
                if not path:
                    return await finish(review("ADAPTER_REVIEW_REQUIRED"), discovery_visited=visited)
                return await finish(result, generated_adapter=str(path), discovery_visited=visited)
            # A newsletter/search form on the homepage isn't proof of a submission form.
            if (
                url != home
                or await page.locator("form")
                .filter(has=page.locator('input[placeholder*="Website"],input[name="website"]'))
                .count()
            ):
                last = result
        links = await page.locator("a[href]").evaluate_all("es=>es.map(e=>({url:e.href,text:e.innerText.trim()}))")
        qualified_links = [
            link
            for link in links
            if len(link["text"]) <= 100
            and ENTRY.search(link["text"])
            and official_url(link["url"], domain)
            and link["url"] not in visited
        ]
        qualified_links.sort(
            key=lambda link: not re.search(r"submit|add |list your|write for|contribute", link["text"], re.I)
        )
        for link in qualified_links:
            if urlparse(link["url"]).fragment or link["url"].endswith("#"):
                observed_clicks[link["url"]] = link["text"]
        queue.extend(link["url"] for link in qualified_links)
    return await finish(last, discovery_visited=visited)
