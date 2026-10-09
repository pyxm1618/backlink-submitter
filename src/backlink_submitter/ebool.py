"""Read eBool's final free-listing review after the observed details step."""

from .contracts import field_value


async def review_adapter(page, pack):
    heading = page.get_by_role("heading", name="Review & Submit", exact=True)
    if await heading.count() != 1 or not await heading.is_visible():
        return None
    text = (await page.locator("body").inner_text()).casefold()
    if "no payment required" not in text or "total due\nfree" not in text:
        return None
    final = page.get_by_role("button", name="Submit Listing", exact=True)
    if await final.count() != 1 or not await final.is_visible() or not await final.is_enabled():
        return None
    fields = {}
    for index, field in enumerate(["Product / App Name", "Website URL", "Public Contact Email"]):
        value = field_value(pack, field, required=True, platform="ebool.com")
        control = page.get_by_text(value, exact=True)
        if await control.count() != 1 or not await control.is_visible():
            return None
        await control.evaluate("(e,i)=>e.setAttribute('data-backlink-review',String(i))", index)
        fields[field] = f'[data-backlink-review="{index}"]'
    await final.evaluate("e=>e.setAttribute('data-backlink-final','ebool')")
    return {
        "domain": "ebool.com",
        "submit_url": page.url,
        "fields": fields,
        "required_fields": list(fields),
        "review_page": True,
        "login_required": False,
        "free_verified": True,
        "reciprocal_required": False,
        "qualification": "QUALIFIED_B",
        "final_action_verified": True,
        "final_submit_selector": '[data-backlink-final="ebool"]',
        "final_submit_text": "Submit Listing",
        "automatic_submit_allowed": False,
    }
