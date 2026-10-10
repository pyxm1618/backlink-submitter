"""Small WYRPlay boundaries; no historical engine, fallback project or OAuth client."""

import asyncio
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import getaddresses
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT = "wyrplay"
TARGET = "https://www.wyrplay.com/"
CONTACT = "support@wyrplay.com"
SHEET_ID = "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"
STATES = {
    "",
    "待提交",
    "需人工核查",
    "历史未验证",
    "审核中",
    "成功",
    "被拒绝",
    "不适用",
    "提交失败",
    "去人工",
    "暂时不可用",
}
DENY = (
    "quick i ching",
    "quick-iching",
    "quickiching",
    "i ching",
    "book of changes",
    "divination",
    "fortune telling",
    "mei hua",
    "yarrow",
    "three-coin",
    "tierlistbase",
)
RECEIPTS = (
    "submission received",
    "thank you for submitting",
    "pending review",
    "awaiting approval",
    "listing submitted",
    "submitted for review",
    "successfully submitted",
    "submitted successfully",
    "submission successful",
    "pending moderation",
    "awaiting moderation",
    "queued for review",
    "under review",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_project(project_id):
    if project_id != PROJECT:
        raise ValueError("Unknown project; no fallback")


def validate_payload(payload):
    text = json.dumps(payload, ensure_ascii=False).casefold()
    if any(term in text for term in DENY):
        raise ValueError("配置污染 / 需人工核查: abort without automatic correction")


def load_project(project_id, root):
    validate_project(project_id)
    root = Path(root).resolve()
    config = json.loads((root / "project.json").read_text())
    if (
        config.get("project_id"),
        config.get("canonical_url"),
        config.get("public_contact_email"),
        config.get("spreadsheet_id"),
        config.get("manifest_version"),
    ) != (PROJECT, TARGET, CONTACT, SHEET_ID, "3.0-final"):
        raise ValueError("Project config identity/ledger/version mismatch")
    manifest = json.loads((root / "submission_manifest.json").read_text())
    identity = manifest["identity"]
    if (
        manifest["schema_version"] != "3.0-final"
        or identity["project_id"] != PROJECT
        or identity["brand_name"] != "WYRPlay"
        or identity["canonical_url"] != TARGET
        or identity["public_contact_email"] != CONTACT
        or identity["ai_product"] is not False
        or manifest["project_guard"]["project_id"] != PROJECT
        or manifest["automation_ledger"]["spreadsheet_id"] != SHEET_ID
    ):
        raise ValueError("WYRPlay pack identity/version/ledger mismatch")
    verified = set()
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        digest, relative = line.split(maxsplit=1)
        asset = (root / relative.lstrip("*")).resolve()
        if not asset.is_relative_to(root) or hashlib.sha256(asset.read_bytes()).hexdigest() != digest:
            raise ValueError("Pack checksum mismatch")
        verified.add(asset)
    assets = manifest["assets"]
    required = [
        "submission_manifest.json",
        "submission_fields.csv",
        assets["logo_png"],
        assets["logo_svg"],
        *assets["screenshots"],
    ]
    if not all((root / path).resolve() in verified for path in required) or len(assets["screenshots"]) != 5:
        raise ValueError("Required pack assets not checksummed")
    with (root / "submission_fields.csv").open(encoding="utf-8-sig", newline="") as stream:
        fields = {row["Field"]: row["Default Value"] for row in csv.DictReader(stream)}
    if (fields["Product / App Name"], fields["Website URL"], fields["Public Contact Email"]) != (
        "WYRPlay",
        TARGET,
        CONTACT,
    ):
        raise ValueError("CSV/manifest mismatch")
    validate_payload(fields)
    return {
        "root": root,
        "manifest": manifest,
        "fields": fields,
        "logo_png": root / assets["logo_png"],
        "logo_svg": root / assets["logo_svg"],
        "screenshots": [root / path for path in assets["screenshots"]],
    }


def field_value(pack, field, *, required, platform, why="", possible_values=None):
    value = pack["fields"].get(field, "")
    if value:
        return value
    # Supplements require explicit provenance; never infer Founder from Operator.
    supplement_path = pack["root"] / "confirmed_facts.json"
    if supplement_path.exists():
        fact = json.loads(supplement_path.read_text()).get(field)
        if fact and fact.get("source") and fact.get("owner_confirmed_at") and fact.get("value"):
            validate_payload(fact["value"])
            return fact["value"]
    if not required:
        return ""
    return {
        "code": "OWNER_INPUT_REQUIRED",
        "field": field,
        "platform": platform,
        "why_required": why,
        "possible_values": possible_values or [],
        "source": "Pack/confirmed facts contain no verified value",
        "next": "Check official project sources; obtain Owner confirmation; record provenance in confirmed_facts.json",
    }


def composed_value(pack, spec):
    """Only the two authoritative identity fields, in order; no template language."""
    if spec.get("fields") != ["Product / App Name", "Website URL"] or spec.get("separator") not in {"\n", " - "}:
        raise ValueError("Unverified composed identity specification")
    values = [pack["fields"].get(field) for field in spec["fields"]]
    validate_payload(values)
    if values != ["WYRPlay", TARGET]:
        raise ValueError("Composed identity differs from official project")
    return spec["separator"].join(values)


def identity_mapped(adapter, pack):
    compositions = adapter.get("composed_fields", {})
    if compositions:
        if len(compositions) != 1:
            raise ValueError("Only one composed identity field is supported")
        spec = next(iter(compositions.values()))
        composed_value(pack, spec)
        if not spec.get("selector") or not spec.get("required"):
            raise ValueError("Composed identity mapping must be explicit and required")
        if any(field in adapter.get("fields", {}) for field in spec["fields"]):
            raise ValueError("Duplicate separate/composed identity mappings")
        return True
    return all(field in adapter.get("fields", {}) for field in ["Product / App Name", "Website URL"])


def select_description(pack, limit):
    choices = [
        pack["manifest"]["copy"][key]
        for key in (
            "description_long_498_chars",
            "description_medium_247_chars",
            "description_compact_155_chars",
            "description_short_96_chars",
        )
    ]
    for value in choices:
        if len(value) <= limit:
            return value
    raise ValueError("OWNER_INPUT_REQUIRED: no approved description fits; do not truncate or invent")


def fitting_field_value(pack, field, value, limit):
    if not isinstance(limit, int) or limit <= 0 or not isinstance(value, str) or len(value) <= limit:
        return value
    if "Description" in field:
        return select_description(pack, limit)
    if field == "One-line Pitch / Tagline" and len(pack["fields"]["Short Title"]) <= limit:
        return pack["fields"]["Short Title"]
    raise ValueError("APPROVED_TEXT_DOES_NOT_FIT")


def safe_artifact(value):
    """Fail before persistence, not after leaking. Bodies/cookies/auth data are never artifacts."""
    if isinstance(value, MemorySecret):
        raise ValueError("Secret cannot be persisted")
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(
                r"password|token|secret|cookie|authorization|api[_-]?key|^otp$|^body$|^session$", str(key), re.I
            ):
                raise ValueError("Secret/body field cannot be persisted")
            safe_artifact(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            safe_artifact(item)
    elif isinstance(value, str):
        if re.search(
            r"(?:access_token|id_token|refresh_token|client_secret|api[_-]?key|password|otp|verification code|magic link)\s*(?:[=:]|is\b)|(?:[?&](?:code|token|state)=)|\bbearer\s+[a-z0-9._-]+",
            value,
            re.I,
        ):
            raise ValueError("Credential/verification content cannot be persisted")


def save_evidence(path, evidence):
    safe_artifact(evidence)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        temporary.chmod(0o600)
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)
    return path


def validate_dispatch_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) != {"method", "host", "path"}:
        raise ValueError("Only safe dispatch method/host/path metadata is allowed")
    if (
        metadata["method"] not in {"POST", "PUT", "PATCH"}
        or not isinstance(metadata["host"], str)
        or not metadata["host"]
        or urlparse("https://" + metadata["host"]).hostname != metadata["host"]
        or not isinstance(metadata["path"], str)
        or not metadata["path"].startswith("/")
        or urlparse(metadata["path"]).query
        or urlparse(metadata["path"]).fragment
    ):
        raise ValueError("Invalid submission dispatch method/host/path")
    safe_artifact(metadata)


async def submit_once(
    journal,
    *,
    payload,
    click,
    project_id,
    prior_status,
    final_action,
    qualified,
    blacklisted,
    human_verification,
    missing_required,
    backlink_id=None,
    prior_attempts="",
    page=None,
    submission_request=None,
    dispatch_timeout_ms=30000,
    before_submit=None,
):
    validate_project(project_id)
    validate_payload(payload)
    if human_verification:
        raise ValueError("HUMAN_VERIFICATION_REQUIRED")
    if missing_required:
        raise ValueError("OWNER_INPUT_REQUIRED: mandatory facts missing")
    if blacklisted or not qualified or prior_status != "待提交":
        raise ValueError("Submit blocked by blacklist, qualification or existing status")
    if not final_action:
        return 0
    if (payload.get("name"), payload.get("url"), payload.get("email"), payload.get("ai_product")) != (
        "WYRPlay",
        TARGET,
        CONTACT,
        False,
    ):
        raise ValueError("Outgoing WYRPlay identity/AI mismatch")
    matcher = None
    if submission_request is not None:
        if submission_request.get("verified") is not True:
            raise ValueError("Submission request matcher must be adapter-verified")
        matcher = {key: submission_request.get(key) for key in ("method", "host", "path")}
        validate_dispatch_metadata(matcher)
    if type(dispatch_timeout_ms) is not int or not 0 < dispatch_timeout_ms <= 30000:
        raise ValueError("Dispatch observation timeout must be within 30 seconds")
    path = Path(journal)
    path.parent.mkdir(parents=True, exist_ok=True)
    intent = {
        "project_id": PROJECT,
        "backlink_id": backlink_id,
        "prior_attempts": prior_attempts,
        "state": "SUBMIT_DISPATCH_UNCONFIRMED",
        "started_at": now(),
        "attempt_increment": 0,
        "dispatch_confirmed": False,
        "dispatch": None,
        "before_submit": before_submit,
    }
    # Atomic O_EXCL across processes/restarts. Caller uses the same per-key path for every run.
    try:
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            json.dump(intent, stream)
    except FileExistsError:
        raise ValueError("Existing submit intent; no automatic duplicate/retry") from None
    observed = asyncio.Event()
    native_action = None
    if page is not None and matcher is None:
        forms = await page.locator("form").evaluate_all(
            "(es,identity)=>es.filter(f=>[...f.elements].some(e=>e.value===identity[0])&&[...f.elements].some(e=>e.value===identity[1])&&f.method.toUpperCase()==='POST').map(f=>f.action)",
            ["WYRPlay", TARGET],
        )
        if len(forms) == 1:
            parsed = urlparse(forms[0])
            if parsed.scheme == "https" and (parsed.hostname or "").removeprefix("www.") == (
                urlparse(page.url).hostname or ""
            ).removeprefix("www."):
                native_action = {"method": "POST", "host": parsed.hostname, "path": parsed.path}
    submission_host = (
        (urlparse(page.url).hostname or "").removeprefix("www.") if page is not None and matcher is None else ""
    )

    def observe(request):
        parsed = urlparse(request.url)
        metadata = {"method": request.method, "host": parsed.hostname, "path": parsed.path}
        if not observed.is_set() and parsed.scheme in {"https", "http"} and metadata in [matcher, native_action]:
            # Never read headers, body, cookies or query parameters into the receipt.
            intent.update(
                state="SUBMIT_RESULT_UNCONFIRMED", attempt_increment=1, dispatch_confirmed=True, dispatch=metadata
            )
            save_evidence(path, intent)
            observed.set()

    def observe_response(response):
        request = response.request
        parsed = urlparse(request.url)
        host = submission_host
        if (
            request.method in {"POST", "PUT", "PATCH"}
            and ((parsed.hostname or "").removeprefix("www.") == host or (parsed.hostname or "").endswith("." + host))
            and not re.search(r"analytics|telemetry|beacon|collect|tracking|metrics", parsed.path, re.I)
            and not observed.is_set()
        ):
            # Multipart uploads can contain binary bytes. Inspect identity only in memory.
            from urllib.parse import unquote_to_bytes

            decoded = unquote_to_bytes(request.post_data_buffer or b"").lower()
            if b"wyrplay" not in decoded or b"wyrplay.com" not in decoded:
                return
            metadata = {"method": request.method, "host": parsed.hostname, "path": parsed.path}
            validate_dispatch_metadata(metadata)
            intent.update(
                state="SUBMIT_RESULT_UNCONFIRMED", attempt_increment=1, dispatch_confirmed=True, dispatch=metadata
            )
            save_evidence(path, intent)
            observed.set()

    listening = page is not None
    if listening:
        page.on("request", observe)
        if matcher is None:
            page.on("response", observe_response)
    try:
        try:
            await click()
        except Exception:
            # UI failure does not erase a request already observed. Otherwise keep the intent and stop.
            if not observed.is_set():
                raise
        if listening and not observed.is_set():
            try:
                await asyncio.wait_for(observed.wait(), dispatch_timeout_ms / 1000)
            except TimeoutError:
                intent["state"] = (
                    "SUBMIT_RESULT_UNCONFIRMED" if intent["dispatch_confirmed"] else "SUBMIT_DISPATCH_UNCONFIRMED"
                )
    finally:
        if listening:
            page.remove_listener("request", observe)
            if matcher is None:
                page.remove_listener("response", observe_response)
    save_evidence(path, intent)
    return int(intent["dispatch_confirmed"])


def timestamp(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return parsed


def mail_matches(message, *, domain, recipient, started_at):
    received = timestamp(message["received_at"])
    addresses = getaddresses([message.get("sender", "")])
    recipients = [email.lower() for _, email in getaddresses([message.get("recipient", "")])]
    host = domain.lower().removeprefix("www.")
    sender_host = addresses[0][1].rpartition("@")[2].lower() if len(addresses) == 1 else ""
    return (
        received >= timestamp(started_at)
        and recipient.lower() in recipients
        and (sender_host == host or sender_host.endswith("." + host))
    )


@dataclass(repr=False)
class MemorySecret:
    value: str

    def __repr__(self):
        return "<MemorySecret redacted>"


def extract_otp(message, *, domain, recipient, requested_at, length):
    if type(length) is not int or not 4 <= length <= 8:
        raise ValueError("Exact page OTP length required")
    if not mail_matches(message, domain=domain, recipient=recipient, started_at=requested_at):
        return None
    subject, body = message.get("subject", ""), message.get("body", "")
    if not re.search(r"verification|verify|otp|confirmation|one.time", subject, re.I):
        return None
    text = re.sub(r"<[^>]+>", " ", subject + " " + body)
    codes = set(
        re.findall(
            r"(?:verification code|confirmation code|one.time (?:code|password)|otp|code)"
            r"(?:\s|[:=-]){0,15}(?:is\s+)?(\d{" + str(length) + r"})(?!\d)",
            text,
            re.I,
        )
    )
    return MemorySecret(next(iter(codes))) if len(codes) == 1 else None


def email_pending(message, *, domain, recipient, started_at):
    if not mail_matches(message, domain=domain, recipient=recipient, started_at=started_at):
        return None
    body = message.get("body", "")
    if not re.search(r"\bWYRPlay\b", body, re.I) or not re.search(r"submission|listing", body, re.I):
        return None
    if not re.search(r"received|review|approval|pending", body, re.I):
        return None
    subject = message.get("subject", "")
    safe_artifact({"subject": subject})
    return {
        "project_id": PROJECT,
        "evidence_code": "E2",
        "email_message_id": message["message_id"],
        "received_at": message["received_at"],
        "sender_domain": getaddresses([message["sender"]])[0][1].rpartition("@")[2].lower(),
        "subject": subject,
        "bound_to_submission": True,
    }


def tracking_pending(url, text, *, previous_url, submitted, domain):
    parsed = urlparse(url)
    if (
        not submitted
        or url == previous_url
        or parsed.scheme != "https"
        or parsed.hostname != domain
        or parsed.query
        or parsed.fragment
        or not re.search(r"\bWYRPlay\b", text, re.I)
        or not re.search(r"/(?:submission|status|launch)/[\w-]+|/products/wyrplay/pending$", parsed.path)
    ):
        return None
    return {"project_id": PROJECT, "evidence_code": "E3", "tracking_url": url, "bound_to_submission": True}


def classify(before, after, *, submitted, proof=None):
    result: dict[str, Any] = {
        "status": "需人工核查" if submitted else "待提交",
        "evidence_code": "",
        "result_url": "",
        "reason": "SUBMIT_RESULT_UNCONFIRMED" if submitted else "No True Submit",
        "project_id": PROJECT,
    }
    proof = proof or {}
    from .browser import listing_url_allowed

    if proof.get("project_id") == PROJECT:
        code = proof.get("evidence_code")
        valid_links = [
            link
            for link in proof.get("links", [])
            if isinstance(link, dict)
            and urlparse(link.get("href", "")).hostname in {"wyrplay.com", "www.wyrplay.com"}
            and urlparse(link.get("href", "")).scheme in {"http", "https"}
        ]
        if (
            code == "E4"
            and all(proof.get(k) for k in ["anonymous", "public_verified", "authentic_listing"])
            and valid_links
            and listing_url_allowed(proof.get("listing_url", ""))
            and re.search(r"\bWYRPlay\b", proof.get("title", ""), re.I)
            and not re.search(r"\b(dashboard|preview)\b", proof.get("title", ""), re.I)
        ):
            result.update(
                status="成功",
                evidence_code="E4",
                result_url=proof["listing_url"],
                proof=proof,
                reason="Anonymous public listing verified",
            )
            return result
        if submitted and code in {"E2", "E3"} and proof.get("bound_to_submission"):
            result.update(
                status="审核中",
                evidence_code=code,
                result_url=proof.get("tracking_url", "") if code == "E3" else "",
                proof=proof,
                reason="Bound submission receipt verified",
            )
            return result
    before, after = " ".join(before.casefold().split()), " ".join(after.casefold().split())
    for receipt in RECEIPTS:
        if submitted and receipt in after and receipt not in before:
            result.update(
                status="审核中",
                evidence_code="E1",
                reason="New post-submit page receipt verified",
                proof={
                    "project_id": PROJECT,
                    "evidence_code": "E1",
                    "bound_to_submission": True,
                    "dom_evidence": [receipt],
                },
            )
            break
    return result


def validate_outcome(result):
    status, code, url = result["status"], result.get("evidence_code", ""), result.get("result_url", "")
    if status not in STATES:
        raise ValueError("Unknown business state")
    proof = result.get("proof", {})
    if status in {"成功", "审核中"}:
        checked = classify("", "", submitted=True, proof=proof)
        if (
            code == "E1"
            and proof.get("project_id") == PROJECT
            and proof.get("bound_to_submission")
            and proof.get("dom_evidence")
        ):
            checked = classify("", " ".join(proof["dom_evidence"]), submitted=True)
        if (checked["status"], checked["evidence_code"], checked["result_url"]) != (status, code, url):
            raise ValueError("Status/result URL requires matching E1/E2/E3/E4 proof")
    elif url or code:
        raise ValueError("No result URL or E-code without genuine pending/live evidence")
    safe_artifact(result)
