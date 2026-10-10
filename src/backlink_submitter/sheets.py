"""Official ledger only. Real preflight uses read-only credentials scopes."""

import json
import os
import re
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
    displayed_reason = human_reason(result["status"], reason)
    if displayed_reason != reason:
        from .contracts import save_evidence

        save_evidence(
            Path("~/.backlink-autofill/runtime/wyrplay/sheet-display-history").expanduser() / f"{now()}-{row}.json",
            {
                "project_id": PROJECT,
                "backlink_id": backlink_id,
                "row": row,
                "internal_reason": reason,
                "prior_note": prior[8],
            },
        )
    values = [result["status"], attempts, now(), TARGET, result.get("result_url", ""), displayed_reason, summary]
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


def human_reason(status, reason):
    """Render the current outcome without exposing internal engineering labels."""
    if status == "成功":
        return "已有成功记录：本轮未重新验证，保留原状态，禁止重复提交。"
    if status == "审核中":
        return "已提交：平台已受理，目前等待审核，禁止重复提交。"
    if status == "已排期":
        return "已有排期记录：公开发布结果尚待核实，禁止重复提交。"
    if status == "历史未验证":
        return "历史记录称已提交：当前结果尚未核实，禁止重复提交。"
    text = reason.casefold()
    if re.search(r"submit_result_unconfirmed|已提交待核实|真实.*post|已观察.*post", text):
        return "已提交待核实：最终业务请求已确认，但公开收录结果尚未核实，禁止重复提交。"
    if re.search(r"submit_dispatch_unconfirmed|最终点击|最终.*点击一次|final_action_result_unconfirmed", text):
        return "提交结果待核实：最终按钮已点击，但业务请求尚未确认，禁止重复提交。"
    # Earlier stages may contain superseded pricing/login findings; show the latest recorded finding.
    text = next((line.casefold() for line in reversed(reason.splitlines()) if line.strip()), "")
    if re.search(r"google_risk_verification", text):
        return "暂未提交：Google 登录触发安全验证，已停止登录尝试。"
    if re.search(r"reciprocal_required|换链|先做好本站链接|反链.*要求|要求.*反链", text):
        return "暂未提交：免费收录要求在 WYRPlay 放对方链接，本轮没有做换链。"
    if re.search(r"automated access.*not allowed|禁止自动访问|自动访问.*禁止", text):
        return "暂未提交：网站禁止自动访问，需要通过允许的人工渠道处理。"
    if status == "不适用" and re.search(
        r"\bai[- ]only\b|\bonly ai\b|只(?:收录|接受|面向).*?\bai\b|仅(?:收录|接受|面向).*?\bai\b", text
    ):
        return "不适用：这个平台只收录 AI 工具，WYRPlay 不符合要求。"
    if re.search(r"银行卡|信用卡|no.card trials|verify cards", text):
        return "暂未提交：免费试用要求银行卡验证，目前没有可执行的免费路径。"
    if re.search(r"payment_only|当前.*付费|收费|100元|paid.only|只.*付费|免费.*(?:满|停止)|79美元", text):
        return "暂未提交：当前没有已确认可用的免费提交入口，本轮不付费。"
    if re.search(r"human_verification|captcha|turnstile|人机验证|安全防护|cloudflare", text):
        return "暂未提交：网站要求完成人机验证。"
    if re.search(r"google_session_unavailable", text):
        return "暂未提交：专用浏览器没有已确认有效的 Google 登录状态，优先使用邮箱认证。"
    if re.search(r"signup not approved|准入|work emails", text):
        return "暂未提交：已完成登录，但平台没有批准该账号使用提交功能。"
    if re.search(r"password|密码|credential_unavailable", text):
        return "暂未提交：当前没有可用的平台登录凭据，需要先寻找邮箱免密码登录方式。"
    if re.search(r"login_required|oauth|需要.*登录|需登录|登录.*(?:未|失败|阻塞)|认证.*(?:未|失败|阻塞)", text):
        return "暂未提交：需要登录后才能看到完整提交表单，目前登录流程没有完成。"
    if re.search(r"worker_timeout|worker_crash|自动化未完成|核验异常|自动.*未完成", text):
        return "暂未提交：自动核验尚未完成，需要继续核对入口、表单和提交条件。"
    if re.search(r"无法打开|访问失败|超时|证书|temporarily_unavailable|连接故障", text):
        return "暂未提交：网站当前无法正常访问，稍后再核查。"
    if re.search(r"没有.*渠道|无.*渠道|no.*channel|不存在.*入口", text):
        return "暂未提交：目前未确认适用的发布渠道，需要继续核查官方入口。"
    if re.search(
        r"phase|manual_review|qualified_|adapter_|matcher|callback host|automation_pending|[a-z]{3,}_[a-z_]+", text
    ):
        return "暂未提交：当前发布条件尚未核实，需要继续核对官方入口和完整表单。"
    latest = next((line.strip() for line in reversed(reason.splitlines()) if line.strip()), "")
    return re.sub(r"^\[[^]]+\]\s*", "", latest)


def write_display(api, row, backlink_id, *, reason, expected_prior, status=None):
    """Authorized display correction only; preserve every business/evidence field."""
    from .contracts import save_evidence

    if row < 2 or expected_prior[:2] != [PROJECT, backlink_id] or full_row(api, row) != expected_prior:
        raise ValueError("Display correction joint key/prior mismatch")
    if re.search(r"Phase|MANUAL_REVIEW|QUALIFIED_|ADAPTER_|matcher|callback host|automation_pending", reason, re.I):
        raise ValueError("Internal engineering labels forbidden in Owner notes")
    if status is not None and (
        expected_prior[3] != "不适用" or expected_prior[4] not in {"", "0"} or expected_prior[7]
    ):
        raise ValueError("Display correction cannot change protected submission state")
    if status is not None and status not in {"去人工", "暂时不可用"}:
        raise ValueError("Unsupported display correction")
    expected = list(expected_prior)
    expected[8] = reason
    if status is not None:
        expected[3] = status
    save_evidence(
        Path("~/.backlink-autofill/runtime/wyrplay/sheet-display-history").expanduser() / f"{now()}-{row}.json",
        {"project_id": PROJECT, "backlink_id": backlink_id, "row": row, "before": expected_prior, "after": expected},
    )
    changes = [{"range": f"外链管理!I{row}", "values": [[reason]]}]
    if status is not None:
        changes.append({"range": f"外链管理!D{row}", "values": [[status]]})
    api.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": changes}
    ).execute()
    if full_row(api, row) != expected:
        raise ValueError("Display correction readback failed; no automatic retry")
    return expected


def write_display_batch(api, corrections):
    """Bounded exact-cell correction, with fresh joint keys and full-row readback."""
    from .contracts import save_evidence

    if not 1 <= len(corrections) <= 25 or len({c["row"] for c in corrections}) != len(corrections):
        raise ValueError("Display correction batch must contain 1-25 distinct rows")
    addresses = [f"外链管理!A{c['row']}:J{c['row']}" for c in corrections]
    values_api = api.spreadsheets().values()

    def snapshots():
        ranges = values_api.batchGet(spreadsheetId=SHEET_ID, ranges=addresses).execute()["valueRanges"]
        if len(ranges) != len(corrections):
            raise ValueError("Display correction snapshot coverage mismatch")
        rows = []
        for value in ranges:
            items = value.get("values", [])
            if len(items) != 1 or len(items[0]) > 10:
                raise ValueError("Missing/ambiguous display correction row")
            rows.append([str(v) for v in items[0]] + [""] * (10 - len(items[0])))
        return rows

    priors = snapshots()
    expected = []
    changes = []
    for correction, prior in zip(corrections, priors, strict=True):
        row = correction["row"]
        key = correction["backlink_id"]
        reason = correction["reason"]
        status = correction.get("status")
        if row < 2 or prior != correction["expected_prior"] or prior[:2] != [PROJECT, key]:
            raise ValueError("Display correction fresh joint key/prior mismatch")
        if re.search(r"Phase|MANUAL_REVIEW|QUALIFIED_|ADAPTER_|matcher|callback host|automation_pending", reason, re.I):
            raise ValueError("Internal engineering labels forbidden in Owner notes")
        if status is not None and (
            prior[3] != "不适用" or prior[4] not in {"", "0"} or prior[7] or status not in {"去人工", "暂时不可用"}
        ):
            raise ValueError("Protected/unsupported display state correction")
        after = list(prior)
        after[8] = reason
        if status is not None:
            after[3] = status
            changes.append({"range": f"外链管理!D{row}", "values": [[status]]})
        changes.append({"range": f"外链管理!I{row}", "values": [[reason]]})
        save_evidence(
            Path("~/.backlink-autofill/runtime/wyrplay/sheet-display-history").expanduser() / f"{now()}-{row}.json",
            {"project_id": PROJECT, "backlink_id": key, "row": row, "before": prior, "after": after},
        )
        expected.append(after)
    values_api.batchUpdate(spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": changes}).execute()
    if snapshots() != expected:
        raise ValueError("Display correction full-row readback failed; no automatic retry")
    return expected
