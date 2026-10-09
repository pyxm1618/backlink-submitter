"""Publish the approved WYRPlay profile through Telegraph's observed rich editor."""

import sys

from .contracts import TARGET


async def publication_adapter(page):
    await page.locator('.ql-editor h1[data-label="Title"]').wait_for(state="visible", timeout=10000)
    if await page.locator('.ql-editor h1[data-label="Title"]').count() != 1:
        return None
    if await page.locator('.ql-editor address[data-label="Author"]').count() != 1:
        return None
    button = page.locator("#_publish_button")
    if await button.count() != 1 or (await button.inner_text()).strip().casefold() != "publish":
        return None
    return {
        "domain": "telegra.ph",
        "submit_url": "https://telegra.ph/",
        "fields": {
            "Product / App Name": ".ql-editor h1",
            "Long Description": ".ql-editor p:first-of-type",
            "Website URL": ".ql-editor p:last-of-type",
        },
        "required_fields": ["Product / App Name", "Website URL", "Long Description"],
        "rich_text_editor": "telegraph",
        "login_required": False,
        "free_verified": True,
        "reciprocal_required": False,
        "qualification": "QUALIFIED_B",
        "final_action_verified": True,
        "final_submit_selector": "#_publish_button",
        "final_submit_text": "PUBLISH",
        "automatic_submit_allowed": False,
    }


async def fill_publication(page, pack):
    await page.locator(".ql-editor h1").wait_for(state="visible", timeout=10000)
    await page.locator(".ql-editor h1").fill(pack["fields"]["Product / App Name"])
    await page.locator(".ql-editor address").fill(pack["fields"]["Operator / Legal Owner"])
    story = page.locator(".ql-editor p:first-of-type")
    await story.fill(pack["fields"]["Long Description"])
    await page.wait_for_timeout(150)
    await story.evaluate(
        "e=>{const r=document.createRange();r.selectNodeContents(e);r.collapse(false);const s=getSelection();s.removeAllRanges();s.addRange(r)}"
    )
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(150)
    link = page.locator(".ql-editor p:last-of-type")
    await link.fill(TARGET)
    await link.click()
    await page.keyboard.press("Meta+ArrowLeft" if sys.platform == "darwin" else "Home")
    await page.keyboard.press("Meta+Shift+ArrowRight" if sys.platform == "darwin" else "Shift+End")
    await page.wait_for_timeout(150)
    await page.locator("#_link_button").click()
    prompt = page.locator("input.prompt_input")
    await prompt.fill(TARGET)
    await prompt.press("Enter")
    if await page.locator(".ql-editor a").filter(has_text=TARGET).count() != 1:
        raise ValueError("PUBLICATION_BACKLINK_UNCONFIRMED")
    if await page.locator(".ql-editor a").get_attribute("href") != TARGET:
        raise ValueError("PUBLICATION_BACKLINK_UNCONFIRMED")
