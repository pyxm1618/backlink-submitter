# 当前 WYRPlay 工作状态（2026-10-08）

正式身份/Sheet/资料包见 project.json，原包 3.0-final 完整保留。
旧 worktree 来源 HEAD `b19ab2e32de0868f686a4d4a03b37e598cf8f337`，修复文件当时为未跟踪文件；
不要用 HEAD 误认为涵盖这些修复，迁移清单另有文件 SHA256。
最新真实现场来源 run `20261008-142831-e5175e`，语义状态及摘要凭据已随仓库保存。
本地旧 runtime 仅作为历史附件留存；clone 恢复规则与停点不需要它。

**FUNCTIONAL CANARY NOT YET VERIFIED**

**NOT READY FOR CONTROLLED ROLLOUT**

| 平台 | 已验证 | 当前下一步 |
|---|---|---|
| FoundrList | Google OAuth、产品表单、正式字段、SVG logo、5截图 | 免费 badge/合法社区资格需要 Owner 判断。Join queue 仅弹窗，不是真 Submit |
| PeerPush | 安全停止于人类验证 | Owner 人工验证后读现场，不绕过 |
| AppLauncher | basic Google OAuth | Workspace/Username onboarding/session 尚未确认，继续账户流程核验 |
| StartupFound | OAuth、表单可到达 | Funding、Founder structure 必填资料缺口；找项目可信事实/Owner 输入 |
| Startup List | 正常 Google session，官方 OAuth 报 missing client_id | PLATFORM_OAUTH_CONFIGURATION_ERROR 暂故障；未来只读复核，不永久黑名单 |

所有5站 True Submit=0、Attempt Increment=0，无本批 E1-E4。
已验证错误计数均0：Wrong Project、Duplicate、Evidence-less Pending/Success、Wrong Sheet Write。
历史 ratingfacts E4 成功不代表本批 functional Canary。

本次迁移只读 Sheet 预检实测 19,103 个 WYRPlay 联合键，无重复：
unknown19050 / 待提交8 / 需人工核查32 / 不适用10 / 历史未验证2 / 成功1 / 审核中0。
总表平台行31213；黑名单行6206。这是时间快照，不是下次必须吻合的固定数字。
新窗口必须刷新，不能当做近期登录状态。完整迁移预检见 MIGRATION_VERIFICATION.json。

下一步不是扩大提交池：先由 Owner 解决原5站的资格/项目资料/人工挑战/账户流程/平台故障，
明确授权继续 same-five Canary 后再读 Sheet 和 Profile；至少一次真实产品 Submit 的生产证据链
经核验后才可以讨论 controlled rollout。迁移本身不授权它。
