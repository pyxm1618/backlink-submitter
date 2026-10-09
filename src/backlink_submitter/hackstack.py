"""Fill the observed Hack Stack product form from WYRPlay's confirmed facts."""

from .contracts import TARGET, validate_payload

DESCRIPTION = """WYRPlay is a free online Would You Rather game for friends, families, kids, couples, classrooms, parties, and road trips. Each question presents two choices. Players pick A or B, vote anonymously, and compare their choice with real community results. The format gives people a starting point for conversation and a way to explore different answers together.

The question collections cover kids, funny, hard, friends, and couples themes. Players can browse categories and use filters to find questions for the people and setting they have in mind. A group of friends can choose questions for a party, couples can explore a collection together, and families can look for questions in the kids collection. Teachers can use the classroom setting, while people planning a road trip can find questions to bring into their activity.

The product supports both online play and offline activities. Online, players can work through the choices and see the community voting results. Presenter-friendly gameplay provides another way to use the questions with a group. Printable question sets let people take questions into an offline activity, such as a classroom, family gathering, or party, rather than depending on the online game throughout the activity.

Core play is free and does not require an account. Voting is anonymous. WYRPlay runs on the web and is a non-AI social game. Its focus is curated questions, two-choice gameplay, category browsing, filters, presenter-friendly play, and printable question sets. The official website brings these options together for people looking for Would You Rather questions and activities to share with others."""


async def form_adapter(page, pack):
    if await page.get_by_role("heading", name="Submit a Product", exact=True).count() != 1:
        return None
    final = page.get_by_role("button", name="Submit Product", exact=True)
    if await final.count() != 1 or not await final.is_visible():
        return None
    owners = page.get_by_text(pack["fields"]["Operator / Legal Owner"], exact=True)
    visible_owners = [control for control in await owners.all() if await control.is_visible()]
    if len(visible_owners) != 1:
        return None
    owner = visible_owners[0]
    await owner.evaluate("e=>e.setAttribute('data-backlink-session','owner')")
    for selector in [
        'input[name="name"]',
        'input[name="url"]',
        'textarea[name="tagline"]',
        ".note-editable",
        'input[name="image"]',
        'input[name="gallery_images[]"]',
    ]:
        if await page.locator(selector).count() != 1:
            return None
    ownership = page.get_by_label("A company I work for or myself owns this product", exact=True)
    if await ownership.count() != 1:
        return None
    await final.evaluate("e=>e.setAttribute('data-backlink-final','hackstack')")
    return {
        "domain": "thehackstack.com",
        "submit_url": page.url,
        "fields": {
            "Product / App Name": 'input[name="name"]',
            "Website URL": 'input[name="url"]',
            "Short Title": 'textarea[name="tagline"]',
            "Long Description": ".note-editable",
        },
        "required_fields": ["Product / App Name", "Website URL", "Long Description"],
        "rich_text_editor": "hackstack",
        "image_selector": 'input[name="image"]',
        "image_asset": str(pack["screenshots"][0].relative_to(pack["root"])),
        "logo_selector": 'input[name="logo"]',
        "screenshots_selector": 'input[name="gallery_images[]"]',
        "submitted_controls": [
            'textarea[name="description"]',
            "#ownership_not_owner",
            "#ownership_owner",
        ],
        "authenticated_selector": '[data-backlink-session="owner"]',
        "free_verified": True,
        "reciprocal_required": False,
        "qualification": "QUALIFIED_B",
        "final_action_verified": True,
        "final_submit_selector": '[data-backlink-final="hackstack"]',
        "final_submit_text": "Submit Product",
        "automatic_submit_allowed": False,
    }


async def fill_form(page, pack):
    # Expanded wording uses only the pack's Long Description, audience, category and pricing facts.
    if pack["fields"]["Product / App Name"] != "WYRPlay" or pack["fields"]["Website URL"] != TARGET:
        raise ValueError("HACKSTACK_PROJECT_IDENTITY_MISMATCH")
    if not 250 <= len(DESCRIPTION.split()) <= 500:
        raise ValueError("HACKSTACK_DESCRIPTION_WORD_LIMIT")
    validate_payload(DESCRIPTION)
    await page.locator('input[name="name"]').fill(pack["fields"]["Product / App Name"])
    await page.locator('input[name="url"]').fill(TARGET)
    await page.locator('textarea[name="tagline"]').fill(pack["fields"]["Short Title"])
    editor = page.locator(".note-editable")
    await editor.fill(DESCRIPTION)
    # Summernote synchronizes on a real keyboard editing event, not the fill input event.
    await editor.press("End")
    await editor.press("Space")
    await editor.press("Backspace")
    # Summernote's actual editing widget must synchronize its hidden submitted textarea.
    submitted = await page.locator('textarea[name="description"]').input_value()
    if "WYRPlay" not in submitted or len(submitted.split()) < 250:
        raise ValueError("EDITOR_SUBMITTED_DESCRIPTION_UNCONFIRMED")
    await page.locator('input[name="image"]').set_input_files(str(pack["screenshots"][0]))
    await page.locator('input[name="logo"]').set_input_files(str(pack["logo_png"]))
    await page.locator('input[name="gallery_images[]"]').set_input_files([str(p) for p in pack["screenshots"]])
    # The observed non-AI Community category matches the approved social game and community voting facts.
    await page.get_by_label("Community", exact=True).check()
    await page.get_by_label("A company I work for or myself owns this product", exact=True).check()
    return {"logo": True, "screenshots": len(pack["screenshots"])}
