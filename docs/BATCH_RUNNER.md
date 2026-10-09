# WYRPlay batch runner

已完成当前授权十站实际尝试；结果见 LIVE_10_VERIFICATION.md。未开启下一批。Google Sheet 为唯一正式账本。

## 候选顺序与分流

读取正式外链总表 A:R、黑名单 A:R、外链管理 A:J，严格核对表头、平台键和 WYRPlay 联合键。
按外链管理实际行顺序推进 WYRPlay 现有记录；总表以平台键关联，只提供入口/类型/事实加速信息。
缺总表、缺渠道依据、旧“失效/排除”、旧人工/临时状态不会单独阻止 Discovery。
成功、审核中、历史未验证、非零 Attempt、persistent intent、已有结果/提交不确定证据和确认黑名单仍保护；
不合法键在输入边界保留 unknown，不能猜域名或转换为拒绝。Quick I Ching 的执行资料完全不参与。
`channel_basis` 仅提示，不再是硬门槛，也没有“688个”执行边界；正式工作队列是全部WYRPlay记录。
`--limit 10` 从未保护记录按正式执行表顺序取连续10项，不人工选择；本次仅十站。
入口缺失也从官网及观察到的官方导航开始，逐站有界核验，不猜 URL。
报告保留 approved/deferred/confirmed_reject/unknown，原总数始终等于所有显式状态之和。

## 两种模式

```bash
.venv/bin/backlink-submitter batch --project wyrplay --mode dry-run
.venv/bin/backlink-submitter batch --project wyrplay --mode dry-run --concurrency 4 --limit 20
```

DRY RUN 默认：只读 Sheet，不填字段/上传/点击/登录，不写 Sheet，不创建 Submit intent。
具备 adapter 的候选只读核验当前表单和最终动作；context 禁止 POST/PUT/PATCH/DELETE。
READY_TO_SUBMIT 表示资料、映射、session 与 final action 的只读门槛通过，不能替代 LIVE 填写后
对实际 DOM、必填/上传、身份、免费条件、黑名单和 intent 的再次检查，也不构成提交授权。

LIVE 必须是 Owner 明确批准的新运行，使用仓库外的单次授权文件：

```json
{
  "project_id": "wyrplay",
  "mode": "LIVE",
  "owner_confirmed": true,
  "expires_at": "<Owner 批准的 UTC ISO-8601 到期时间>",
  "backlink_ids": ["<Owner 批准的正式平台键>"]
}
```

上例仅说明格式，不是有效授权或真实平台数据。运行命令：

```bash
.venv/bin/backlink-submitter batch --project wyrplay --mode live --owner-approval /absolute/external/owner-approved-run.json
```

LIVE 授权在启动时以 `.used` 标记消耗，每个最终动作再次检查到期时间。
保持提交 adapter 的 `automatic_submit_allowed=false`；授权仅施加到内存副本。
已有成功 StartupFound 和历史 Attempt 行永远不因批量运行重投。

## 现场 Discovery 与首次 Submit

DRY RUN 保留只读诊断，不构成授权。LIVE 跟随观察到的同域入口与正常认证链接，在当前
context 读取并填写 label/name/placeholder/aria/fieldset/legend、普通条款与可满足的官方上传。
普通登录/OAuth、邮件验证、Next/Continue 属于自动步骤，技术未完成保留系统暂缓。
新账号确认密码页面可请求 host 内存凭据；已有主账号密码与 CAPTCHA/2FA 等仍为 Owner 边界。

第一次最终 Submit 不要求 verified matcher 或事前 handler endpoint 证明。现场确认 WYRPlay
真实值、必填、免费路径、联合键和授权后，写单次 intent 并监听实际 POST/PUT/PATCH。
只记录 method/host/path，不保存 body/token/password；无法确认派发时 Attempt 不增加且禁止再点。
已存在 adapter/matcher 保留为诊断和历史合同；LIVE 使用本次页面事实，既有成功永远不重投。

E1–E4 继续用于结果确认，普通价格、超时、404、未知或项目不相关均不能推出全局黑名单。
NOT_APPLICABLE 只影响 WYRPlay；全局淘汰必须有明确官方正面证据并精确回读。

## 资源与人工恢复

默认 2 个 worker，配置范围 1–4，同域任务永远最多 1。固定数量 consumer 和有界内存队列。
每站独立子进程、专用 profile；正常任务全部 headless。完成立即关闭 context，释放所有 pages。
每站 90 秒墙钟截止；context 关闭最多 10 秒。超时/崩溃回收该 worker 进程组，不删除锁，
不杀 Owner Chrome；失败站不自动重试。独立匿名 E4 context 也有 finally 关闭。
跨进程 batch-run 锁阻止多个运行同时占用 profile；Sheet 写者锁串行化正式写入。
仍不宣称 Sheets API 原子 CAS，发现并发变化立即停止。

遇到 CAPTCHA/Cloudflare/2FA/密码挑战：先关闭 context，再写安全恢复提示到仓库外
`~/.backlink-autofill/runtime/wyrplay/human-queue/KEY.json`。LIVE 非提交分流写“去人工”与中文具体原因，
Attempt 不变；DRY RUN 只保留现场提示，不改正式 Sheet。这些提示和运行审计文件不是平行账本。
不保存 cookie/token/邮箱正文/认证 URL/敏感页面。Profile 留在仓库外，不复制到 Git。

只有 Owner 明确启动单站人工处理时才打开 headed：

```bash
.venv/bin/backlink-submitter handoff --project wyrplay --backlink-id KEY --owner-human-action
```

仅打开已排入人工队列的指定站，使用该域专用 profile，最长 180 秒；最终提交 endpoint 被拦截。
Discovery hint 可保存实际观察到的同域恢复入口；resume 重新验证来源与联合键。
没有已验证 matcher 的 handoff 保守拦截全部写方法；若登录依赖写请求，也保持阻碍，
等待核验 final endpoint 后再使用原 handoff，不能借人工窗口探测 Submit。
Owner 正常完成登录/验证后关闭该专用窗口，不删除 SingletonLock，不绕过任何挑战。
随后恢复同一站并重新检查：

```bash
.venv/bin/backlink-submitter resume --project wyrplay --backlink-id KEY --mode dry-run
# 若以后另获 LIVE 单站授权，resume 可使用 --mode live --owner-approval 仓库外授权文件
```

resume 重新查联合键、黑名单、Attempt、intent 和官方入口，hint 不替代账本。
成功/审核中/历史未验证、非零 Attempt 或已有 intent 不能 resume Submit。

## Submit 与结果

批量 wrapper 调用现有 run_submission/submit_once/classify/write_outcome，不重写单站 engine。
Final click 不等于 Attempt；仅 verified method/host/path 的 dispatch receipt 可 +1，并以
single-use `.sheet-intent` 保证不重复计数。每次写入重新查 key/prior 并完整 A:J 回读，保留 I/J。
无 dispatch 或无结果证据均需人工核查，保留 intent，禁止再次点击。
崩溃恢复只核对持久 receipt；未消费的确定 dispatch 允许一次受保护 +1，无确定 dispatch不加。
已有 `.sheet-intent` 的不明确写入只报人工核查，不盲目重写。

结果包括 SUCCESS、PENDING、NOT_APPLICABLE、GLOBAL_BLACKLIST、HUMAN_VERIFICATION_REQUIRED、
OWNER_INPUT_REQUIRED、TEMPORARILY_UNAVAILABLE、READY_TO_SUBMIT 或现有 Sheet 状态/原因码。
只有 E1/E2/E3 -> 审核中，E4 -> 成功；已有状态的 dry 分类不伪装本轮新证据。
E1 沿用单站引擎，E3/E4 只取观察到的真实链接并使用既有 proof helpers；后续更新 increment=0。
E2 仍需已连接 Gmail connector 提供本次绑定的正式邮件，经 email_pending 验证；CLI 不引入
第二套 OAuth、邮件服务或假邮件 fallback，缺邮件证据明确不可用，不能猜成功。

## Matchbox 已核验模式

`askmatchbox.com` 的 `/founders` 使用唯一 `Request a listing →` 按钮展开 listing request。
展开阶段始终阻断 POST/PUT/PATCH/DELETE，不创建 submit intent、不计 Attempt。
`composed_fields` 仅支持按顺序组合正式 `Product / App Name` 与 `Website URL`，分隔符明确配置为换行；
不支持模板、自由文案、Founder/Funding 或其他字段。填写后和真实 Submit 前精确核对完整 identity。
无 taxonomy/upload 的该表单独立验证；其他平台仍走原 discovery/adapter 规则。
`Add my product` 仅在已核验 listing form 内接受。matcher 必须由现场 React onSubmit、
官方同组件 render 绑定、已审计 handler hash 和 `founder_listing` payload 同时证明。
复用 adapter 时在新 context 中重新展开、检查字段、免费条款与 handler；变化后停止。
adapter 的 `automatic_submit_allowed=false`，仍须独立 Owner LIVE 授权及全部既有提交合同。

## 自动认证与中文动作

只有实际 CAPTCHA/密码输入/短信或 Authenticator 2FA/设备/风险确认，以及真实缺失的业务事实或授权决定才去人工。
普通登录先复用每站persistent profile，跟随实际登录/Google入口，放行页面已绑定的auth-only请求；
真实Google流程可在初始context关闭后重试现有Owner专用profile，不导出cookie，不同时占用两个context。
Owner已打开/其他worker正使用专用profile时保持系统暂缓，不删锁、不杀Owner浏览器。
登录成功计数必须见到离开认证界面回到本平台；进入OAuth/点击按钮不等于完成登录。

认证网络保护按阶段执行：AUTH/VERIFICATION只放行DOM绑定的认证action及其认证字段，
观察到且redirect_uri绑定当前平台的Google流程才允许Google认证请求。
最终已验证业务endpoint持续阻断；无matcher也不能开放任意POST。
DISCOVERY/FINAL_SUBMIT在本轮只读模式阻断业务写请求。真实Final仍由原引擎、Owner独立授权控制。

Gmail仅用现有connector读接口：账户、收件人、官方发送域、发起时间、邮件语义、唯一OTP或同域magic link同时匹配。
验证码/链接仅在MemorySecret与浏览器内存中，不写Sheet/evidence/log，不建立新OAuth。
`ConnectedGmail`供能调用既有连接工具的hosting caller注入`discover(..., connector=...)`；
默认独立 worker 没有 Codex connector；`--mail-stdio` 已提供 hosting AI → 已连接工具 → stdin 内存回复传输。
本轮真实 profile/search 及 host→CLI 往返已验证；未注入/连接故障仍返回 GMAIL_CONNECTOR_UNAVAILABLE。
本轮没有真实 OTP/magic link 完成案例，不能用接口或 fixture 通过替代该验证。

Next/Continue/Review只在唯一可见控件时有界推进；授权 LIVE 的 FORM_STEP 放行同平台普通下一步请求。
这些标签不替代最终提交意图与单次点击保护；只读运行仍阻断写请求。
字段识别包含label/name/id/placeholder/aria及现场fieldset/legend/options元数据；Email星号标签可确定映射正式邮箱。
没有taxonomy控制时不强制taxonomy；存在时仍保留真实选项与非AI合同。
matcher增加CDP实际绑定submit监听器/React onSubmit及fetch/XHR正证据；无override的native action可接受，
无绑定的 bundle 字符串不构成 matcher；最终 Submit 采用当前授权与页面事实，真实首提监听派发。

技术未完成、无法证明selector/matcher、多步骤请求/认证绑定不明，不算Owner人工动作。
本轮用“暂时不可用 | 自动核验尚未完成，保留系统继续处理”明确区分系统暂缓与站点故障；
内部automation_pending与具体reason保留，不冒充不适用/黑名单，也不冒充READY。
原提交派发/结果不确定的需人工核查、安全intent及E1–E4合同不变，不能自动重投。

## 人工循环

```bash
.venv/bin/backlink-submitter human-loop --project wyrplay --owner-human-action --limit 5
```

正式Sheet去人工行先交headless链重新核验，旧“普通登录/复杂表单”不直接弹窗；
只有此次实际确认的Owner边界才打开该单站dedicated headed browser。
每5秒核验、最多10分钟、串行一窗口；超时/关闭释放context与worker。
窗口只允许页面证据已绑定的认证请求，已知最终业务endpoint先于DOM检查阻断，未知业务POST不放行。
Owner完成验证后关闭headed，现有headless链重新核验；READY才由原protected writer更新该行动状态，Attempt不变。
这不是Submit授权；当前十站已打开一个 ebool 人工窗口并正式回写；该窗口等候结束，新账号密码随后由 Owner 授权自动填入。
CAPTCHA厂商未被页面绑定的必要POST同样不会猜着开放；仍需在独立验证中证明 transport，不能声称所有挑战均可恢复。

## Host 已连接能力

`--mail-stdio` 使用当前执行 AI 已连接 Gmail。CLI 发出安全操作名/参数，host 调用已有工具并通过
无回显 stdin 回传；邮箱正文、OTP、magic link 与新账号凭据只驻留内存，不建立第二套 OAuth。
新账号凭据需要 Owner 已给出的明确值，系统不生成或猜测；普通已有登录不会套用新账号密码。
