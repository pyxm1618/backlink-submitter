# WYRPlay batch runner

本轮仅实现并验证能力；CONTROLLED ROLLOUT NOT STARTED。Google Sheet 仍为唯一正式账本。

## 候选顺序与分流

读取正式外链总表 A:R、黑名单 A:R、外链管理 A:J，严格核对表头、平台键和 WYRPlay 联合键。
按外链总表实际行顺序关联现有 WYRPlay 行；缺失总表事实的行在末尾保留 unknown，不自动建行。
重复键/不一致配置 fail closed。每次运行和正式写入都刷新 Sheet。

先跳过黑名单、成功/审核中/历史未验证/需人工核查/去人工/暂时不可用等已有状态、非零 Attempt、persistent intent。
历史总表“失效/已排除”只进入待复核，不能因旧 timeout 判永久失效或新增黑名单。
浏览器前必须有可追溯的正向渠道依据：总表的官方发布入口、明确目录/社区/内容发布类型，
或同时具备免费事实、验证时间与官方来源 URL 的平台渠道事实。首页、login/register、
“实测免费”本身、旧“自动提交成功”及无官方来源的笼统“发现投稿通道”均不够。
已知评论/订阅 endpoint 不作为发布渠道。该预筛只决定是否进入浏览器，不删原记录、不把未知改为拒绝。
只读取 WYRPlay 执行行；不使用 Quick I Ching 的状态、Attempt、payload 或提交结果。
没有 adapter 的合格候选才进入只读 Discovery；入口缺失时只从官网与观察到的同域链接寻找。
不能确认入口/字段/资格/matcher 的记录保留 unknown 或对应明确阻碍；不猜路径或 selector。
按预筛后的正式候选池顺序推进，`--limit 50` 表示前50个可处理候选，无需人工挑选平台。
`--start-after KEY` 和 `--limit N` 可限定本轮执行窗口；未处理记录保留 deferred/unknown。
报告同时保留 approved/deferred/confirmed_reject/unknown，original total=sum(states)。

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

## 只读 Discovery

Discovery 复用每站 worker、90秒截止和 context finally，不新增浏览器常驻池。
优先读取总表同域 HTTPS 提交入口，缺失/不可达时回到官方主页；最多5个页面，只追踪真实
观察到的 Submit/Add product/Launch/Contribute 等同域链接。跨域主页面导航和全部写方法被拦截。
公开 JS 仅 GET 观察到的官方 script URL，不猜 bundle 路径，不追踪 API GET 的重定向。

表单语义来自 label/name/placeholder/aria 和实际 options；仅使用唯一稳定属性 selector。
WYRPlay identity 来自原3.0-final，必填未知或选择/上传规则无法确认则 OWNER_INPUT_REQUIRED/人工核查。
当前自动生成范围为明确的产品表单、原生单选 taxonomy，以及可证实的匿名免费适配规则；
复杂 choice/widget/upload 条件与复杂 SPA handler 保留待审，不能为扩大 READY 数量猜测。
原生 matcher 要求明确 POST/action 且无可能覆盖提交的脚本/inline handler/按钮 action override。
JS matcher 只接受唯一、完整可证明的 observed-form submit listener，preventDefault 和唯一 literal
fetch method/host/path；通用 bundle 中出现 endpoint 字符串不构成 handler 绑定证据。

只有 adapter_gate 和当前 readonly_ready 均通过才原子生成新 adapter，包含官方来源、字段、
最终动作、dispatch、安全摘要与时间 provenance；已有 adapter 不覆盖，不调用 git。
生成后 DRY RUN 返回 READY；未来经 Owner 新授权的 LIVE 会释放 Discovery context，再进入原有
worker 的真实填写、fresh Sheet/黑名单/intent/授权检查以及 run_submission，不能直接 Submit。
分类原因 OFFICIAL_SUBMIT_URL_UNCONFIRMED、DISPATCH_MATCHER_UNVERIFIED、ADAPTER_REVIEW_REQUIRED
仅保留内部诊断；存在已记录发布渠道但不能自动执行时，Owner 行动状态为“去人工”，原因/备注用中文说明。不新增平行状态数据库。AI-only 仅项目不适用；全球淘汰必须命中明确
官方完整政策声明，普通付费价格、超时/404/无法查明均不能推断全球淘汰。

## Adapter 边界

复用已有 fields、required_fields、choice_fields、taxonomy、upload、qualification、free_verified、
final_action_verified 和 verified submission_request。batch 另需真实验证的 `final_submit_text`，
并提供 `authenticated_selector` 证明平台 session，或已验证的 `login_required=false`。
未核验这些执行条件就保持需人工核查，不猜 selector、不修改现有 adapter。

平台不适用/全局问题可由 adapter `assessment` 记录已核验的 outcome、reason、官方 source_url、
checked_at 和明确 marker；执行时重新读取该官方页面，marker 变化立即停止。
NOT_APPLICABLE 只写 WYRPlay“不适用”。GLOBAL_BLACKLIST 只接受 SPAM/PBN/MALICIOUS/
PERMANENTLY_UNAVAILABLE/PAYMENT_ONLY/NO_EXTERNAL_LINK_CHANNEL 的正证据，精确追加并回读
黑名单 A:R，不删除项目行。AI-only/登录/CAPTCHA/缺资料/单次网络错误不能进全局黑名单。

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

## 中文动作与人工循环

正式非提交核验显示“待提交 / 去人工 / 不适用 / 暂时不可用”；成功与审核中仍完全依赖原 E1–E4。
待提交只来自全部现有 adapter/readiness 门槛通过。需登录、人工验证、真实缺字段、复杂表单/
不明最终请求进入去人工；不适用须项目级正证据，黑名单须既有严格平台级证据。
无正向渠道事实的全量池记录保留 unreviewed，不写成不适用或黑名单，也不进入浏览器。
内部英文原因码仍在 runtime evidence，中文动作不是新提交授权，更不抹去证据不确定性。
未确认 dispatch/提交结果的原 Submit 合同、需人工核查和 persistent intent 保持不变，禁止重投。

Owner 明确处理时启动顺序循环（默认一站，可给出本次最多处理数量）：

```bash
.venv/bin/backlink-submitter human-loop --project wyrplay --owner-human-action --limit 5
```

队列由正式 Sheet 的“去人工”状态及总表顺序决定；runtime hint 只提供安全恢复 URL/profile。
缺 hint 的行仍去人工，提示先单站核验；不创建另一套正式任务数据库。
一次仅一个 dedicated headed browser，每5秒检查验证，最长10分钟。超时/关闭保持去人工，
context 关闭与 worker 进程组回收完成后才进入下一站。没有 Owner 明确命令不会抢桌面焦点。
已验证 matcher 的最终 endpoint 所有方法都拦截；无已验证 matcher 时整个窗口只读，
依赖 POST 的登录也不能放行，保留去人工等待单站 matcher 核验，不猜哪个 POST 是登录。
Owner 完成验证后，关闭 headed，再交现有 headless 单站链重新核验所有门槛。
循环不写提交结果、不执行 Submit；既有 headless 链确认 READY 后，使用原 protected writer
将该行从去人工更新为待提交，Attempt 不变，每次核对联合键并完整 A:J 回读。超时仍去人工。
返回单站 resume 指引；其余未通过项保留去人工，不靠新数据库推进队列。
真正继续提交仍需独立、单次、范围明确的 Owner LIVE grant；不能因人工循环通过而自动消费提交授权。
人工循环编排已由测试验证；没有声称未知 matcher 平台或真实 Owner 登录闭环已生产验证。

暂时不可用不会在普通批次自动重试。保留已观察到的安全恢复提示，Owner 可显式指定单站 `resume --mode dry-run` 重新核验；非零 Attempt/intent/成功/审核中仍禁止恢复提交。只有新的单站 LIVE grant 才允许恢复后的真实 Submit。
