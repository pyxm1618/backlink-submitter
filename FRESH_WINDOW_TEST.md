# Fresh Window Test

给一个无旧聊天历史的新 AI 只发：

> Clone https://github.com/pyxm1618/backlink-submitter.git，按 AGENTS.md 恢复 WYRPlay。
> 阅读必要文件、跑全部合同测试、只读访问正式 Sheet；报告当前状态和下一步。
> 本次禁止注册、OAuth、填表、Submit、Sheet 写入和 rollout。

按 README 安装环境。Owner 已有 Sheet 授权凭据放仓库外，通过
GOOGLE_APPLICATION_CREDENTIALS 或默认现有 service-account 文件访问；凭据不会随 clone 提供。
若无权限报告 OWNER_SETUP_REQUIRED，而不是猜数字。

验收：新 AI 能说明三张表、平台/项目事实、全局黑名单边界、content submission 价值、
reciprocal 人工价值判断、缺字段 Owner 闭环、Human Verification、E1-E4、True Submit/Attempt，
并恢复各站状态及 FUNCTIONAL CANARY VERIFIED / CONTROLLED ROLLOUT NOT STARTED。
必须指出 FoundrList 非最终点击、StartupFound 已完成一次 E4 Canary 且禁止重投、Startup List 临时 OAuth 故障。
生产验证摘要见 `docs/PRODUCTION_CANARY_VERIFICATION.json`；旧冷 clone/迁移回执保持历史原样。
给下一步但不执行；测试绿色不等于真实提交成功。

运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/backlink-submitter preflight --project wyrplay --read-sheet --browser-smoke
```

本迁移验收用独立干净 clone 重跑以上命令，检查只靠仓库的配置、状态快照和文档即可恢复。
这验证冷 clone 可运行与信息完备；不是宣称已让独立新 AI 做完语义验收。
真正 Fresh Window AI 验收使用上述最小 prompt，不提供旧 runtime 或聊天历史。

实际冷 clone 验证回执：`docs/COLD_CLONE_VERIFICATION.json`。独立虚拟环境58测试通过，
真实三表只读访问及 headless smoke 通过，真实 Submit/Sheet 写入均0。独立新 AI 语义验收尚未运行。
