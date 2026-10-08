# WYRPlay 恢复与执行 Runbook

先读 AGENTS、project.json、正式 manifest/CSV、FIELD_POLICY、STATUS_MODEL、SHEET_MODEL；跑全部合同测试。
所有对外字段必须来自包内文本或附有可信来源和 Owner 确认的补充资料。
启动项目不是 wyrplay 或 manifest 不是 3.0-final，立即停止。污染 payload 立即中止当前站，
记录配置污染/需人工核查，不替换后继续。

## 当前停点

看 `projects/wyrplay/canary_state.json` 与 `docs/CURRENT_STATE.md`。
目前 **FUNCTIONAL CANARY NOT YET VERIFIED / NOT READY FOR CONTROLLED ROLLOUT**。
migration、绿色 tests、fixture Submit、历史成功项都不能改变这个结论。
本次迁移没有获准新外链提交；下一阶段必须等 Owner 指令。

## 冷启动预检

按 README 安装，运行 lint、mypy、pytest 与只读 preflight。
读正式 Sheet，核对三张表/联合键/总数覆盖；不固定认为数量永远 19,103。
检查黑名单，然后查 project×platform 状态与外部 runtime intent。
任何历史已提交迹象先核验，不直接重投。
缺外部凭据只报告 Owner setup；不得复制旧硬编码 secret 或另建 Gmail OAuth。
Gmail 已连接 connector 优先；Profile + 无副作用 search + 时间/发件/收件过滤。
邮件搜索失败是 `EMAIL_EVIDENCE_UNAVAILABLE`，只阻断需要邮件证明的具体步骤。

## 资格与渠道

先用三张表预筛，不访问整个 19k unknown 池。只有被 Owner 批准范围才做现场核验。
真实官网、正确官方入口、类型适合、免费可用、质量正常才能 QUALIFIED。
登录不是淘汰；人类验证是执行阻碍；未确认免费/类别则人工核查。
A/B/C 用简单相关性与质量判断，不打百分分数。

支持渠道分类：
PRODUCT_DIRECTORY、STARTUP_DIRECTORY、SOFTWARE_DIRECTORY、GENERAL_DIRECTORY、
CONTENT_SUBMISSION、GUEST_POST、BLOG_PUBLISHING、COMMUNITY_PUBLISHING、RECIPROCAL_LINK。
内容/博客/Guest Post 是研究价值，不因不是 Submit Product 而全局淘汰。
普通评论、垃圾回帖、搜索、newsletter、随机 contact/问卷不是产品收录。
内容发布必须是官方允许渠道、相关原创价值且有单独 Owner 授权；本仓库不自动执行这些动作。
Google Form 必须官网明示作为收录入口。

换链标 `RECIPROCAL_REQUIRED` 等待 Owner 价值判断。
主要 nofollow 默认不值得交换；已证明高质量 dofollow 可人工候选；不明则 UNKNOWN/NEEDS_REVIEW。
不自动挂 badge、不制造社区投票/评论、不购买套餐/Featured/backlink、不改 WYRPlay 网站。
旧资格备注可能按旧 reciprocal 标准产生；不能全局删除或自动反转，未来做有界复核。

## 缺字段闭环

可选未知留空；必填先查 pack、confirmed_facts、WYRPlay 正式网站/配置可信来源。
明确可靠且在 Owner 授权范围内的事实，固化补充资料并记录来源；Operator 不等于 Founder。
无法确定输出 `OWNER_INPUT_REQUIRED`：field/platform/why_required/possible_values/source。
Owner 确认后写 `projects/wyrplay/confirmed_facts.json`：

```json
{"Field Label": {"value": "Owner-confirmed fact", "source": "official source / Owner instruction",
                 "owner_confirmed_at": "ISO-8601"}}
```

包内既有 identity/copy 不被补充静默覆盖；改正式包必须明确审批、更新版本及 checksum。
原包 policy MD 的“mandatory -> manual”与该机制一致；先查可信事实，未确认前仍停止。
资料缺失不是平台失败。不要以 Other/N/A/零值替代未知 Founder/Funding。

## 浏览器与 Owner handoff

Playwright + Chrome Chromium 内核 + headless，默认 service_workers=block。
专用 profile 是仓库外 `~/.backlink-autofill/browser-profile`，不复制 cookie/profile 到 Git。
当前 live handoff 已证明要 `ignore_default_args=['--use-mock-keychain']` 匹配 Owner 正常 Chrome 钥匙串。
Profile 有 SingletonLock：不删除锁、不杀所有 Chrome；Owner 正常关闭专用窗口后继续。
Owner 登录 Google 不等于每个平台已登录。真实检查平台 session，一站一 context/page 保持
OAuth -> onboarding -> form -> upload -> final action 连续性；不要中间关闭导致 SPA/session 丢失。
可以正常使用 Owner 已登录 Google 账户，禁止密码重输/挑战/2FA/风险绕过。
任何 CAPTCHA/Cloudflare Human Verification/设备确认 -> HUMAN_VERIFICATION_REQUIRED，停在现场给 Owner。
本仓库不自动打开 headed 窗口或抢焦点；人工步骤由 Owner 完成。
导航20s、元素10s、提交响应30s，单站90s；需 OTP 最多额外180s。
关闭 page/context 用 timeout；失败销毁 worker，不能无限堆页。小批 concurrency2、同域1，
只有 live Canary 通过才可最多4。当前没有批量执行器/rollout授权。

## 精准填写与最终 Submit

Site Adapter 优先。真实确认官网意图、label/name/placeholder/aria/说明、必填字段；
没有验证 selector 不生成通用瞎填。资料从 pack 选择短/中/长，按实际字符长度，不能自由改文案。
Games 优先，Entertainment/Party Games/Social Games/Web Application 按真实 taxonomy；非 AI。
Logo 仅正式 PNG/SVG；截图 Home、Play、Find、Print、Leaderboard 顺序。

`workflow.fill_fields` 只用于 Owner 授权已验证 adapter；`workflow.run_submission` 单站合同
检查实际 DOM 污染/identity、required、free/reciprocal、fresh Sheet 联合键、既有状态和持久 intent。
明确 final selector 及动作语义，再授权 automatic_submit_allowed。
当前五站均 **未授权自动最终 Submit**，不复制 Join free launch queue 当 final selector。
固定 runtime 根 `~/.backlink-autofill/runtime/wyrplay/`；per-key intent 在其 submit-intents 子目录，跨 run 保留。
runtime 新 run_id YYYYMMDD-HHMMSS-random；每站 before/after/evidence.json/dom_excerpt。
截图仅产品页，不能截图已填写 OTP/密码/带 OAuth token 的页面。若现场含敏感值，停止保存原始页，
仅保存允许的 metadata 与脱敏状态；不要复制整段 HTML/邮箱正文。
`save_evidence` 校验敏感键与认证 URL；结构化收集者不能把 secrets 放入任意备注绕过该边界。
邮件 OTP 仅 MemorySecret 内存，不 console、不 Sheet、不 evidence、不 magic-link token 输出。

最终动作最多一次，正常派发返回 +1。保存受理证据后 protected Sheet 写 D:J + full A:J readback。
无结果 manual；日志只输出安全摘要，不输出原 provider exception/token/body。
异常/关闭/读取失败必须保留 intent 和现场；不要因报告失败又 Submit。
E2/E3/E4 分别通过专用验证函数取得 proof，再 `classify` 与 `write_outcome`，不猜 page.url。
E4 质量记录不改成功定义，但 noindex 等可以降低后续优先级。

## 结束/交接

报告逐站状态/证据/True Submit/Attempt，原总数=sum(approved+deferred+reject+unknown)，
所有排除有逐项事实；未核验不等拒绝。不改其他项目、不批量创造空行结果。
要升级 functional Canary，必须真实 Submit、真实证据、真实 Sheet 回读且五类错误=0。
这件事尚未发生，迁移完成后停止等待 Owner。
