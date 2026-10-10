"""Playwright headless contexts; no cookie export, credential logging or challenge bypass."""

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from .contracts import now


def isolated_profile(profile):
    """Reject personal browser data, including aliases resolving into it, before any write."""
    root = Path(profile).expanduser().resolve()
    home = Path.home().resolve()
    personal = [home / "Library/Application Support/Google/Chrome", home / "Library/Application Support/Chromium"]
    parts = [part.casefold() for part in root.parts]
    if (
        any(root == p or root in p.parents or p in root.parents for p in personal)
        or any("tabbit" in part for part in parts)
        or any(part == "default" or re.fullmatch(r"profile[ _]\d+", part) for part in parts)
        or any(parts[i : i + 2] == ["google", "chrome"] for i in range(len(parts) - 1))
    ):
        raise ValueError("AUTOMATION_PROFILE_FORBIDDEN: personal Chrome/Tabbit data must remain untouched")
    if (root / "Default").is_symlink() and not (root / "Default").resolve().is_relative_to(root):
        raise ValueError("AUTOMATION_PROFILE_FORBIDDEN: profile alias leaves isolated data directory")
    return root


@asynccontextmanager
async def browser_session(playwright, *, profile=None):
    if profile:
        root = isolated_profile(profile)
        if (root / "SingletonLock").is_symlink() or (root / "SingletonLock").exists():
            raise ValueError("PROFILE_IN_USE: Owner must normally close only the dedicated browser; never delete lock")
        context = await playwright.chromium.launch_persistent_context(
            str(root),
            channel="chrome",
            headless=True,
            service_workers="block",
            ignore_default_args=["--use-mock-keychain"],
        )
        context._backlink_profile = str(root)
        try:
            yield context
        finally:
            await asyncio.wait_for(context.close(), 10)
    else:
        browser = await playwright.chromium.launch(channel="chrome", headless=True)
        context = await browser.new_context(service_workers="block")
        try:
            yield context
        finally:
            try:
                await asyncio.wait_for(context.close(), 10)
            finally:
                await asyncio.wait_for(browser.close(), 10)


def listing_url_allowed(url):
    parsed = urlparse(url)
    return (
        parsed.scheme in {"https", "http"}
        and bool(parsed.hostname)
        and not parsed.query
        and not parsed.fragment
        and not re.search(
            r"/(dashboard|admin|account|preview|search|submit|submission|status|login|edit)(?:/|$)", parsed.path, re.I
        )
    )


async def verify_listing(browser, url, *, screenshot=None):
    if not listing_url_allowed(url):
        return None
    context = await browser.new_context(service_workers="block")  # deliberately never storage_state/profile
    page = None
    try:
        page = await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if not response or response.status != 200 or not listing_url_allowed(page.url):
            return None
        if urlparse(page.url).hostname != urlparse(url).hostname:
            return None
        title = await page.title()
        body = await page.locator("body").inner_text(timeout=10000)
        if not re.search(r"\bWYRPlay\b", title + " " + body, re.I) or re.search(
            r"\b(dashboard|preview)\b", title, re.I
        ):
            return None
        links = await page.locator("a[href]").evaluate_all(
            "nodes=>nodes.filter(a=>a.getClientRects().length).map(a=>({href:a.href,rel:a.rel||'dofollow'}))"
        )
        links = [
            link
            for link in links
            if urlparse(link["href"]).hostname in {"www.wyrplay.com", "wyrplay.com"}
            and urlparse(link["href"]).scheme in {"https", "http"}
        ]
        if not links:
            return None
        robots = await page.locator('meta[name="robots"]').evaluate_all("nodes=>nodes.map(n=>n.content)")
        xrobots = response.headers.get("x-robots-tag", "")
        canonical = await page.locator('link[rel="canonical"]').evaluate_all("nodes=>nodes.map(n=>n.href)")
        if canonical and (
            len(canonical) != 1
            or not listing_url_allowed(canonical[0])
            or urlparse(canonical[0]).hostname != urlparse(page.url).hostname
        ):
            return None
        if screenshot:
            await page.screenshot(path=str(screenshot), full_page=True, timeout=10000)
        return {
            "project_id": "wyrplay",
            "evidence_code": "E4",
            "anonymous": True,
            "public_verified": True,
            "authentic_listing": True,
            "listing_url": page.url,
            "title": title,
            "links": links,
            "canonical": canonical,
            "meta_robots": robots,
            "x_robots_tag": xrobots,
            "indexability": "noindex" if "noindex" in (" ".join(robots) + " " + xrobots).lower() else "index",
            "checked_at": now(),
        }
    finally:
        try:
            if page:
                await asyncio.wait_for(page.close(run_before_unload=False), 5)
        finally:
            await asyncio.wait_for(context.close(), 10)
