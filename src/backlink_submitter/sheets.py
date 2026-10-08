"""Official ledger only. Real preflight uses read-only credentials scopes."""

import json
import os
from collections import Counter
from pathlib import Path

from .contracts import PROJECT, SHEET_ID, TARGET, now, safe_artifact, validate_dispatch_metadata, validate_outcome


def service(*, writable=False):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    path = Path(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json")
    ).expanduser()
    scope = "https://www.googleapis.com/auth/spreadsheets" + ("" if writable else ".readonly")
    credentials = service_account.Credentials.from_service_account_file(path, scopes=[scope])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def read_range(api, address):
    return api.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=address).execute().get("values", [])


def full_row(api, row):
    values = read_range(api, f"外链管理!A{row}:J{row}")
    if len(values) != 1 or len(values[0]) > 10:
        raise ValueError("Missing/ambiguous execution row")
    return [str(v) for v in values[0]] + [""] * (10 - len(values[0]))


def write_outcome(
    api, row, backlink_id, result, *, reason, summary, attempt_increment=0, expected_prior=None, attempt_receipt=None
):
    if row < 2 or not backlink_id or type(attempt_increment) is not int or attempt_increment not in {0, 1}:
        raise ValueError("Invalid row/key/attempt increment")
    validate_outcome(result)
    safe_artifact({"reason": reason, "summary": summary})
    prior = full_row(api, row)
    if prior[:2] != [PROJECT, backlink_id] or (expected_prior is not None and prior != expected_prior):
        raise ValueError("Fresh joint key/prior snapshot mismatch; write refused")
    if attempt_increment:
        if attempt_receipt is None:
            raise ValueError("Attempt +1 requires persisted single-use True Submit receipt")
        receipt_path = Path(attempt_receipt)
        receipt = json.loads(receipt_path.read_text())
        if (
            receipt.get("project_id"),
            receipt.get("backlink_id"),
            receipt.get("prior_attempts"),
            receipt.get("attempt_increment"),
            receipt.get("dispatch_confirmed") is True,
        ) != (PROJECT, backlink_id, prior[4], 1, True):
            raise ValueError("True Submit receipt/key/prior attempt mismatch")
        validate_dispatch_metadata(receipt.get("dispatch"))
        safe_artifact(receipt)
        # Reserving the receipt before API mutation prevents retry after an ambiguous write/readback.
        try:
            with receipt_path.with_suffix(".sheet-intent").open("x") as stream:
                stream.write(f"{PROJECT} | {backlink_id} | row {row}")
        except FileExistsError:
            raise ValueError("Attempt receipt already used; no automatic re-increment") from None
    # Blank remains blank during any inspection/non-final action.
    attempts = str(int(prior[4] or "0") + 1) if attempt_increment else prior[4]
    values = [result["status"], attempts, now(), TARGET, result.get("result_url", ""), reason, summary]
    expected = prior[:3] + values
    api.spreadsheets().values().update(
        spreadsheetId=SHEET_ID, range=f"外链管理!D{row}:J{row}", valueInputOption="RAW", body={"values": [values]}
    ).execute()
    if full_row(api, row) != expected:
        raise ValueError("Sheet full A:J readback failed; no automatic retry")
    return expected


def read_ledger(api):
    info = api.spreadsheets().get(spreadsheetId=SHEET_ID, fields="spreadsheetId,sheets.properties.title").execute()
    if info["spreadsheetId"] != SHEET_ID:
        raise ValueError("Spreadsheet ID mismatch")
    tabs = {sheet["properties"]["title"] for sheet in info["sheets"]}
    if not {"外链总表", "外链管理", "黑名单"} <= tabs:
        raise ValueError("Required official tabs missing")
    execution = read_range(api, "外链管理!A:J")
    master = read_range(api, "外链总表!A:R")
    blacklist = read_range(api, "黑名单!A:R")
    rows = [r + [""] * (10 - len(r)) for r in execution[1:] if r and r[0] == PROJECT]
    keys = [r[1] for r in rows]
    if len(set(keys)) != len(keys) or any(not key for key in keys):
        raise ValueError("Duplicate/missing WYRPlay composite key")
    counts = dict(Counter(r[3] or "unknown" for r in rows))
    if len(rows) != sum(counts.values()):
        raise ValueError("Ledger coverage mismatch")
    return {
        "spreadsheet_id": SHEET_ID,
        "read_at": now(),
        "project_rows": len(rows),
        "states": counts,
        "master_rows": max(0, len(master) - 1),
        "blacklist_rows": max(0, len(blacklist) - 1),
        "joint_keys_unique": True,
        "writes": 0,
        "submit": 0,
    }


def is_blacklisted(api, backlink_id, domain):
    rows = read_range(api, "黑名单!A:B")
    if not rows or rows[0][:2] != ["外链ID", "平台域名"]:
        raise ValueError("Blacklist header not recognized; fail closed")
    domain = domain.lower().removeprefix("www.")
    return any(
        row and (row[0] == backlink_id or (len(row) > 1 and row[1].lower().removeprefix("www.") == domain))
        for row in rows[1:]
    )


def read_candidate_tables(api):
    info = api.spreadsheets().get(spreadsheetId=SHEET_ID, fields="spreadsheetId,sheets.properties.title").execute()
    if info["spreadsheetId"] != SHEET_ID:
        raise ValueError("Official spreadsheet identity mismatch")
    return {
        key: read_range(api, tab + "!A:" + end)
        for key, tab, end in [("master", "外链总表", "R"), ("blacklist", "黑名单", "R"), ("execution", "外链管理", "J")]
    }


def append_global_blacklist(api, candidate, finding):
    """Positive platform evidence only; no project row deletion or whitelist inversion."""
    from .batch import GLOBAL_REASONS, MASTER_HEADER, official_url

    if finding.get("outcome") != "GLOBAL_BLACKLIST" or finding.get("reason") not in GLOBAL_REASONS:
        raise ValueError("Project mismatch/unknown is not global blacklist evidence")
    if (
        not finding.get("marker")
        or not finding.get("checked_at")
        or not official_url(finding.get("source_url", ""), candidate["domain"])
    ):
        raise ValueError("Global blacklist requires verified positive provenance")
    safe_artifact(finding)
    prior = full_row(api, candidate["row"])
    if prior[:2] != [PROJECT, candidate["backlink_id"]] or prior[3] not in {"", "待提交"} or prior[4] not in {"", "0"}:
        raise ValueError("Joint key/state changed before blacklist write")
    rows = read_range(api, "黑名单!A:R")
    if not rows or rows[0] != MASTER_HEADER:
        raise ValueError("Global blacklist header mismatch")
    if any(
        r
        and (
            r[0] == candidate["backlink_id"]
            or len(r) > 1
            and r[1].removeprefix("www.") == candidate["domain"].removeprefix("www.")
        )
        for r in rows[1:]
    ):
        return None
    values = [""] * 18
    values[:7] = [
        candidate["backlink_id"],
        candidate["domain"],
        candidate["submit_url"],
        "backlink-submitter verified qualification",
        now(),
        "已排除",
        finding["reason"],
    ]
    values[12:16] = [
        finding["checked_at"],
        finding["source_url"] + " | " + finding["marker"],
        "已排除",
        finding["reason"],
    ]
    result = (
        api.spreadsheets()
        .values()
        .append(
            spreadsheetId=SHEET_ID,
            range="黑名单!A:R",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        )
        .execute()
    )
    address = result["updates"]["updatedRange"]
    import re

    if not re.fullmatch(r"'?黑名单'?!A\d+:R\d+", address):
        raise ValueError("Unexpected blacklist write range; no retry")
    actual = read_range(api, address)
    if len(actual) != 1 or actual[0] + [""] * (18 - len(actual[0])) != values:
        raise ValueError("Global blacklist full A:R readback failed; no retry")
    if full_row(api, candidate["row"]) != prior:
        raise ValueError("Project row changed during blacklist append; manual review")
    return address
