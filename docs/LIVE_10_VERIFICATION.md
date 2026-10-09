# WYRPlay 原顺序十站 LIVE 验收（2026-10-09）

接手及远端 main 基线均为 `9ea8df3ea9f0f29c2ec60950b47fdc0f5d22939d`。
上一轮16项未提交修改逐项审核，16保留并局部纠正、0删除、0暂缓、0未审核，见 LOCAL_CHANGE_REVIEW.md。
未 reset、重写数据库、删除 profile/锁或借用其他项目资料。

## 队列与执行边界

取消688/channel_basis硬门槛；正式队列按外链管理实际行顺序，缺渠道/入口/旧证据仍允许现场发现。
保留成功/审核中、历史Attempt、persistent intent、结果链接和已确认黑名单的保护。
本窗口冻结前10个可处理联合键，不借用 StartupFound/Matchbox，不进入第11个平台。
后续有限续跑仅推进这10站中尚未最终点击的记录，最终点击过的记录从不重投。

范围10 = approved1 + deferred6 + confirmed_reject0 + unknown3；unreviewed=0。
unknown3是已经执行后的结果/派发未知，不是未访问，更不是拒绝；6个deferred含1个人机挑战和5个系统未完成。
范围外19,093条未在本窗口重新审核，原状态完整保留，不作批量拒绝或压缩。

## 实际生产指标

| 指标 | 本窗口实证 |
|---|---:|
| 实际打开官网 | 10 |
| 填写业务发布资料 | 4 |
| 到达最终业务按钮 | 4 |
| 最终按钮点击 | 4（每站最多一次） |
| 确认最终业务请求 | 2 |
| Attempt 增量 | 2（Telegraph与Sideprojects各1） |
| 新公开成功 / 审核中 | 1 / 0 |
| 结果核查 | 3 |
| Owner实际挑战 | 1 |
| 系统暂缓 | 5 |
| 重复 Submit | 0 |

打开与填写是实际浏览器动作，不表示全部页面始终HTTP 200或认证均成功。
登录实证：The Hack Stack注册后专用profile显示Wang Yufei并可进入产品表单；
Sideprojects使用本窗口创建的账号资料，在同一context完成密码登录并进入发布表单。
Generic批次计数未识别这两次完成，不能拿旧计数器0或早期 beehiiv OAuth误计数作为实证。

## 每站记录：入口、认证、邮箱、字段与推进

“自动”指本窗口AI实际浏览器操作；没有把点击OAuth按钮当作登录成功。
Gmail列说明本次验证需求及实证，未触发验证码不能填写成“成功获取”。

| 顺序/行 | 平台 | 打开与实际入口 | 登录方式及完成 | Gmail/验证码 | 实际填写 | Next/Continue |
|---|---|---|---|---|---|---|
| 1 / 803 | ebool.com | 是；Submit→免费/start→Review & Submit | 自动填新账号密码；账号最终建立未确认 | 实际查询无本轮对应邮件；OTP未完成 | 名称、URL、联系邮箱、运营者、国家、描述、Education分类；可选logo未上传 | 是；有界多页推进，最终复核再推进一次 |
| 2 / 805 | toollisted.com | 是；Submit→/auth/login→现场Sign up链接/register | 自动填写新账号资料；注册响应未确认，登录未确认 | 无可确认的OTP要求或获取 | 注册名称、邮箱和密码；未确认业务表单填写 | 无业务Next |
| 3 / 806 | beehiiv.com | 是；首页/features/link-in-bio及实际signup路径；未到发布页 | 尝试正常认证/OAuth；未确认登录完成 | 未取得本轮OTP/magic link闭环 | 未确认业务字段填写 | 未完成业务多步 |
| 4 / 807 | thehackstack.com | 是；注册后www站点实际/add-product | 自动新账号注册；专用profile可见Wang Yufei并能进入产品表单；裸域流程另行退回登录 | 未要求本次验证码 | 名称、URL、短标题、253词描述、主图、logo、5截图、真实归属 | 单页表单 |
| 5 / 808 | telegra.ph | 是；首页直接文章编辑/Publish | 匿名，无需登录 | 不需要 | WYRPlay标题、正式长描述、真实官网锚点 | 单页编辑 |
| 6 / 809 | sideprojects.net | 是；/projects/submit→login→现场/register | 自动设置品牌用户名；密码登录后同一context到发布表单 | 未要求本次验证码 | URL、名称、短标题、正式长描述、4截图、Games；免费队列保留默认日期 | 单页发布；未选付费日期 |
| 7 / 810 | dreamwidth.org | 是；首页实际Create a free account→/create；未到发布页 | 免费注册页超时/曾返回504；未完成认证 | 未取得本轮OTP/magic link闭环 | 未确认业务字段填写 | 未到业务Next |
| 8 / 811 | wordpress.com | 是；实际/start→log-in/zh-cn | 页面实际Checking your browser挑战，未完成 | 尚未进入邮件验证 | 未确认业务字段填写 | 卡在浏览器挑战 |
| 9 / 812 | promoteproject.com | 是；实际Submit startup打开Google流程 | 尝试已有Owner专用profile与Google标识页；session/consent未确认 | 未取得本轮OTP/magic link闭环 | 认证标识字段；未到产品表单 | 未到业务Next |
| 10 / 813 | astrodir.com | 是；首次读到Astrology/Tarot/Bazi/AI目录；后续官网加载失败 | 未确认需要登录或完成 | 未触发确认的验证码流程 | 未确认业务字段填写 | 未完成业务多步 |

## 每站记录：最终按钮、请求、Attempt、结果与具体卡点

| 平台 | 到达最终Submit | 点击 | 业务请求实证 | 最终Attempt | Sheet结果 | 实际卡点/证据 |
|---|---|---:|---|---|---|---|
| ebool.com | 是 | 1 | 未确认 | 空白，增量0 | 需人工核查 | 免费Review页面提交后无回执；当时验证码二进制请求读取错误，后已修代码；保留intent，未重投 |
| toollisted.com | 否 | 0 | 无最终请求 | 空白，增量0 | 暂时不可用 | /auth/register仍显示注册表单；认证传输已推进但账号建立未确认；额外Sign in链接定位超时，属于系统工作 |
| beehiiv.com | 否 | 0 | 无最终请求 | 空白，增量0 | 暂时不可用 | signup/认证推进达到有界上限，未进入可发布页面；不是Owner必须输入密码的确认 |
| thehackstack.com | 是 | 1 | 元数据未确认 | 空白，增量0 | 需人工核查 | 点击后真实页面返回The cat field is required.；不是发布成功。随后修正Community并只读填表核验，未重投 |
| telegra.ph | 是，Publish | 1 | POST edit.telegra.ph /save | 1 | 成功 | 匿名E4公开页面含WYRPlay官网链接；已精确回读 |
| sideprojects.net | 是，Submit for launch | 1 | POST sideprojects.net /projects/submit | 1 | 需人工核查 | 现场原生form action绑定、真实POST已观察；无新回执或公开listing，已提交待核实，保留intent |
| dreamwidth.org | 否 | 0 | 无最终请求 | 空白，增量0 | 暂时不可用 | 免费/create页面超时/504，worker TimeoutError；保留系统暂缓，不误称Owner密码缺失 |
| wordpress.com | 否 | 0 | 无最终请求 | 空白，增量0 | 去人工 | 实际Checking your browser挑战，需要Owner完成验证 |
| promoteproject.com | 否 | 0 | 无最终请求 | 空白，增量0 | 暂时不可用 | Google session/consent未确认，未进入产品提交表单；不宣称OAuth成功 |
| astrodir.com | 否 | 0 | 无最终请求 | 空白，增量0 | 暂时不可用 | 目录内容偏占卜/AI且后续页面不可用；本轮未提升永久不适用或全局黑名单 |

确认业务Submit=2，最终点击=4。不能把ebool/Hack Stack未确认派发计成Attempt，不能把
Sideprojects未确认结果计成审核中。Hack Stack有服务端校验错误页面，但没有保存可认定的请求元数据。
三站结果核查与WordPress的人机挑战分开；五个普通认证/页面技术问题仍是系统暂缓。

## Gmail、OAuth和系统验证

Gmail已连接工具真实profile/search成功，host→stdin→CLI内存往返已验证；ebool的对应查询真实返回0封。
没有另建OAuth，没有将验证码、cookie、token或新账号密码写入Sheet/仓库/凭据文件。
本轮真实OTP/magic link完成=0；Google OAuth完成未验证。Fixture的成功不替代这些结论。
新平台密码使用Owner授权的内存值自动填写；主Google账号重新认证、2FA或实际挑战保留Owner边界。

首提无需预存matcher/handler证明；Telegraph现场请求建立派发证据。
Sideprojects采用当前页面原生form action作为现场绑定并观察真实POST，未猜测接口。
The Hack Stack及ebool的未知结果保留单次intent；后续读取/填表验证不是再点击。

最终代码检查：ruff check、ruff format --check、mypy（18个源文件）PASS；224 pytest PASS（127.82秒）。
只读preflight：资料包3.0-final PASS、三表真实读取、匿名headless WYRPlay HTTP200、profile未触碰。
Hack Stack最终修正的真实只读填写回读：描述253词、Community勾选、5张截图、归属勾选、表单gate通过、final_click=0。
这些验证不代表Hack Stack重新提交成功，也不代表可扩大批量。

## Sheet、防重复和范围回读

本窗口前后WYRPlay项目总数19,103；十站联合键逐一核对，A:J真实回读，Attempt仅两站各+1。
四个按project×platform唯一命名的intent保留；四次final点击都没有第二次点击，重复Submit=0。
正式总表与黑名单前后内容哈希相同；除这十站外执行表所有项目的行内容哈希相同。
因此范围外修改=0、跨项目修改=0、黑名单新增=0，既有成功/Attempt记录未改变。
详细hash、精确键/行、最终状态与各intent派发元数据保留在仓库外 after.json。

外部证据根：`~/.backlink-autofill/runtime/wyrplay/live-10-20261009/`。
首轮实际十站证据：`batch-20261009-074609-c543c4`；后续仅原十站有限继续。
Telegraph E4：`batch-20261009-074609-c543c4/telegra.ph/followup-proof.json`。
ebool/Hack Stack/Sideprojects最终记录：同验收目录的 `ebool-final`、`hackstack-final`、`sideprojects-final`。
公开成功链接：<https://telegra.ph/WYRPlay-10-09>。
敏感运行页面、账号资料、grant、profile和Sheet完整备注不加入Git。

## 结论

本窗口已完成原十站实际尝试并记录所有具体卡点，确认Submit大于0；不判定零Submit FAILED。
已证明受限范围内真实打开、填写、点击、业务POST、E4与Sheet回读可以执行。
整体仍NOT READY FOR EXPANDED ROLLOUT：普通认证可靠性、部分提交派发与结果识别、真实OTP/magic link和Google OAuth尚未验证。
按Owner要求完成提交/push main后停止，不自动执行下一批。
