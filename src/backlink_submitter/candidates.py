"""Positive master facts select browser work; Chinese actions do not manufacture proof."""

import re
from urllib.parse import urlparse

# Only channel-bearing path segments. Login, pricing, homepage and generic articles are not entries.
ENTRY_PATH = re.compile(
    r"(?:^|/)(?:submit(?:[-_](?:a[-_])?(?:product|startup|tool|website|site|ai|post|article|content|story|guest[-_]posts?))?"
    r"|add[-_](?:your[-_]|a[-_])?(?:product|startup|tool|website|site|listing)"
    r"|write[-_]for[-_]us|contribute|guest[-_]post(?:s)?|publish|publishing|community|forum)(?:/|$)",
    re.I,
)
PLATFORM_TYPES = {
    "产品目录",
    "Startup目录",
    "软件目录",
    "工具目录",
    "游戏目录",
    "网站目录",
    "通用目录",
    "AI工具目录",
    "MCP目录",
    "AI开发资源目录",
    "AI Agent目录",
    "工作流目录",
    "RSS目录",
    "内容投稿",
    "Guest post",
    "内容发布平台",
    "社区",
    "论坛",
    "友情链接目录",
    "PRODUCT_DIRECTORY",
    "STARTUP_DIRECTORY",
    "SOFTWARE_DIRECTORY",
    "TOOL_DIRECTORY",
    "GAME_DIRECTORY",
    "GENERAL_DIRECTORY",
    "CONTENT_SUBMISSION",
    "GUEST_POST",
    "BLOG_PUBLISHING",
    "COMMUNITY_PUBLISHING",
    "RECIPROCAL_LINK",
}
CHANNEL_TEXT = re.compile(
    r"\b(?:submit (?:your |a |an )?(?:product|startup|tool|website|site)|list your (?:product|startup|tool|website)"
    r"|add (?:your |a |my )?(?:product|startup|tool|website)|write for us|contribute|guest post"
    r"|publish (?:your |a )?(?:article|post|story)|create (?:a |your )?(?:post|blog))\b"
    r"|提交(?:工具|网站|产品|应用)|申请收录|网站收录|投稿|发布文章|发布产品|提交收录|免费收录",
    re.I,
)
REASONS = {
    "HUMAN_VERIFICATION_REQUIRED": "需要人机验证",
    "CAPTCHA": "需要人机验证",
    "OWNER_LOGIN_REQUIRED": "需要登录；请在专用窗口完成平台账户验证",
    "OWNER_INPUT_REQUIRED": "需要 Owner 确认真实字段",
    "UNMAPPED_REQUIRED_FIELDS": "需要确认表单必填字段",
    "ADAPTER_REVIEW_REQUIRED": "已有发布渠道记录，需要人工核验投稿方式或表单；自动填写条件未确认",
    "FINAL_ACTION_UNVERIFIED": "存在发布渠道，最终提交按钮需要人工确认",
    "FINAL_SELECTOR_UNVERIFIED": "存在发布渠道，最终提交按钮需要人工确认",
    "DISPATCH_MATCHER_UNVERIFIED": "表单存在，但自动提交请求无法安全确认",
    "OFFICIAL_SUBMIT_URL_UNCONFIRMED": "已有发布渠道记录，需要人工核验当前官方入口",
    "HTTP_UNAVAILABLE_NOT_PERMANENT_PROOF": "官网当前访问失败；稍后重试，不作永久淘汰",
    "OFFICIAL_PAGE_UNAVAILABLE": "官网当前无法打开或访问超时；稍后重试",
    "WORKER_TIMEOUT": "本站核验超时，浏览器已回收；稍后重试",
    "WORKER_CRASH_OR_INVALID_RESULT": "本站核验异常，浏览器已回收；稍后重试",
    "HUMAN_WAIT_TIMEOUT": "人工等待已超时，保持去人工，可稍后继续",
    "OWNER_PASSWORD_REQUIRED": "需要 Owner 输入密码",
    "OWNER_2FA_REQUIRED": "需要 Owner 完成短信或 Authenticator 双重验证",
    "OWNER_DEVICE_CONFIRMATION": "需要 Owner 确认登录设备",
    "OWNER_RISK_CONFIRMATION": "需要 Owner 完成风险确认",
    "HUMAN_WINDOW_CLOSED": "人工窗口已关闭，仍需单站重新核验",
    "TAXONOMY_UNCONFIRMED": "需要 Owner 确认与本项目相符的实际表单分类",
    "UPLOAD_REQUIREMENTS_UNCONFIRMED": "需要人工核验实际上传格式及尺寸限制",
    "QUALIFICATION_FREE_OR_LOGIN_UNVERIFIED": "需要人工核验免费条件、产品适配与登录要求",
    "FIELD_OR_TAXONOMY_UNVERIFIED": "真实发布入口已有记录，需要人工核验必填字段及分类",
    "SESSION_PROOF_UNVERIFIED": "需要人工确认平台登录状态",
    "AI_ONLY": "官方只接受 AI 产品，WYRPlay 不符合收录条件",
    "NO_PROJECT_PUBLISHING_CHANNEL": "官网用途与 WYRPlay 发布不匹配；已检查的官方页面无可用发布渠道",
}


def channel_basis(master):
    from .batch import official_url

    domain, url = master[1].lower().removeprefix("www."), master[2]
    if re.search(r"(?:wp-comments-post\.php|/(?:comments?|newsletter|subscribe)(?:/|$))", urlparse(url).path, re.I):
        return None  # Known comment/subscription endpoints are not product/content publishing.
    if official_url(url, domain) and ENTRY_PATH.search(urlparse(url).path):
        return {"kind": "official_entry", "source_url": url, "master_column": "提交入口"}
    if master[16].strip() in PLATFORM_TYPES:
        return {"kind": "platform_type", "platform_type": master[16], "master_column": "平台类型"}
    # Free=免费 alone (often copied from an HTTP response) proves nothing about a channel.
    if (
        master[12]
        and master[7] in {"是", "免费", "免费（付费可选）"}
        and CHANNEL_TEXT.search(master[13])
        and not re.search(
            r"未(?:验证|确认)|需要人工确认|未发现.*(?:渠道|入口)|unconfirmed|not verified|no submission channel",
            master[13],
            re.I,
        )
    ):
        # Generic legacy "found a channel / submitted successfully" lacks official traceability.
        # Do not use any project's old Submit result as platform qualification.
        sources = re.findall(r"https://[^\s<>；，。)]+", master[13])
        source = next(
            (
                u
                for u in sources
                if official_url(u, domain)
                and not re.search(r"wp-comments-post|/comments?(?:/|$)", urlparse(u).path, re.I)
            ),
            None,
        )
        if source:
            return {
                "kind": "verified_platform_fact",
                "source_url": source,
                "checked_at": master[12],
                "master_column": "平台备注",
            }
    return None


def observed_channel(source_url, body, links, fields):
    """Public DOM labels only; no values, cookies, account identity or guessed URLs."""
    # Bind the wording to an actual entry/CTA. News prose and SaaS feature names are not channels.
    entry_label = re.compile(
        r"^(?:contribute|guest post|write for us|投稿|提交|申请收录|发布文章|网站提交|友情链接申请)$", re.I
    )
    cta = re.compile(
        r"submit (?:your |a |an )?(?:product|startup|tool|website|site)\b"
        r"|list your (?:product|startup|tool|website)|add (?:your |a |my )?(?:product|startup|tool|website)"
        r"|write for us|(?:submit|send) (?:a |your )?guest post|publish your (?:article|post|story)"
        r"|create your (?:post|blog)|提交(?:工具|网站|产品|应用)|申请收录|提交收录|免费收录",
        re.I,
    )
    matches = [
        x
        for x in links
        if entry_label.fullmatch(x.get("text", "").strip())
        or cta.search(x.get("text", ""))
        or (
            ENTRY_PATH.search(urlparse(x["url"]).path)
            and not re.search(r"/(?:features|news|blog|articles)/", urlparse(x["url"]).path)
        )
    ]
    names = " ".join(
        " ".join(x.get("labels", [])) + " " + x.get("name", "") + " " + x.get("placeholder", "") for x in fields
    )
    product_form = bool(
        re.search(r"product name|startup name|tool name|产品名称|工具名称", names, re.I)
        and re.search(r"website|网址|url", names, re.I)
    )
    marker = cta.search(body)
    purpose = ""
    for pattern, label in [
        (r"\buniversity\b|\badmissions\b|学校|大学", "学校/研究机构"),
        (r"\b(?:breaking news|news coverage|news reporting|journalism)\b|新闻报道|新闻资讯", "新闻媒体"),
        (
            r"\b(?:our company|our business|our products|our services|motorcycle|automobile)\b|公司简介|企业简介",
            "企业/品牌官网",
        ),
        (r"\b(?:encyclopedia|reference library)\b|百科全书", "百科/参考站"),
    ]:
        if re.search(pattern, body, re.I):
            purpose = label
            break
    return {
        "confirmed": bool(matches or product_form or marker),
        "source_url": source_url,
        "channel_links": matches[:20],
        "product_form": product_form,
        "marker": marker.group(0) if marker else "",
        "site_purpose": purpose,
    }


def action_result(result, basis=None):
    from .automation import OWNER_REASONS

    r = dict(result)
    outcome, reason = r["outcome"], r["reason"]
    known = {
        "READY_TO_SUBMIT": "待提交",
        "SUCCESS": "成功",
        "PENDING": "审核中",
        "NOT_APPLICABLE": "不适用",
        "TEMPORARILY_UNAVAILABLE": "暂时不可用",
        "GLOBAL_BLACKLIST": "全局黑名单",
    }
    if outcome in known:
        status = known[outcome]
    elif reason in {"WORKER_TIMEOUT", "WORKER_CRASH_OR_INVALID_RESULT"}:
        status = "暂时不可用"
    elif (
        reason in OWNER_REASONS
        or reason
        in {"CAPTCHA", "OWNER_INPUT_REQUIRED", "RECIPROCAL_REQUIRED", "HUMAN_WAIT_TIMEOUT", "HUMAN_WINDOW_CLOSED"}
        or (
            outcome == "OWNER_INPUT_REQUIRED"
            and reason
            not in {
                "UNMAPPED_REQUIRED_FIELDS",
                "TAXONOMY_UNCONFIRMED",
                "UPLOAD_REQUIREMENTS_UNCONFIRMED",
                "REQUIRED_FACT_OR_CONSTRAINT_UNCONFIRMED",
            }
        )
    ):
        status = "去人工"
    elif reason == "HUMAN_VERIFICATION_REQUIRED":
        status = "去人工"
    elif basis or r.get("channel_confirmed") or reason not in {"NO_POSITIVE_CHANNEL_FACT", "UNKNOWN_PLATFORM"}:
        status = "暂时不可用"
        r["automation_pending"] = True
    else:
        # Do not turn unexamined sites into rejection or an executable action.
        return dict(
            r, action_status=None, action_reason="发布渠道尚未核验，保留原记录，不进入自动队列", coverage="unknown"
        )
    detail = REASONS.get(reason, "已记录发布渠道；当前自动条件未完整确认，需要人工核验")
    if (
        status == "去人工"
        and basis
        and re.search(
            r"/(?:write-for-us|submit-a-guest-post|submit-guest-post)(?:/|$)",
            urlparse(basis.get("source_url", "")).path,
        )
        and outcome not in {"HUMAN_VERIFICATION_REQUIRED", "OWNER_INPUT_REQUIRED"}
    ):
        detail = "需要人工准备符合投稿规范的原创文章，并确认编辑收稿方式；内容发布另需 Owner 授权"
    if status == "暂时不可用" and r.get("automation_pending"):
        detail = "自动核验尚未完成，保留系统继续处理：" + REASONS.get(reason, "入口、表单或认证证据待系统核验")
    if status == "待提交":
        detail = "平台、资料、最终动作和提交请求均已核验；执行仍需 Owner 授权"
    if status in {"成功", "审核中"}:
        detail = "本次真实提交证据已验证，禁止重复提交"
    if status == "全局黑名单":
        detail = "已确认全局排除依据；保留平台级证据，不进入执行队列"
    if r.get("missing_fields") or r.get("missing_field"):
        detail += "：" + "、".join(r.get("missing_fields") or [r["missing_field"]])
    return dict(
        r,
        action_status=status,
        action_reason=detail,
        coverage="approved"
        if status in {"待提交", "成功", "审核中"}
        else "confirmed_reject"
        if status in {"全局黑名单", "不适用"}
        else "deferred",
    )
