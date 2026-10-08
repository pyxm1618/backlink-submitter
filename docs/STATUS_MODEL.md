# 状态与证据合同

## 外链管理 D

| 状态 | 含义 |
|---|---|
| 空白（报告 unknown） | 尚未按新标准处理，保持原样 |
| 待提交 | 资格已确认；真正执行仍需检查登录、Owner 授权和幂等性 |
| 历史未验证 | 旧系统称提交，但无当前认可证据；不是失败，先核验，不能直接重投 |
| 需人工核查 | 人类验证、缺必填资料、配置污染、执行/结果不确定 |
| 审核中 | 有与本次 True Submit 绑定的 E1/E2/E3 |
| 成功 | E4 匿名公开 Listing 与真实 backlink |
| 被拒绝 | 有平台明确拒绝证据 |
| 不适用 | 对本项目不适合，不能自动全局黑名单 |
| 提交失败 | 明确技术/校验错误，且能证明没有成功提交 |

状态标签不替代原始原因，保留历史备注和新证据。不得把 unknown 当拒绝或批量变待提交。

## E1–E4

- **E1 PAGE_PENDING**：最终 Submit 后新出现明确受理反馈。原页面已有 Pending 不算。
- **E2 EMAIL_PENDING**：新官方确认，received_at >= submission_started_at；发送域与平台相关，
  收件人是该步骤实际邮箱，正文明确绑定 WYRPlay submission/listing。OTP 邮件不算。
  仅持久化 message ID、时间、sender domain、安全 subject；不保存正文。
- **E3 TRACKING_PENDING**：本次 Submit 后新唯一 submission/status/launch URL，
  官网同域，内容证明对应 WYRPlay；dashboard/page.url/跳转本身不算。
- **E4 LIVE_LISTING**：全新匿名 context、无 storage_state、200 公开可访问，
  标题/主体识别 WYRPlay、有可见真实 `<a>` 指向 wyrplay.com/www.wyrplay.com。
  不能是 dashboard/preview/search/login/确认页。检查最终 URL、canonical、title、主体。
  记录 rel、meta robots、X-Robots-Tag；nofollow/ugc/noindex 不等于失败，价值另评。

E1/E2/E3 -> 审核中；E4 -> 成功。HTTP 200、无错误、URL 变化、点击按钮都不算受理证据。
提交后无证据 -> 需人工核查 / `SUBMIT_RESULT_UNCONFIRMED`，不得再次 Submit。

## True Submit 与 Attempt

真正创建 submission/listing/review request 的最终动作才是 True Submit。
Login/Continue/Next/Upload/Preview/Save Draft/Open Modal/Join Queue 弹窗不是。
确认成功派发一次最终动作，Attempt +1；此前为 0。
派发发生超时/崩溃且不能确定是否到达：保留 intent，人工核验实际尝试，禁止重试或猜测次数。
测试证明正常 True Submit +1；这种异常分支尚未经过生产实测。

`submit_once` 的 O_EXCL intent 文件必须按 `(wyrplay, backlink_id)` 跨 run 持久保存。
不能因为重开窗口/换 run_id/删除 runtime 而重投；正式 Sheet 也要先查。
成功、审核中、需人工核查、历史未验证均不能自动再次 Submit。
非最终点击若要重新归类必须有动作语义的正证据，不能用“没有反馈”作推断。

## 原因码与两个维度

原因码不是新 Sheet 状态：
`OWNER_INPUT_REQUIRED`、`HUMAN_VERIFICATION_REQUIRED`、
`PLATFORM_OAUTH_CONFIGURATION_ERROR`、`PLATFORM_AUTH_ERROR`、
`TEMPORARILY_UNAVAILABLE`、`RECIPROCAL_REQUIRED`。

资格：QUALIFIED_A/B/C、NOT_APPLICABLE、MANUAL_REVIEW、UNKNOWN。
执行就绪：READY、LOGIN_REQUIRED、HUMAN_VERIFICATION、UNKNOWN。
登录或人类验证本身不否定资格；关键免费/类别/政策事实未知才是资格人工核查。
