# 当前 WYRPlay 工作状态（2026-10-09）

本次授权仅覆盖正式执行表顺序前 10 个可处理记录，已真实逐站执行，未开启下一批。
688/channel_basis 硬门槛已取消；缺入口、类型或旧证据仍允许从官网发现。
正式身份、Sheet 和 3.0-final 资料包保持原合同。已有成功/审核中、Attempt、intent 和黑名单仍保护。

实际已确认一次 Telegraph 最终 Publish：POST edit.telegra.ph/save；Attempt=1；匿名 E4 确认公开
https://telegra.ph/WYRPlay-10-09 含 WYRPlay 官网链接，Sheet A:J 精确回读为成功。
Sideprojects 在同一 context 完成密码登录、填写和一次 Submit for launch，真实观察到
POST sideprojects.net /projects/submit；Attempt=1，结果待核实，未确认 E1–E4。
ebool 与 The Hack Stack 各最终点击一次，派发元数据未确认，Attempt 保持空白；后者页面返回分类必填错误。
共打开10站、业务填表4站、最终点击4次、确认业务请求2次、成功1、审核中0、重复提交0。
当前十站完整结果及收尾核验见 LIVE_10_VERIFICATION.md。不能据此宣称可以扩大批量。

Gmail 已连接工具实际 profile/search 成功，已接上 host→stdin→CLI 内存往返；
本次尚未完成任何真实 OTP/magic link 登录。Google OAuth 已尝试，未验证登录成功。
新平台账号设置密码可使用 Owner 授权的内存值自动填入；主账号密码、挑战和 2FA 仍由 Owner 操作。
值不进入 shell 命令、日志、Sheet、Git 或凭据文件。

LIVE 从发现到填表/多步骤/最终 Submit 使用同一 context；首次 Submit 不要求预存 matcher。
点击前写 O_EXCL intent，点击最多一次；只有确认实际业务写请求才增加 Attempt。
测试与 fixture 不替代以上生产结果，未知或系统未完成不得冒充拒绝或 Owner 必须操作。

## 以下为历史执行记录

旧批次的 200 条、688 池、未授权 LIVE 或旧 Gmail 不可用结论仅描述当时状态，
不能用作本次队列边界或当前 connector 状态。

## 候选池与生产状态修复（2026-10-09，历史决策，688边界已撤销）

全量域名池 != 可提交候选池。正式三表 fresh read：WYRPlay 外链管理19,103条，
外链总表31,213条，黑名单6,206条；普通新闻/企业/学校等官网不能仅凭在池中就进入浏览器。
上一轮曾按正向渠道预筛得到688个可核验候选；该硬门槛已由Owner本轮要求撤销。历史统计为：
其中671个明确官方发布入口、17个明确目录/发布平台类型。旧泛化成功备注不构成平台渠道事实，但缺渠道事实不再阻止Discovery；
已验证事实必须有可追溯官方来源。未纳入队列的数据不删除，未审/不确定仍保留未知。

- 原授权200条全部完成逐项官方证据审计：待提交0、去人工119、不适用58、暂时不可用23、黑名单0。
  每条写入均fresh joint key、Attempt increment=0、完整A:J回读；范围外行、总表、黑名单变化0。
- fabtoolai.com真实必填字段为 Email（wpforms-8262-field_4）；正式项目已有support@wyrplay.com。
  旧UNKNOWN是必填标签映射漏识别，不是Owner缺失资料。状态去人工，备注明确字段及适配核查。
- 新池正式顺序前200条只读运行，与原200条交集0：待提交0、去人工191、不适用0、暂时不可用9、黑名单0。
  新真实Submit=0，新批Sheet write=0，新adapter=0；并发最大2、同域1、200个关闭区间、worker组全部回收。
- 本轮两组200条均有中文明确动作；内部reason/evidence不足保留为诊断信息，不冒充通过或淘汰。
  其余未审历史记录不扩大修改。
- human-loop已实现并经测试：单窗口、5秒轮询、最长10分钟、超时释放，再交现有headless链核验。
  已验证最终endpoint在人工窗口持续阻断；未知matcher保持只读，不猜登录POST或最终Submit。
  Owner实际人工登录/验证生产闭环本轮未执行；任何真实Submit仍需独立、单次、明确授权。
- ruff check/format、mypy、189 pytest及readonly preflight通过；原149测试全部保留。

零READY的结论：尚不具备下一步大量提交条件，停止，不开启LIVE。
官方渠道预筛只证明“可能可发布”，不证明免费/适配/自动可提交：例如uool.com页面明确需登录，
secureblitz.com/write-for-us为原创文章编辑收稿，thataicollection.com/submit为多步骤AI收录流程。
现有资料中资格/免费事实及Discovery的完整表单/最终请求证据仍有缺口；不得以入口字符串提升READY。
本轮不扩展adapter支持；下一步须有界核验这些缺口，不继续从大池盲跑。
安全核验记录见 [CANDIDATE_POOL_REPAIR_VERIFICATION.json](CANDIDATE_POOL_REPAIR_VERIFICATION.json)。

## 正式 LIVE 200 候选批次（2026-10-09，历史记录，当前动作见上节）

Owner 明确批准基于 `d6a26c0967989196c6bcb78d07447dd70204a697`，从 `uool.com` 后
按正式三表与 select_candidates 规则锁定200个新可处理候选；首项 `airadar.live`，末项
`factcheckcenter.jp`。一次性仓库外授权已消费，批次结束，不自动继续下一批。

- 精确处理/访问200；并发2、同域1、200个浏览器关闭区间，worker超时/崩溃0，残留browser/context0。
- verified adapter新增0、READY_TO_SUBMIT 0、真实Submit 0、SUCCESS/PENDING 0、真实提交率0%。
- HUMAN_VERIFICATION_REQUIRED 47（验证挑战18、Owner登录29）、OWNER_INPUT_REQUIRED 1。
- TEMPORARILY_UNAVAILABLE 19；证据未确认待复核133。NOT_APPLICABLE/新增GLOBAL_BLACKLIST均0。
- 本窗口显式覆盖：approved0 + deferred67 + confirmed_reject0 + unknown133 = 200。
  unknown保留未知，不作拒绝；全部候选已运行不代表全部资格已确认。
- 正式Sheet写入200次，每次既有protected writer均完成精确A:J回读；结束再fresh核验200行。
  恰好批准范围内200行变化；Attempt全部保持原值，结果链接空白，其他项目/错误行变化0。
- Scope内无Submit intent、重复Submit0；StartupFound及其他既有成功/历史Attempt行未变化。
- `fabtoolai.com` 返回 `UNMAPPED_REQUIRED_FIELDS`；现有Discovery结果未记录具体字段名。
  字段事实保持UNKNOWN/需人工核查，不猜Owner事实，不现场修改通用代码。
- 当时“未观察到必须阻止下一批的系统级错误”的判断现已被本轮根因审计纠正：
  全量域名池并不是可提交候选池，旧泛化备注也不能替代可追溯的平台发布事实；不得据此继续 LIVE。

基础检查：ruff check/format、mypy、149 pytest、正式Sheet readonly preflight及匿名headless
浏览器smoke均PASS。未修改通用代码或既有adapter；本次仅固化安全生产核验/当前状态记录。
完整范围、原因统计、核对依据和外部runtime路径见
[PRODUCTION_BATCH_200_VERIFICATION.json](PRODUCTION_BATCH_200_VERIFICATION.json)。

## 生产 Canary

WYRPlay × StartupFound，外链管理 row 6249，backlink_id `startupfound.com`：

- Owner 单次授权，真实 final click=1。
- dispatch_confirmed=true：`POST startupfound.com /api/startups/submit`。
- Attempt=1；后续 E4 状态升级 Attempt increment=0。
- E4：全新匿名 context 验证公开 listing 与可见 WYRPlay backlink。
- Result URL：https://startupfound.com/s/wyrplay；Sheet 最终状态=成功，完整 A:J 已精确回读。
- Duplicate Submit=0；其他 Sheet 行修改=0。
- 公开页面仍标注 Waiting for moderation；E4 不代表平台 moderation 已批准。
- E1 文案未被现有识别器接受，E2 邮件连接不可用，E3 未取得认可 tracking proof；通过依据为 E4。

安全元数据与外部 runtime 路径见 [PRODUCTION_CANARY_VERIFICATION.json](PRODUCTION_CANARY_VERIFICATION.json)。
生产 run `20261008-131026-d9032b`；本地证据保持仓库外，不复制敏感页面、Sheet 备注或凭据。
固定 project×platform persistent intent 已保留，禁止重复 Submit。

## 执行边界

Canary 后的首次 Owner-scoped LIVE 200批次已结束；Canary快照 `ready_for_controlled_rollout=false`
不是永久Submit授权，本批没有READY或Submit。未来批次仍须新的Owner明确范围。
所有 `automatic_submit_allowed=false` 保持不变，StartupFound 的单次运行时授权已消耗。
不处理历史 Attempt，不扩大平台池；未来工作必须遵循新的 Owner 范围并刷新正式 Sheet。
此前Canary状态收口仅固化仓库，新真实Submit=0、Sheet write=0；本次LIVE批次写入200，见上节。

## 原 Canary 平台

其他四站保留旧现场快照（run `20261008-142831-e5175e`），不是当前会话保证，本次未访问。

| 平台 | 已记录的状态 | 下一步边界 |
|---|---|---|
| FoundrList | 表单/上传曾验证；免费资格需 Owner 判断 | Join queue 仅弹窗，非 Submit；不自动挂 badge/制造社区活动 |
| PeerPush | HUMAN_VERIFICATION_REQUIRED | Owner 人工验证，不绕过 |
| AppLauncher | basic Google OAuth；onboarding/session 未确认 | 获授权后核验 Workspace/Username 流程 |
| StartupFound | 成功，Attempt=1，E4 | 已完成本次 Canary，保留 intent，不重投 |
| Startup List | PLATFORM_OAUTH_CONFIGURATION_ERROR | 临时 OAuth 故障，不永久黑名单 |

## 历史迁移来源

旧 worktree HEAD `b19ab2e32de0868f686a4d4a03b37e598cf8f337`，修复文件当时为未跟踪文件；
迁移清单另有文件 SHA256，不能用该 HEAD 误认为涵盖修复。
`MIGRATION_VERIFICATION.json`、`COLD_CLONE_VERIFICATION.json` 和旧 Canary receipt 保持历史原样。
其中未验证 Canary/旧 Sheet 数量描述是当时快照，由本次生产记录取代当前状态；
绿色 fixture tests 或历史 ratingfacts 成功不能替代本次 StartupFound 的真实生产证据。

## 批量能力准备（未执行 LIVE）

最小候选分流、默认2/最多4 worker、同域1、进程回收与单站 handoff/resume 已实现；
运行方法及边界见 `BATCH_RUNNER.md`。此次只读 dry-run，不改 StartupFound 成功记录或历史 Attempt。
StartupFound 的 Founder 显示为平台账户 Display name Wang Tachyon，未获 Owner 确认；
记录 `OWNER_INPUT_REQUIRED`，详见 `STARTUPFOUND_FOUNDER_REVIEW.json`。未修改 listing。

## 只读 Discovery 能力

无 adapter 的可处理候选现在复用现有 worker 进行有界官网核验，凭正证据生成 adapter 或明确分流。
当前轮仅前50个可处理候选的顺序 dry-run；真实 Submit=0、Sheet write=0，未启动 LIVE。
核验结果见 `DISCOVERY_DRY_RUN_VERIFICATION.json`；未覆盖的平台仍保留原显式 unknown/deferred。

## Matchbox 定向修复（2026-10-09，未执行 LIVE）

仅 `askmatchbox.com` 新增已现场核验的表单展开、组合 identity 和 React handler 支持。
真实 readonly discovery 已生成 verified adapter，READY_TO_SUBMIT；最终 Submit=0、Sheet write=0。
组合值只来自正式名称和 canonical URL，换行分隔；prepare_form 与最终提交前均精确核对实际 identity。
handler 必须与现场 form.onSubmit 和官方 bundle 中的同组件 listing form 绑定，且匹配已审计函数 hash；
无 category 的 Matchbox 不要求 taxonomy，其他平台既有规则保持。所有自动提交开关仍为 false。
原同批50站只读回归与安全证据见 `MATCHBOX_DISCOVERY_VERIFICATION.json`；不授权 LIVE 或 rollout。
