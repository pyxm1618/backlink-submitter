# WYRPlay 下一顺序 20 站 LIVE 核验（2026-10-10）

Owner 授权的是远端 main `1bd1c4f417d0156ddbb80052e21444f2ca264122` 上的四项定点修复和正式顺序下一批 20 个新记录。
本轮为 LIVE，不是 dry-run。没有扩大到 50；上一轮十站没有重新执行。

## 四项修复

- 普通注册后在当前平台继续登录；已有本轮账号密码和 Owner 明确提供的平台账号仅在内存使用。平台认证邮箱与 WYRPlay 公开联系邮箱分离，最终业务字段仍是正式资料包。Google 账户选择严格匹配当前 connector 身份。
- 沿用 host → Gmail connector → stdin → CLI；并发站点共享串行 stdin 请求锁，验证码或 magic link 按平台、收件人、发起时间和语义匹配，并有限等待。本批没有触发可确认的 OTP/magic link，闭环为 0。
- 最终点击前检查原生 validity、visible required、radio/checkbox/file、页面错误及核心身份和分类；用已有批准文本和实际分类选项修复。校验失败不创建 Submit intent，不消耗最终点击。
- 首次真实提交保留 E1–E4，观察原生表单业务请求、同平台响应状态/JSON中的固定回执标记、页面/公开链接和确认邮件。请求体及完整响应不保存。观察窗口覆盖 SPA 异步响应；已确认业务请求但结果不清楚仍保护 intent、Attempt +1，不重投。

认证续接还修正了实际登录页面未进入 discovery_visited 时无法 resume 的问题：仅补入浏览器真实到达的官方 URL。
没有另建 OAuth，没有添加依赖或更改正式资料包。

## 精确范围与逐站结果

|顺序|平台|正式行|本轮最终卡点|
|---|---|---:|---|
|1|desifounder.com|814|普通 OAuth 尝试后仍未核验平台登录；发现论坛，未完成业务表单入口|
|2|coodoeil.fr|816|法语目录入口没有被推进到业务表单|
|3|peerpush.com|817|定价页的普通认证未推进完成|
|4|hunt0.com|818|页面访问超时/无法打开|
|5|microlaunch.net|819|HTTP 访问失败，非永久拒绝|
|6|tinylaunch.com|820|未核验可执行发布入口|
|7|huntscreens.com|821|真实 Submit 页面含 $0 Queue；未推进队列选择及后续表单；未点击付费提交|
|8|dev.to|822|普通 OAuth 尝试未确认平台登录，未进入发布编辑器；没有评论或发帖|
|9|starterstory.com|824|登录/邮件入口页面 HTTP 访问失败；未确认发起邮件验证|
|10|stellarlaunch.org|825|普通邮箱认证未推进完成|
|11|topaihubs.com|826|真实 /submit 转登录页，认证及业务表单未推进完成|
|12|aiching.app|827|实际页面为问答产品，未核验发布入口；没有提交问题|
|13|parade.com|828|HTTP 访问失败，未确认人工验证挑战|
|14|alternativeto.net|829|HTTP 访问失败，未确认人工验证挑战|
|15|aitoolhub.net|830|原遇现有账号密码；Owner 补充账号后自动发出登录请求，未确认登录成功；官网 Submit 指向 gptdemo.net，未擅自扩大站点范围|
|16|moge.ai|831|未核验可执行发布入口|
|17|seektool.ai|832|Google OAuth session/consent 未确认，系统继续负责|
|18|aitoolnet.com|833|HTTP 访问失败，非永久拒绝|
|19|toolidx.com|834|实际提交页出现付费按钮 $29，与 FAQ 免费提交说明未形成可执行免费流程；未购买|
|20|toplikevideo.com|835|未核验可执行发布入口|

20 个均实际打开。17 个由本轮页面证据直接确认；初轮异常退出的 3 个另有本轮时间范围内 Chrome 官方导航历史，随后仅在原范围内复查。
最终官方 Sheet 20 个均为暂时不可用；内部覆盖为 approved 0 + deferred 20 + confirmed reject 0 + unreviewed 0 = 20。
不把未找到、访问失败或认证未完成改写为平台拒绝。

## 验收数字

|指标|真实结果|
|---|---|
|锁定/实际打开|20 / 20 个唯一平台|
|明确发布入口|4：HuntScreens、TopAIHubs、Toolidx 的站内入口；AiToolHub 官网 outbound Submit。后者未执行目标站；该数字不证明免费资格或完整业务表单可用|
|完成注册/登录|0|
|Google OAuth 完成|0；有实际尝试，完成未确认|
|Gmail OTP/magic link 实际闭环|0；本批未触发可确认的邮件验证码或 magic link|
|业务表单填写/到达最终 Submit|0 / 0|
|最终点击/确认真实业务请求|0 / 0|
|成功/审核中/已提交待核实|0 / 0 / 0|
|真正人工步骤|曾 1：AiToolHub 现有账号密码；Owner 提供后已自动尝试，当前待人工 0|
|最终系统暂缓|20：入口/表单推进 10，认证 4，访问问题 6|
|重复 Submit|0；20 个均没有新的 Submit intent|
|范围外或错误 Sheet 修改|0；范围外执行行、总表、黑名单快照 hash 均与本轮前一致；上一轮十站包含于保护范围|
|Attempt|20 个均保持各自执行前值|
|tests|230 项完整测试通过；最新续接改动另以 54 项入口/认证回归通过。fixture 不计入生产成绩|
|下一批 50|不建议；业务 Submit 为 0，普通认证自动完成未确认|

真实缺口是从动态发布入口持续推进到业务表单的通用交互能力：免费队列/弹窗、认证回到平台和后续多步页面仍未可靠完成。
本批没有进入最终提交，因此提交前校验及回执增强只有自动化测试证据，不能宣称经过本批生产 Submit 验证。

## 可追溯证据

全部运行态材料保留在仓库外 `~/.backlink-autofill/runtime/wyrplay/live-20-20261010/`：
`before.json`、`after.json`、`consolidated-report.json`、`public-entry-check.json`、`opened-history-proof.json` 和测试/只读预检报告。
原 20 站运行 `batch-20261010-084123-dad5ff`，Owner 账号续接 `batch-20261010-084951-8016d6`，原范围三站认证复查 `batch-20261010-085109-24b606`。
范围授权、浏览器 profile、cookie、token、密码、邮件内容和敏感页面不提交 Git。
