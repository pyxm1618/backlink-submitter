# 唯一正式账本

名称：外链管理总控表。
ID：`1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA`。
任何访问前断言 ID；不创建平行正式表、不改结构。

## 三张表

| 表 | 键 | 记录内容 |
|---|---|---|
| 外链总表 | 外链ID | 平台事实，跨项目复用 |
| 黑名单 | 平台/外链ID | 有正证据的全局禁止池；提交前先查 |
| 外链管理 | 项目ID + 外链ID | 项目适用性、执行与结果；本仓库仅 wyrplay |

平台事实：存在/提交入口/免费/登录及方式/人类验证/支持的渠道/reciprocal或badge/
链接属性/故障/付费-only/垃圾或永久失效。不能把 WYRPlay 被拒绝写成平台失效。
项目事实：WYRPlay 类型是否允许、资料缺口、是否执行、尝试、证据和结果。
纯 AI 目录可能 WYRPlay 不适用，但未来别的项目适用，不进全局黑名单。

黑名单只有：明确垃圾/PBN/恶意/负面 SEO 网络/永久失效/确认任何外链渠道都不存在/
确认纯付费且当前全局政策禁止付费。必须记录跨项目原因与核验来源。
AI-only、类别不匹配、项目资料缺失、CAPTCHA、登录、一次 OAuth 故障、
内容投稿/Guest Post/博客/换链都不是全局禁用理由。

## 外链管理 A:J

| 列 | 字段 | 规则 |
|---|---|---|
| A | 项目ID | wyrplay |
| B | 外链ID | 现有标准化键，不靠 row number 缓存定位 |
| C | 平台域名 | 保留 |
| D | 状态 | 严格状态模型 |
| E | 尝试次数 | 仅 True Submit +1；纯核验保持原字符串，包括空白 |
| F | 最近操作时间 | 实际核验/执行更新时 UTC ISO-8601 |
| G | 目标URL | https://www.wyrplay.com/ |
| H | 结果链接 | 仅 E3 tracking 或 E4 listing；E1/E2 及无结果留空 |
| I | 原因/备注 | 保留旧备注，追加事实与结论，不写邮件正文/OTP |
| J | 证据摘要 | E码或资格/历史原因 + 核心摘要 + evidence 路径 |

写 D:J 前重新读取 A:J，核对 A=wyrplay、B=当前 backlink_id，并检查预期旧快照。
写 RAW 后完整回读 A:J，所有字段完全匹配。异常不能盲目重写，可能已经写入。
禁止其他项目更新；本次迁移所有外部 API 均只读。
资格证据不伪装 E1-E4。未处理空白行不能填造结果。

Google Sheets values API 没有原子 compare-and-swap；当前实现先读后写后精确回读，
无法阻止恰好夹在写入前后的外部并发。使用单一写者；发现冲突停止并人工核验，不宣称事务保证。
`write_outcome` 是低层函数，Attempt +1 只能传受保护 `submit_once` 的返回值，
与当前期望旧行绑定。写 +1 必须提供匹配项目/平台/原 E 值的持久 True Submit receipt，
以单次 sheet-intent 标记禁止重复计数；读写不明确时保留标记人工核验，不删除重试。

## 读取

`preflight --read-sheet` 使用 readonly scope、读取三张核心表、仅输出 WYRPlay 汇总，
不持久化其他项目行/邮件/敏感备注。凭据通过外部文件，不进 Git。
没有凭据/权限时报告依赖缺失，不伪造统计；新窗口需要已授权账户/connector 或现有 service account 文件。
