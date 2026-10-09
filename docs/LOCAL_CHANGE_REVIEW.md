# 上一轮本地修改审核

实际接手目录：`backlink-submitter-fresh-window-20261008`。远端 main 与接手 HEAD 均为
`9ea8df3ea9f0f29c2ec60950b47fdc0f5d22939d`。没有 reset、清理 profile 或重写数据库。

原始未提交项 16 = 保留并修正 16 + 暂缓 0 + 确认删除 0 + 未审核 0。
文件逐项审核；“保留”包含必要的局部纠正，不代表原实现完整可用。

| 原始文件 | 决定及依据 |
|---|---|
| docs/BATCH_RUNNER.md | 保留队列顺序与隔离说明；删除首次提交必须证明 matcher 的要求，补 host Gmail 接入 |
| docs/CURRENT_STATE.md | 保留历史记录；当前状态以本次十站实际执行报告为准 |
| docs/RUNBOOK.md | 保留项目、资产和防重合同；更新有限 LIVE 授权与现场推进方式 |
| docs/STATUS_MODEL.md | 保留 E1–E4；普通认证和技术缺口不伪装为 Owner 人工动作 |
| src/backlink_submitter/batch.py | 保留撤销 channel_basis 门槛、执行表排序、并发回收和账目覆盖；修正汇总敏感键误报 |
| src/backlink_submitter/batch_worker.py | 保留认证与人机分离、资源回收；LIVE 使用同一 context 从发现到提交 |
| src/backlink_submitter/candidates.py | 保留渠道提示；不再作为允许进入网站的条件 |
| src/backlink_submitter/discovery.py | 保留字段和入口识别；补动态加载、普通查询 URL、真实 CTA、上传与首提监听 |
| src/backlink_submitter/human_loop.py | 保留单站人工轮询与原 profile；本次 LIVE 自动恢复在同一当前流程执行 |
| tests/test_batch.py | 保留队列/Attempt/intent/联合键合同；更新旧人工状态可重新发现的预期 |
| tests/test_candidate_actions.py | 保留未知与拒绝区分、中文动作与正式队列覆盖 |
| tests/test_discovery.py | 保留真实 DOM/请求的 fixture；未将 fixture 宣称为生产提交 |
| src/backlink_submitter/automation.py | 保留 OAuth、邮箱、多步骤；取消正常 Google 按钮的事前 handler 证明要求，修正认证计数 |
| src/backlink_submitter/gmail_connector.py | 保留严格邮件绑定与 MIME 解析；适配当前 connector 实际响应，接上内存 stdin 往返 |
| src/backlink_submitter/handler_proof.py | 保留为只读诊断；LIVE 首提不调用，不再阻碍真实提交 |
| tests/test_automatic_progress.py | 保留认证、验证码、防挑战绕过和多步骤测试；正常条款 checkbox 自动处理 |

本轮新增的首提请求测试、正常登录 URL/统计回归测试及 Telegraph 富文本填写，只服务于本次范围。
credential、cookie、验证码、token、profile、Owner grant 与敏感运行页面均不加入 Git。
