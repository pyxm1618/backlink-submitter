"""Bounded authentication and local form progression, never a business Submit grant."""

import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

from .contracts import MemorySecret, extract_otp, mail_matches, now, timestamp

AUTH_LABEL = re.compile(
    r"^(?:sign in|log in|login|sign up|register|create (?:an? )?account|continue with google|sign in with google|send (?:code|magic link)|verify(?: email| code)?|登录|登入)$",
    re.I,
)
AUTH_FIELDS = re.compile(
    r"(?:email|email_address|user_email|identifier|name|full_name|log|pwd|wp-submit|testcookie|username|user_name|password|password_confirmation|confirm_password|passwd|code|otp|csrf|xsrf|nonce|_token|authenticity_token|redirect|return|remember|submit|login|action|state|token|credential)",
    re.I,
)
OWNER_REASONS = {
    "HUMAN_VERIFICATION_REQUIRED",
    "OWNER_PASSWORD_REQUIRED",
    "OWNER_2FA_REQUIRED",
    "OWNER_DEVICE_CONFIRMATION",
    "OWNER_RISK_CONFIRMATION",
    "OWNER_FACT_REQUIRED",
    "OWNER_AUTHORIZATION_REQUIRED",
}


async def owner_boundary(page):
    text = (await page.locator("body").inner_text(timeout=10000)).casefold()
    for pattern, reason in [
        (
            r"verify (?:you are|that you.re) human|checking your browser|请.*人机验证|完成.*滑块|(?:complete|solve|verify).*captcha",
            "HUMAN_VERIFICATION_REQUIRED",
        ),
        (
            r"(?:enter|verification).*authenticator|authenticator (?:code|verification)|two.step verification|enter.*(?:sms|2fa|two.factor)|text message.*code",
            "OWNER_2FA_REQUIRED",
        ),
        (r"confirm your device|device confirmation|设备确认", "OWNER_DEVICE_CONFIRMATION"),
        (r"unusual traffic|verify it.s you|risk verification|风险验证", "OWNER_RISK_CONFIRMATION"),
    ]:
        if re.search(pattern, text):
            return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": reason}
    for e in await page.locator('input[type="password"]').all():
        if await e.is_visible() and await e.evaluate("e=>e.value.length===0"):
            return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "OWNER_PASSWORD_REQUIRED"}
    for e in await page.locator(
        'iframe[src*="challenges.cloudflare.com"],iframe[src*="recaptcha"],iframe[src*="hcaptcha"]'
    ).all():
        if await e.is_visible():
            return {"outcome": "HUMAN_VERIFICATION_REQUIRED", "reason": "HUMAN_VERIFICATION_REQUIRED"}
    return None


class AuthGuard:
    """Only DOM/handler-proven auth endpoints and auth-only keys may mutate in AUTH."""

    def __init__(self, domain, matcher=None):
        self.domain = domain
        self.matcher = matcher
        self.phase = "DISCOVERY"
        self.live = False
        self.endpoints = {}
        self.oauth_links = set()
        self.auth_hosts = set()
        self.oauth_active = False
        self.oauth_provider_seen = False
        self.registration_active = False
        self.login_active = False
        self.verification_families = set()
        self.blocked_writes = 0
        self.auth_requests = 0

    def same_site(self, url):
        p = urlparse(url)
        return (
            p.scheme == "https"
            and (
                (p.hostname or "").removeprefix("www.") == self.domain.removeprefix("www.")
                or (p.hostname or "").endswith("." + self.domain.removeprefix("www."))
            )
            and not p.username
            and not p.password
        )

    def navigation_allowed(self, url):
        if self.same_site(url):
            return True
        if url in self.oauth_links:
            self.oauth_provider_seen = urlparse(url).hostname == "accounts.google.com"
            return True
        p = urlparse(url)
        redirects = parse_qs(p.query).get("redirect_to", [])
        if self.oauth_active and p.scheme == "https" and len(redirects) == 1 and self.same_site(redirects[0]):
            if p.path.startswith("/auth/"):
                self.auth_hosts.add(p.hostname)
                return True
        if self.oauth_active and p.scheme == "https" and p.hostname in self.auth_hosts:
            return True
        if self.oauth_active and p.scheme == "https" and p.hostname == "accounts.google.com":
            self.oauth_provider_seen = True
            query = parse_qs(p.query)
            if p.path in {"/o/oauth2/auth", "/o/oauth2/v2/auth"}:
                redirects = query.get("redirect_uri", [])
                scopes = set(" ".join(query.get("scope", [])).split())
                return (
                    len(redirects) == 1
                    and (self.same_site(redirects[0]) or urlparse(redirects[0]).hostname in self.auth_hosts)
                    and scopes
                    <= {
                        "openid",
                        "email",
                        "profile",
                        "https://www.googleapis.com/auth/userinfo.email",
                        "https://www.googleapis.com/auth/userinfo.profile",
                    }
                )
            return True
        return False

    async def observe(self, page):
        for frame in await page.locator("iframe[src]").all():
            if not await frame.is_visible():
                continue
            url = urlparse(await frame.get_attribute("src") or "")
            for family in ["hcaptcha.com", "recaptcha.net", "challenges.cloudflare.com"]:
                if url.scheme == "https" and (url.hostname == family or (url.hostname or "").endswith("." + family)):
                    self.verification_families.add(family)
            if (
                url.scheme == "https"
                and url.hostname in {"www.google.com", "www.recaptcha.net"}
                and url.path.startswith("/recaptcha/")
            ):
                self.verification_families.add("google-recaptcha")
        for form in await page.locator("form").all():
            labels = await form.locator('button,input[type="submit"]').evaluate_all(
                'es=>es.map(e=>e.innerText.trim()||e.value||"")'
            )
            fields = await form.locator("input,select,textarea").evaluate_all(
                "es=>es.map(e=>({name:e.name,type:e.type}))"
            )
            names = {e["name"] for e in fields if e["name"]}
            if (
                not any(AUTH_LABEL.fullmatch(x) for x in labels)
                or not names
                or any(not AUTH_FIELDS.fullmatch(x) for x in names)
            ):
                continue
            action = await form.get_attribute("action")
            method = (await form.get_attribute("method") or "GET").upper()
            # A native action is auth proof only when its controls and action label are auth-only.
            if action and self.same_site(urljoin(page.url, action)) and method in {"POST", "PUT", "PATCH"}:
                p = urlparse(urljoin(page.url, action))
                self.endpoints[(method, p.hostname, p.path)] = names
        links = await page.locator("a[href]").evaluate_all("es=>es.map(e=>({url:e.href,text:e.innerText.trim()}))")
        for link in links:
            p = urlparse(link["url"])
            q = parse_qs(p.query)
            redirects = q.get("redirect_uri", [])
            if (
                AUTH_LABEL.fullmatch(link["text"])
                and p.scheme == "https"
                and p.hostname == "accounts.google.com"
                and q.get("client_id")
                and len(redirects) == 1
                and self.same_site(redirects[0])
            ):
                self.oauth_links.add(link["url"])

    def permits(self, method, url, payload, *, frame_url=""):

        p = urlparse(url)
        if self.matcher and (p.hostname, p.path) == (self.matcher["host"], self.matcher["path"]):
            return False
        if method in {"GET", "HEAD", "OPTIONS"}:
            return True
        # Telegraph initializes its editor session here; this is not article publication.
        if self.domain == "telegra.ph" and p.hostname == "edit.telegra.ph" and p.path == "/check" and method == "POST":
            return True
        if (
            self.live
            and self.phase == "FINAL_SUBMIT"
            and self.domain == "telegra.ph"
            and p.hostname == "edit.telegra.ph"
        ):
            return method in {"POST", "PUT", "PATCH"}
        if self.live and self.phase in {"FORM_STEP", "FINAL_SUBMIT"} and self.same_site(url):
            return method in {"POST", "PUT", "PATCH"}
        source = urlparse(frame_url)
        for family in self.verification_families:
            if family == "google-recaptcha":
                if (
                    source.hostname in {"www.google.com", "www.recaptcha.net"}
                    and source.path.startswith("/recaptcha/")
                    and p.hostname in {"www.google.com", "www.recaptcha.net"}
                    and p.path.startswith("/recaptcha/")
                ):
                    return True
            elif (
                (source.hostname == family or (source.hostname or "").endswith("." + family))
                and (p.hostname == family or (p.hostname or "").endswith("." + family))
                and source.scheme == p.scheme == "https"
            ):
                return True
        if self.phase not in {"AUTH", "VERIFICATION"}:
            return False
        if self.live and (self.registration_active or self.login_active) and self.same_site(url):
            # This phase follows the observed account-creation button with approved auth fields.
            # Next/React actions need not expose a conventional form-encoded payload.
            return not isinstance(payload, dict) or not any(
                re.search(r"product|website|listing|description|payment|charge|price", key, re.I) for key in payload
            )
        # The platform's Cloudflare challenge transport is identified from an actual challenge,
        # never a general permission for platform business requests.
        if (
            "challenges.cloudflare.com" in self.verification_families
            and self.same_site(url)
            and p.path.startswith("/cdn-cgi/challenge-platform/")
        ):
            return True
        if self.oauth_active and self.phase == "AUTH" and self.same_site(url):
            # The observed Google button may initiate a SPA/server action. No adapter is needed.
            if not isinstance(payload, dict) or not any(
                re.search(r"product|website|listing|description", k, re.I) for k in payload
            ):
                return True
        allowed = self.endpoints.get((method, p.hostname, p.path))
        if allowed is not None:
            return (
                isinstance(payload, dict)
                and bool(payload)
                and set(payload) <= allowed
                and all(AUTH_FIELDS.fullmatch(k) for k in payload)
            )
        # Observed, platform-bound Google OAuth flow only; no broad third-party POST access.
        return bool(
            self.oauth_active
            and p.scheme == "https"
            and p.hostname == "accounts.google.com"
            and re.fullmatch(
                r"/(?:_|v\d|signin|o/oauth2|ServiceLogin|AccountChooser|CheckCookie|RotateCookies)(?:/.*)?", p.path
            )
        )

    async def refresh_route(self, route, page):
        parsed = urlparse(route.request.url)
        if self.matcher and (parsed.hostname, parsed.path) == (self.matcher["host"], self.matcher["path"]):
            await route.abort()
            return
        if route.request.method not in {"GET", "HEAD", "OPTIONS"}:
            await self.observe(page)
        await self.route(route)

    async def route(self, route):
        request = route.request
        parsed = urlparse(request.url)
        if self.matcher and (parsed.hostname, parsed.path) == (self.matcher["host"], self.matcher["path"]):
            await route.abort()
            return
        if request.is_navigation_request() and not self.navigation_allowed(request.url):
            await route.abort()
            return
        payload = None
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            try:
                raw = request.post_data or ""
                payload = (
                    json.loads(raw)
                    if request.headers.get("content-type", "").startswith("application/json")
                    else {k: v for k, v in parse_qs(raw, keep_blank_values=True).items()}
                )
            except (ValueError, TypeError, UnicodeDecodeError):
                payload = None
        if not self.permits(request.method, request.url, payload, frame_url=request.frame.url):
            self.blocked_writes += int(request.method not in {"GET", "HEAD", "OPTIONS"})
            await route.abort()
        else:
            self.auth_requests += int(request.method not in {"GET", "HEAD", "OPTIONS"})
            await route.fallback()


async def mailbox_challenge(connector, *, domain, recipient, started_at, length):
    """Use an existing connector callable; every account/time/sender/semantic binding is required."""
    profile = await connector("get_profile", {})
    if not profile.get("email") or "@" not in profile["email"]:
        return None
    messages = await connector(
        "search_messages",
        {
            "query": f"to:{recipient} after:{int(timestamp(started_at).timestamp())} -in:spam -in:trash",
            "max_results": 10,
        },
    )
    found = []
    for message in messages:
        if re.search(
            r"password reset|account recovery|reset your password|payment verification|security alert",
            message.get("subject", ""),
            re.I,
        ):
            continue
        if not mail_matches(message, domain=domain, recipient=recipient, started_at=started_at):
            continue
        if (
            timestamp(message["received_at"]) > timestamp(now())
            or (timestamp(message["received_at"]) - timestamp(started_at)).total_seconds() > 600
        ):
            continue
        if length is not None:
            secret = extract_otp(message, domain=domain, recipient=recipient, requested_at=started_at, length=length)
            if secret:
                found.append(secret.value)
        elif re.search(r"magic link|sign.in|confirm.*email|verify.*email", message.get("subject", ""), re.I):
            links = re.findall(r'https://[^\s<>"\']+', message.get("body", ""))
            for link in links:
                p = urlparse(link)
                if (
                    (p.hostname or "").removeprefix("www.") == domain.removeprefix("www.")
                    and re.search(r"auth|verify|confirm|magic|login", p.path, re.I)
                    and not re.search(r"reset|recover|unsubscribe|oauth|payment", p.path, re.I)
                    and not p.username
                    and not p.password
                ):
                    found.append(link.rstrip("."))
    return MemorySecret(found[0]) if len(set(found)) == 1 else None


async def wait_for_mail(connector, **binding):
    import asyncio

    for attempt in range(3):
        secret = await mailbox_challenge(connector, **binding)
        if secret is not None:
            return secret
        if attempt < 2:
            await asyncio.sleep(5)
    return None


async def automatic_authentication(page, pack, guard, *, connector=None, counters=None):
    counts = counters if counters is not None else {}
    for key in ["automatic_login", "automatic_oauth", "automatic_email_verification"]:
        counts.setdefault(key, 0)
    await guard.observe(page)
    pending_kind = None
    account_secret = connector.platform_password(guard.domain) if hasattr(connector, "platform_password") else None
    registration_attempted = False
    password_login_attempted = False
    for _ in range(8):
        boundary = await owner_boundary(page)
        creation = False
        if registration_attempted and re.search(r"/(?:register|signup|sign-up)(?:/|$)", urlparse(page.url).path):
            return {
                "outcome": "TEMPORARILY_UNAVAILABLE",
                "reason": "REGISTRATION_RESPONSE_UNCONFIRMED",
                "automation_pending": True,
            }
        if boundary and boundary["reason"] == "OWNER_PASSWORD_REQUIRED" and guard.same_site(page.url):
            passwords = [e for e in await page.locator('input[type="password"]').all() if await e.is_visible()]
            text = (await page.locator("body").inner_text()).casefold()
            if account_secret is not None and not re.search(
                r"/(?:register|signup|sign-up)(?:/|$)", urlparse(page.url).path
            ):
                if len(passwords) == 1 and account_secret is not None and not password_login_attempted:
                    await passwords[0].fill(account_secret.value)
                    password_login_attempted = True
                    boundary = await owner_boundary(page)
                else:
                    return {
                        "outcome": "TEMPORARILY_UNAVAILABLE",
                        "reason": "REGISTRATION_RESPONSE_UNCONFIRMED",
                        "automation_pending": True,
                    }
            new_account = len(passwords) in {1, 2} and bool(
                re.search(r"create.*account|sign up|register|新建.*账号|注册", text)
                and (
                    len(passwords) == 1
                    and re.search(r"/(?:register|signup|sign-up)(?:/|$)", urlparse(page.url).path)
                    or len(passwords) == 2
                    and re.search(r"confirm password|repeat password|确认密码", text)
                )
            )
            if (
                boundary
                and new_account
                and not registration_attempted
                and connector is not None
                and hasattr(connector, "new_account_password")
            ):
                secret = await connector.new_account_password(guard.domain)
                for control in passwords:
                    await control.fill(secret.value)
                account_secret = secret
                del secret
                counts["new_account_credentials_filled"] = 1
                creation = True
                boundary = await owner_boundary(page)
            elif (
                boundary
                and not registration_attempted
                and connector is not None
                and hasattr(connector, "new_account_password")
            ):
                links = await page.locator("a[href]").evaluate_all(
                    "es=>es.map(e=>({url:e.href,text:e.innerText.trim()}))"
                )
                registrations = {
                    link["url"]: link["text"]
                    for link in links
                    if guard.same_site(link["url"])
                    and re.search(r"sign up|register|create (?:a free |free )?account|create one", link["text"], re.I)
                    and not re.search(r"paid|buy|reset|forgot", link["text"], re.I)
                }
                if len(registrations) == 1:
                    href, label = next(iter(registrations.items()))
                    await page.get_by_role("link", name=label, exact=True).first.click(timeout=10000)
                    await page.wait_for_timeout(800)
                    continue
        google_controls = page.get_by_role(
            "button", name=re.compile(r"^(?:(?:continue|sign in|log in|login|sign up) with )?google$", re.I)
        )
        google_links = page.get_by_role(
            "link", name=re.compile(r"^(?:(?:continue|sign in|log in|login|sign up) with )?google$", re.I)
        )
        alternatives = [e for e in [*await google_controls.all(), *await google_links.all()] if await e.is_visible()]
        if (
            alternatives
            and not creation
            and not password_login_attempted
            and (boundary is None or boundary["reason"] == "OWNER_PASSWORD_REQUIRED")
            and pending_kind is None
        ):
            if len(alternatives) == 1 and guard.same_site(page.url):
                guard.phase = "AUTH"
                guard.oauth_active = True
                await alternatives[0].click(timeout=10000)
                await page.wait_for_timeout(1200)
                pending_kind = "automatic_oauth"
                continue
        if boundary and boundary["reason"] == "OWNER_PASSWORD_REQUIRED" and alternatives:
            if await google_links.count() == 1:
                href = await google_links.get_attribute("href")
                url = urljoin(page.url, href or "")
                if url in guard.oauth_links or guard.same_site(url):
                    guard.phase = "AUTH"
                    guard.oauth_active = True
                    await google_links.click(timeout=10000)
                    await page.wait_for_timeout(300)
                    pending_kind = "automatic_oauth"
                    continue
            return {
                "outcome": "TEMPORARILY_UNAVAILABLE",
                "reason": "AUTO_OAUTH_BINDING_UNCONFIRMED",
                "automation_pending": True,
            }
        if (
            boundary
            and boundary["reason"] == "OWNER_PASSWORD_REQUIRED"
            and pending_kind is None
            and urlparse(page.url).path in {"", "/"}
        ):
            # A homepage login widget is not proof that the observed publication channel needs it.
            channels = await page.locator("a[href]").evaluate_all(
                "es=>es.map(e=>({url:e.href,text:e.innerText.trim()}))"
            )
            if any(
                guard.same_site(c["url"])
                and c["url"] != page.url
                and re.search(
                    r"submit|add (?:your |a )?(?:product|tool|website)|list your|contribute|write for us|收录|投稿|提交",
                    c["text"],
                    re.I,
                )
                for c in channels
            ):
                return None
        if boundary:
            return dict(
                boundary,
                oauth_flow_started=pending_kind == "automatic_oauth",
                owner_action_proof={
                    "kind": "visible_challenge_or_required_password",
                    "reason": boundary["reason"],
                    "google_alternative_present": bool(alternatives),
                },
            )
        text = (await page.locator("body").inner_text()).casefold()
        otp = page.locator(
            'input[autocomplete="one-time-code"],input[name="otp"],input[name="verification_code"],input[name="code"]'
        )
        if await otp.count() == 1:
            counts["gmail_challenge_triggered"] = 1
            if connector is None:
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "GMAIL_CONNECTOR_UNAVAILABLE",
                    "automation_pending": True,
                }
            size = await otp.get_attribute("maxlength")
            if not size or not 4 <= int(size) <= 8:
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "EMAIL_BINDING_UNCONFIRMED",
                    "automation_pending": True,
                }
            try:
                secret = await wait_for_mail(
                    connector,
                    domain=guard.domain,
                    recipient=counts.get("registration_email", pack["fields"]["Public Contact Email"]),
                    started_at=counts.get("email_requested_at", now()),
                    length=int(size),
                )
            except (ConnectionError, OSError):
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "GMAIL_CONNECTOR_UNAVAILABLE",
                    "automation_pending": True,
                }
            if secret is None:
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "EMAIL_BINDING_UNCONFIRMED",
                    "automation_pending": True,
                }
            await otp.fill(secret.value)
            del secret
            pending_kind = "automatic_email_verification"
        elif re.search(
            r"check your (?:email|inbox).*(?:magic|sign.in|confirm|verify)|magic link.*(?:sent|email)|(?:verification|confirmation) email.{0,50}sent|confirm your email|verify your email address",
            text,
        ):
            counts["gmail_challenge_triggered"] = 1
            if connector is None or "email_requested_at" not in counts:
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "GMAIL_CONNECTOR_UNAVAILABLE",
                    "automation_pending": True,
                }
            try:
                secret = await wait_for_mail(
                    connector,
                    domain=guard.domain,
                    recipient=counts.get("registration_email", pack["fields"]["Public Contact Email"]),
                    started_at=counts["email_requested_at"],
                    length=None,
                )
            except (ConnectionError, OSError):
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "GMAIL_CONNECTOR_UNAVAILABLE",
                    "automation_pending": True,
                }
            if secret is None:
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "EMAIL_BINDING_UNCONFIRMED",
                    "automation_pending": True,
                }
            await page.goto(secret.value, wait_until="domcontentloaded", timeout=20000)
            del secret
            pending_kind = "automatic_email_verification"
            continue
        # Reuse an existing platform session: absence of auth controls requires no login click.
        links = page.get_by_role("link").filter(
            has_text=re.compile(r"^(?:continue|sign in|login|log in) with google$", re.I)
        )
        if await links.count() == 1:
            href = await links.get_attribute("href")
            url = urljoin(page.url, href or "")
            if url in guard.oauth_links or guard.same_site(url):
                guard.phase = "AUTH"
                guard.oauth_active = True
                await links.click(timeout=10000)
                await page.wait_for_timeout(300)
                pending_kind = "automatic_oauth"
                continue
        if (urlparse(page.url).hostname or "") == "accounts.google.com":
            # Account identity comes from the connected Owner mailbox, never another project.
            identifier = page.locator('input[name="identifier"]')
            if await identifier.count() == 1 and await identifier.is_visible() and connector is not None:
                profile = await connector("get_profile", {})
                if profile.get("email"):
                    counts["registration_email"] = profile["email"]
                    await identifier.fill(profile["email"])
                    next_button = page.get_by_role("button", name=re.compile(r"^(?:Next|下一步)$", re.I))
                    if await next_button.count() == 1:
                        await next_button.click(timeout=10000)
                        await page.wait_for_timeout(1000)
                        continue
            # Exactly one existing account; never supply a password or invent an identity.
            choices = page.locator("[data-identifier]")
            if await choices.count() > 1 and connector is not None:
                profile = await connector("get_profile", {})
                matching = [
                    e
                    for e in await choices.all()
                    if (await e.get_attribute("data-identifier") or "").casefold()
                    == profile.get("email", "").casefold()
                ]
                if len(matching) == 1:
                    counts["registration_email"] = profile["email"]
                    await matching[0].click(timeout=10000)
                    await page.wait_for_timeout(800)
                    continue
            if await choices.count() == 1:
                await choices.click(timeout=10000)
                await page.wait_for_timeout(300)
                continue
            consent = page.get_by_role("button", name=re.compile(r"^(?:Continue|Allow|继续|允许)$", re.I))
            visible_consent = [e for e in await consent.all() if await e.is_visible()]
            if len(visible_consent) == 1:
                await visible_consent[0].click(timeout=10000)
                await page.wait_for_timeout(800)
                continue
            return {
                "outcome": "TEMPORARILY_UNAVAILABLE",
                "reason": "OAUTH_SESSION_OR_CONSENT_UNCONFIRMED",
                "automation_pending": True,
            }
        auth_links = page.get_by_role("link", name=re.compile(r"^(?:sign in|log in|login|登录)$", re.I))
        visible_links = [link for link in await auth_links.all() if await link.is_visible()]
        if len(visible_links) == 1 and (pending_kind is None or account_secret is not None):
            href = await visible_links[0].get_attribute("href")
            if href and guard.same_site(urljoin(page.url, href)) and urljoin(page.url, href) != page.url:
                guard.phase = "AUTH"
                await visible_links[0].click(timeout=10000)
                await page.wait_for_timeout(300)
                await guard.observe(page)
                continue
        forms = page.locator("form")
        chosen = None
        for form in await forms.all():
            if not await form.is_visible():
                continue
            labels = await form.locator('button,input[type="submit"]').evaluate_all(
                'es=>es.map(e=>e.innerText.trim()||e.value||"")'
            )
            if any(AUTH_LABEL.fullmatch(x) for x in labels):
                chosen = form
                break
        if chosen is None:
            guard.phase = "DISCOVERY"
            if not guard.same_site(page.url):
                return {
                    "outcome": "TEMPORARILY_UNAVAILABLE",
                    "reason": "AUTH_NAVIGATION_FAILED",
                    "automation_pending": True,
                }
            if pending_kind and guard.same_site(page.url) and not re.search(r"sign in to|log in to|需要登录", text):
                from .discovery import controls, semantic_field

                observed_fields = {semantic_field(control) for control in await controls(page, page)}
                logout = page.get_by_role("link", name=re.compile(r"^(?:logout|log out|sign out|退出登录)$", re.I))
                authenticated = {"Product / App Name", "Website URL"} <= observed_fields or any(
                    [await control.is_visible() for control in await logout.all()]
                )
                if authenticated and (pending_kind != "automatic_oauth" or guard.oauth_provider_seen):
                    counts[pending_kind] += 1
            return None
        await guard.observe(page)
        if creation:
            name = chosen.locator('input[name="name"],input[autocomplete="name"]')
            if await name.count() == 1:
                await name.fill(pack["fields"]["Operator / Legal Owner"])
            username = chosen.locator('input[name="username"],input[name="user_name"]')
            if await username.count() == 1:
                brand = pack["fields"]["Product / App Name"].casefold()
                if not await username.evaluate(
                    "(e,v)=>{const c=e.cloneNode(true);c.value=v;return c.checkValidity();}", brand
                ):
                    return {
                        "outcome": "TEMPORARILY_UNAVAILABLE",
                        "reason": "REGISTRATION_USERNAME_CONSTRAINT",
                        "automation_pending": True,
                    }
                await username.fill(brand)
        email = chosen.locator('input[type="email"],input[autocomplete="username"]')
        if await email.count() == 1:
            account_email = connector.platform_email(guard.domain) if hasattr(connector, "platform_email") else None
            account_email = account_email or pack["fields"]["Public Contact Email"]
            await email.fill(account_email)
            counts["registration_email"] = account_email
        button = chosen.locator('button,input[type="submit"]')
        legal = [
            b
            for b in await button.all()
            if AUTH_LABEL.fullmatch((await b.inner_text()).strip() or (await b.get_attribute("value") or ""))
        ]
        if len(legal) != 1:
            return {
                "outcome": "TEMPORARILY_UNAVAILABLE",
                "reason": "AUTH_ACTION_UNCONFIRMED",
                "automation_pending": True,
            }
        guard.phase = "VERIFICATION" if pending_kind == "automatic_email_verification" else "AUTH"
        guard.registration_active = creation
        guard.login_active = password_login_attempted
        registration_attempted = registration_attempted or creation
        counts.setdefault("email_requested_at", now())
        clicked_label = (await legal[0].inner_text()).strip()
        await legal[0].click(timeout=10000)
        await page.wait_for_timeout(1800)
        if (
            (creation or password_login_attempted)
            and await legal[0].count() == 1
            and await legal[0].is_visible()
            and (await legal[0].inner_text()).strip() == clicked_label
        ):
            return {
                "outcome": "TEMPORARILY_UNAVAILABLE",
                "reason": "REGISTRATION_RESPONSE_UNCONFIRMED",
                "automation_pending": True,
            }
        pending_kind = pending_kind or "automatic_login"
    guard.phase = "DISCOVERY"
    return {"outcome": "TEMPORARILY_UNAVAILABLE", "reason": "AUTH_PROGRESS_BOUND_REACHED", "automation_pending": True}


async def advance_local_step(page, pack, guard):
    """Advance unique observed non-final steps; business writes require scoped LIVE."""
    next_buttons = page.get_by_role(
        "button",
        name=re.compile(
            r"^(?:Next|Continue|Review|Continue to Review|Continue setup|Save and continue|Next step|下一步|继续)$",
            re.I,
        ),
    )
    visible = [b for b in await next_buttons.all() if await b.is_visible() and await b.is_enabled()]
    if len(visible) != 1:
        return False
    await fill_known_controls(page, pack, guard.domain)
    if guard.domain == "ebool.com":
        search = page.get_by_placeholder("Search categories...", exact=True)
        if await search.count() == 1 and await search.is_visible():
            for category in ["Games", "Entertainment", "Party Games", "Social Games", "Web Application", "Education"]:
                if category == "Education" and "classroom" not in pack["fields"]["Medium Description"].casefold():
                    continue
                guard.phase = "FORM_STEP" if getattr(guard, "live", False) else "DISCOVERY"
                await search.fill(category)
                await page.wait_for_timeout(1200)
                option = page.get_by_role("button", name=category, exact=True)
                if await option.count() == 1 and await option.is_visible():
                    await option.click()
                    await search.wait_for(state="hidden", timeout=5000)
                    break
        # Reactive category lookup may redraw other controls; read and refill the current DOM.
        await fill_known_controls(page, pack, guard.domain)
    guard.phase = "FORM_STEP" if getattr(guard, "live", False) else "DISCOVERY"
    before = guard.blocked_writes
    before_text = await page.locator("body").inner_text()
    before_url = page.url
    await visible[0].click(timeout=10000)
    await page.wait_for_timeout(800)
    return guard.blocked_writes == before and (
        before_url != page.url or before_text != await page.locator("body").inner_text()
    )


async def fill_known_controls(page, pack, domain):
    """Fill approved facts before handing over a genuine password or challenge."""
    from .contracts import field_value, fitting_field_value
    from .discovery import controls, selector_for, semantic_field

    filled = []
    for control in await controls(page, page):
        if control["disabled"] or control["type"] in {
            "password",
            "hidden",
            "file",
            "checkbox",
            "radio",
            "submit",
            "button",
        }:
            continue
        field = semantic_field(control)
        selector = await selector_for(page, control)
        if not field or not selector or not await page.locator(selector).is_visible():
            continue
        value = field_value(pack, field, required=False, platform=domain)
        if not value:
            continue
        value = fitting_field_value(pack, field, value, control["maxLength"])
        locator = page.locator(selector)
        if await locator.input_value() == value:
            filled.append(field)
            continue
        if control["tag"] == "SELECT":
            if value not in [option["text"] for option in control["options"]]:
                continue
            await locator.select_option(label=value)
        else:
            await locator.fill(value)
        if control["tag"] == "SELECT" or await locator.input_value() == value:
            filled.append(field)
    return filled
