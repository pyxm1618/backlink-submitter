"""Bounded, read-only official discovery. Ambiguity never becomes an executable adapter."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import Error as BrowserError

from .batch import adapter_gate, official_url
from .contracts import field_value, now, safe_artifact
from .workflow import human_boundary

ENTRY = re.compile(
    r"\b(submit|add (?:a |your )?(?:product|startup|tool|website)|list your product|launch|contribute|guest post)\b",
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
        await human_boundary(page)
    except ValueError:
        return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_VERIFICATION_REQUIRED"}
    except BrowserError:
        return {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "OFFICIAL_PAGE_UNAVAILABLE"}
    if not official_url(page.url, domain):
        return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "OWNER_LOGIN_REQUIRED"}
    if not response or response.status >= 400:
        return {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "HTTP_UNAVAILABLE_NOT_PERMANENT_PROOF"}
    return None


async def qualify(page, domain):
    text = (await page.locator("body").inner_text(timeout=10000)).casefold()
    for marker, outcome, reason in POLICIES:
        if re.search(r"(?:^|[.!?\n]\s*)" + re.escape(marker) + r"(?:[.!?\n]|$)", text):
            return {"outcome": outcome, "reason": reason, "source_url": page.url, "marker": marker, "checked_at": now()}
    if re.search(r"(?:sign in|log in|login|create an account) (?:to|required to) (?:submit|add|list|launch)", text):
        return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "OWNER_LOGIN_REQUIRED"}
    return None


async def controls(page, form):
    # Only stable, unique attributes observed in the current DOM; never nth()/position.
    return await form.locator("input,select,textarea").evaluate_all("""es=>es.map(e=>({
      tag:e.tagName, type:e.type, required:e.required, disabled:e.disabled,
      id:e.id, name:e.name, placeholder:e.getAttribute('placeholder')||'',
      aria:e.getAttribute('aria-label')||'', labels:[...e.labels||[]].map(l=>l.innerText.trim()),
      accept:e.accept||'', multiple:!!e.multiple, maxLength:e.maxLength,
      options:e.tagName==='SELECT'?[...e.options].map(o=>({text:o.text.trim(),value:o.value,disabled:o.disabled})):[]
    }))""")


async def selector_for(page, control):
    for attribute, value in [
        ("id", control["id"]),
        ("name", control["name"]),
        ("placeholder", control["placeholder"]),
        ("aria-label", control["aria"]),
    ]:
        if value and len(value) < 150 and re.fullmatch(r"[\w .:/?()-]+", value):
            selector = "[" + attribute + "=" + json.dumps(value) + "]"
            if await page.locator(selector).count() == 1:
                return selector
    return None


def semantic_field(control):
    terms = [*control["labels"], control["aria"], control["placeholder"], control["name"]]
    names = {
        "Product / App Name": {"product name", "startup name", "app name", "tool name", "product_name", "startup_name"},
        "Website URL": {"website", "website url", "product url", "url", "website_url"},
        "Public Contact Email": {"contact email", "email", "email address"},
        "One-line Pitch / Tagline": {"tagline", "one line pitch", "one-line pitch"},
        "Short Description": {"short description"},
        "Medium Description": {"description", "product description", "startup description"},
    }
    matches = {field for field, aliases in names.items() if any(term.casefold().strip() in aliases for term in terms)}
    return next(iter(matches)) if len(matches) == 1 else None


async def dispatch_matcher(page, form, final, domain):
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
    if len(sources) != len(scripts) + await page.locator("script[src]").count():
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
            await page.locator("script[src]").count()
            or any(script.strip() for _, script in sources)
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


async def build_adapter(page, pack, domain):
    forms = page.locator("form").filter(has=page.locator('button[type="submit"],input[type="submit"]'))
    if await forms.count() != 1:
        return review("ADAPTER_REVIEW_REQUIRED"), None
    form = forms.first
    final = form.locator('button[type="submit"],input[type="submit"]')
    if await final.count() != 1 or not await final.is_visible() or not await final.is_enabled():
        return review("ADAPTER_REVIEW_REQUIRED"), None
    # Existing final-action engine reads inner_text; input[value] finals need review.
    text = (await final.inner_text()).strip()
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
            if (
                not selector
                or "logo" not in semantic
                or control["accept"] not in {"image/png", ".png", "image/png,image/svg+xml"}
                or adapter.get("logo_selector")
            ):
                return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "UPLOAD_REQUIREMENTS_UNCONFIRMED"}, None
            # Size constraints stated elsewhere cannot be assumed; require explicit
            # compatibility in the visible form before accepting the official PNG.
            adapter.update(logo_selector=selector, logo_format="png", logo_required=control["required"])
        elif field and selector and control["type"] not in {"checkbox", "radio", "password"}:
            value = field_value(pack, field, required=control["required"], platform=domain)
            if (
                isinstance(value, dict)
                or control["maxLength"] > 0
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
            return {"outcome": "OWNER_INPUT_REQUIRED", "reason": "UNMAPPED_REQUIRED_FIELDS"}, None
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
    if not all(k in adapter["fields"] for k in ["Product / App Name", "Website URL"]) or not adapter.get("taxonomy"):
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
            ]
            if s in body
        ),
        None,
    )
    suitability = next(
        (s for s in ["we accept games", "games and web applications", "all web applications are welcome"] if s in body),
        None,
    )
    login = next(
        (s for s in ["no account required", "no login required", "submit without signing up"] if s in body), None
    )
    if (
        not free
        or not suitability
        or not login
        or re.search(r"(?:badge|reciprocal|backlink).{0,30}(?:required|mandatory)", body)
        or "no free submissions" in body
    ):
        return review("QUALIFICATION_FREE_OR_LOGIN_UNVERIFIED"), None
    if adapter.get("logo_selector"):
        return review("UPLOAD_SIZE_CONSTRAINT_REVIEW_REQUIRED"), None
    matcher, dispatch = await dispatch_matcher(page, form, final, domain)
    if not matcher:
        return review("DISPATCH_MATCHER_UNVERIFIED"), None
    adapter.update(free_verified=True, login_required=False, qualification="QUALIFIED_B", submission_request=matcher)
    adapter["provenance"] = {
        "verified_at": now(),
        "official_source": page.url,
        "field_evidence": evidence,
        "final_action_evidence": {"selector": final_selector, "text": text, "unique_count": 1},
        "dispatch_evidence": dispatch,
        "free_evidence": free,
        "suitability_evidence": suitability,
        "login_evidence": login,
    }
    from .batch_worker import readonly_ready

    gate = adapter_gate(adapter, pack)
    if not gate:
        readiness = await readonly_ready(page, adapter)
        gate = readiness if readiness["outcome"] != "READY_TO_SUBMIT" else None
    return (gate, None) if gate else ({"outcome": "READY_TO_SUBMIT", "reason": "DISCOVERY_ADAPTER_VERIFIED"}, adapter)


async def discover(page, pack, job):
    domain = job["domain"]

    async def official_readonly(route):
        request = route.request
        if (
            request.is_navigation_request()
            and request.frame == page.main_frame
            and not official_url(request.url, domain)
        ):
            await route.abort()
        else:
            await readonly_route(route)

    await page.route("**/*", official_readonly)
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
        failure = await navigate(page, url, domain)
        if failure:
            last = failure
            if failure["outcome"] == "HUMAN_VERIFICATION_REQUIRED":
                return dict(failure, discovery_visited=visited, submit_url=url)
            continue
        qualification = await qualify(page, domain)
        if qualification:
            return dict(qualification, discovery_visited=visited, submit_url=page.url)
        if await page.locator("form").count():
            result, adapter = await build_adapter(page, pack, domain)
            if adapter:
                safe_artifact(adapter)
                path = Path(pack["root"]) / "adapters" / (domain + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    # No overwrite, no git operation, and no partially readable adapter.
                    staged = path.with_suffix(".discovery")
                    with staged.open("x") as stream:
                        stream.write(json.dumps(adapter, ensure_ascii=False, indent=2) + "\n")
                    try:
                        import os

                        os.link(staged, path)
                    finally:
                        staged.unlink()
                except FileExistsError:
                    return dict(review("ADAPTER_REVIEW_REQUIRED"), discovery_visited=visited)
                return dict(result, generated_adapter=str(path), discovery_visited=visited, submit_url=page.url)
            # A newsletter/search form on the homepage isn't proof of a submission form.
            if (
                url != home
                or await page.locator("form")
                .filter(has=page.locator('input[placeholder*="Website"],input[name="website"]'))
                .count()
            ):
                return dict(result, discovery_visited=visited, submit_url=page.url)
        links = await page.locator("a[href]").evaluate_all("es=>es.map(e=>({url:e.href,text:e.innerText.trim()}))")
        queue.extend(
            link["url"]
            for link in links
            if ENTRY.search(link["text"]) and official_url(link["url"], domain) and link["url"] not in visited
        )
    return dict(last, discovery_visited=visited)
