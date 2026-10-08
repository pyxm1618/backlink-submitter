# backlink-submitter

WYRPlay 外链执行合同、正式资料包与可恢复运行说明。只支持 `wyrplay`；不是 BacklinkOS 的复制品。

当前：**FUNCTIONAL CANARY VERIFIED / CONTROLLED ROLLOUT NOT STARTED**。
WYRPlay × StartupFound 已验证一次真实 Submit、POST dispatch、Attempt=1、E4 和完整 Sheet A:J 回读。
生产安全元数据见 [Canary verification](docs/PRODUCTION_CANARY_VERIFICATION.json)。
一次 Canary 不授权 rollout；`automatic_submit_allowed` 保持 false。
本仓库的 fixture 测试不能替代生产 Canary。

## Start

需要 Python 3.11+、Google Chrome（Chromium 内核）；没有 Chrome 的环境先由 Owner 安装 Chrome。

```bash
git clone https://github.com/pyxm1618/backlink-submitter.git
cd backlink-submitter
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
.venv/bin/backlink-submitter preflight --project wyrplay
```

授权文件必须在仓库外。现有默认位置是 `~/.config/seo-sheets/service-account.json`，
也可用 `GOOGLE_APPLICATION_CREDENTIALS` 指定已有凭据文件。该服务账户需有正式 Sheet 访问权。
不要复制凭据进仓库或为此创建第二套 Gmail OAuth。

```bash
.venv/bin/backlink-submitter preflight --project wyrplay --read-sheet --browser-smoke
```

此命令仅 GET，Sheets scope 为 readonly；不填表、不登录、不点击、不写回。
浏览器 smoke 使用匿名 headless context，不触碰 Owner 的 Profile。

继续工作前读 [Runbook](docs/RUNBOOK.md)、[当前状态](docs/CURRENT_STATE.md)、
[Sheet 模型](docs/SHEET_MODEL.md)、[状态/证据](docs/STATUS_MODEL.md)。
[冷窗口测试](FRESH_WINDOW_TEST.md) 是无聊天历史恢复的最小流程。

## Implementation

`src/backlink_submitter/` 保持六个小模块：contracts（项目/证据/OTP/防重）、
browser、sheets、workflow（精确 adapter 填报和单站执行）、cli、包入口。
默认 CLI **没有提交命令**。`workflow.run_submission` 是受保护的单站库函数；
当前五个站点都没有获准启用自动最终 Submit。今后须 Owner 授权、重新核验资格及最终动作，
再保存经过现场验证的 adapter。禁止用猜测 selector 开启执行。

Gmail 由当前 AI 已连接 connector 读取 Profile/无副作用搜索，并转换为结构化 message，
交给 `extract_otp` / `email_pending`。账号登录邮箱与公开产品联系邮箱是不同语义字段，
recipient 必须是本次实际请求收件账号；不得默认替换。connector 不可用仅影响依赖邮件的站点。
无本地 OAuth 客户端、凭据刷新器或 magic-link 自动执行。

## No secrets / no parallel ledger

不提交密码、OAuth/API token、cookie、Profile、邮箱正文、私有截图或整个 Sheet 快照。
Runtime 在仓库外。正式业务账本始终是指定 Google Sheet；仓库快照仅用于解释历史状态。
资料包中的旧项目字符串仅存在于拒绝规则，不是旧项目配置或提交字段。
原 CSV 的 CRLF/BOM 用 .gitattributes 原样保留，确保 clone 后 checksum 不变。
