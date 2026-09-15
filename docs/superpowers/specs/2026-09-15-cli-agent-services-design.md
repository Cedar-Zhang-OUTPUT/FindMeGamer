# FindMeGamer Agent Services — 设计规格

日期：2026-09-15。本文记录已确认的产品边界；技术选型是本轮实施方案，不代表已开发或发布。

## 1. 目标与非目标

提供 `fmg` CLI，让同事及 Agent 通过公司服务器使用 YouTube、X、Steam、公开商务邮箱补强、邮件发送。平台凭据只保存在服务器。CLI 不呈现 Library、Creator Profile、Game Profile、Match 等旧产品业务对象；分析和业务决策由调用它的 Agent 完成。

YouTube、X 的官方只读能力采用薄封装，保留参数与返回字段，不转换成旧 Profile 数据模型。不提供发帖、删除、关注等平台写操作。接口存在不等于公司的授权已覆盖：命令目录必须标明认证要求和实际可用状态。长连接流、二进制下载等非普通 JSON 请求先单独标记为不支持，不能伪装为已覆盖。

内部 Demo 质量标准：正常端到端、数据保存、避免重复执行及重复发信、明确的密钥泄露和 SSRF 风险、当前数据库迁移必须过关；不做多租户系统、无停机滚动升级、复杂运维控制台。

## 2. Skill 的明确分工

- **本次可直接编写：技术使用 Skill。** 教 Agent 发现命令、理解参数与字段、选择授权可用的 API、分页、控制调用上限、解释错误、等待任务、预览与确认发信。示例必须来自已实现并测试的 CLI。
- **用户已确认：业务工作流 Skill。** 按本文第 10 节实现，固定证据、去重、恢复、预算与发信确认边界；搜索策略与分析深度由 Agent 根据实际证据决定。
- 技术 Skill 不默认开始付费批量调用，不自动补充业务步骤，不把历史产品规则当作新工作流程。

## 3. 部署与隔离

建议 Go 实现独立二进制 CLI；Python 3.13 + FastAPI 实现新网关，Celery 执行邮箱任务。沿用服务器 PostgreSQL、Redis、HTTPS 代理，不新增云服务。

新服务目录 `agent-service/`，CLI 目录 `cli/`，技术 Skill 目录 `skills/fmg-api/`。新数据库 `find_me_gamer_agent`，新 Redis 命名空间和 `fmg_agent` 队列；不得消费旧客户端任务。旧 API、Worker、Beat 继续停止，备份保留，不删除旧库或覆盖旧配置。部署允许维护窗口。

旧系统仅作为可复用实现参考：HTTP/安全校验、平台认证、Gemini 邮箱补强、SMTP 传输。新服务不得依赖旧 Profile、Library、匹配和模板业务模型。

每位同事或 Agent 使用独立可撤销访问令牌。数据库只存令牌摘要，日志不含令牌、公司密钥、SMTP 密码。初期由服务器管理命令签发/撤销，无注册和账户界面。邮箱发送权限与只读权限分离。HTTPS 是携带令牌调用的前提。

## 4. CLI 与网关契约

命令族：`fmg youtube`、`fmg x`、`fmg steam`、`fmg email`；另有 `auth`、`version`、`upgrade`。提供 macOS/Linux 的 arm64、amd64 安装包及一行安装命令。

平台通用命令形态：

```sh
fmg youtube operations
fmg youtube describe search.list
fmg youtube call search.list --params '{"part":"snippet","q":"indie games","maxResults":5}'
```

具体 operation ID 以核验后的官方目录为准。CLI 帮助、服务校验、Skill 引用同一份目录。目录覆盖官方只读操作，测试状态分为 simulated、live-verified、requires-authorization、unsupported；新增目录不能把未实测标成实测。

`POST /v1/providers/{provider}/call` 接收 `{operation, params}`。默认只请求一页。可显式指定有限 `--max-pages`、`--max-items`；分页由 CLI 逐页请求，能中断，保留已完成结果。服务器只接受注册的上游主机、路径、HTTP 方法与参数位置，不接受任意目标 URL、客户端认证头或密钥参数。

stdout 输出 JSON，stderr 输出诊断。响应为 `{data, meta}`，`data` 保留上游字段，包括未知扩展字段和部分错误；`meta` 包含 request_id、分页游标、可得的限流信息和警告。错误结构为 `{error:{code,message,retryable,retry_after_seconds},request_id}`。缺少限流信息表示 unknown，不等于无限额度。

退出码：0 成功；2 参数错误；3 身份或权限；4 限流/余额；5 上游或网络；6 异步任务失败；7 发送结果未知。SDK 的上游错误须先脱敏。

配额不足停止。429 只在明确允许重试且等待时间在调用期限内时按上游提示有限等待；超时返回恢复建议，不无限占用进程。不为状态检查额外调用付费模型。不默认自动遍历整个账号或平台。

## 5. 邮箱补强

`fmg email enrich --url <public-creator-url>` 创建任务；`fmg email job <id> --wait` 等待/查询。输入为公开账号 URL 和可选平台、名称；不得要求先建 Profile。

顺序为公开主页/明确关联的商务页面提取，未找到再调用现有 Gemini 补强。只寻找公开商务联络邮箱，不猜地址、不检索私人泄露信息。结果支持多邮箱，每项含 email、purpose、source_url、discovery_method、verification_status。没有结果返回完成且空数组，而不是编造或无限补查。找到邮箱不代表验证投递成功。

任务与结果持久化，访问受令牌约束。用幂等键去除同一次请求的重复提交；成功步骤可复用，失败步骤可重试。超时、取消与服务重启要有明确终态或恢复路径，不能永久 running。保留期限配置为有限值，默认 30 天；只清理新服务任务记录，不碰旧数据库。

## 6. 邮件发送

服务端维护版本化模板目录与变量定义，CLI 获取模板并提交收件人及逐人变量生成预览；不依赖旧版 Profile 或观看证据数据库。`preview` 生成服务端不可变快照与 preview_id；`send --preview-id ... --confirm --idempotency-key ...` 才触发发送。预览显示全部收件人和正文，不能预览后静默换内容。用户在会话中一次确认明确的一批，不逐封重复询问；批量执行保留逐封回执。

SMTP 凭据服务器配置。发送状态至少 queued、sending、sent、failed、unknown。请求重复和并发不得重复投递；SMTP 接受后但确认丢失属于 unknown，不自动重发。超时重试 CLI 应查询已有发送记录。SMTP 未配置时预览可用，发送明确返回 configuration_missing。

本次不自动发真实邮件；验收真实投递前需用户指定测试收件人。旧 Yes/No 活动回调不是本版 CLI 必要能力，后续业务流程若需要再定义。

## 7. 交付与验收

依次交付：网关及官方目录 → CLI 只读能力 → 邮箱补强 → 发信预览/幂等 → 技术 Skill → 隔离端到端 → 部署/安装包/源代码发布。

真实核验用最少请求，记录平台、操作、时间和结果，不记录密钥。未授权的官方操作明确列出；SMTP 缺配置不伪称实投通过。从空白 macOS/Linux 安装、登录、读 API、异步邮箱任务、发送预览均需可复现证据。源代码和发行附件都上传 GitHub，下载安装的 SHA256 必须一致。

## 8. 已完成的旧系统停机边界

旧服务已停止；保留 PostgreSQL、Redis 和代理。服务器备份目录 `/var/backups/find-me-gamer/pre-cli-20260915/`，包括数据库、Redis、镜像与私有配置。校验过归档与摘要，尚未宣称完整恢复演练通过。含凭据的归档不得进入 Git 或公开下载。

## 9. 官方目录核验入口

- YouTube：https://developers.google.com/youtube/v3/docs
- YouTube 配额：https://developers.google.com/youtube/v3/determine_quota_cost
- X：https://docs.x.com/llms.txt
- X 限流：https://docs.x.com/x-api/fundamentals/rate-limits
- X 认证：https://docs.x.com/fundamentals/authentication/oauth-2-0/application-only
- Steam：https://partner.steamgames.com/doc/webapi/isteamwebapiutil?l=english

Steam Store 的 appdetails、类似产品等便利能力与正式 Steam Web API 分开标注来源和稳定性，不声称它们都是有正式保障的公共 API。配额及授权要求在实现时重新核验，不固化历史数字。

## 10. 已确认的 Agent 工作流增补

用户于本任务确认以下业务设计，并授权开始实施；本节替代此前“业务 Skill 等待定义”的状态。

### 本地记忆与搜索

- 以 Steam App ID 定位游戏；名字歧义才询问用户。生成 `game-profile.md`，包含事实、玩法/循环/受众等分析、Steam 相似推荐及来源和时间。事实与推断分开，本次推广需求不混入游戏事实。
- 每游戏目录有 `creator-index.json`；每轮 `runs/<run-id>/` 包含 `search-intent.json`、`progress.json`、`evidence/`、`matches/`、`usage.json`、`summary.md`；邮件材料保存在 `outreach/`。
- 搜索条件分硬约束、偏好、推导线索。Agent 可使用相似游戏、同义词、自主安排有限搜索与深挖；不擅自放宽硬条件。语言、作者地区、受众地区分别判断，缺失为 unknown。
- 默认首轮目标 20 位有依据的合适创作者，同时有有限调用预算，先触及任一边界即停止并汇报，不保证凑足人数。未指定预算时默认每平台最多 5 页搜索、100 位唯一账号详细读取、每位最多 10 条作品；邮箱补强最多 20 位。此为可调整的操作上限，不宣称固定金额上限；用户更严格限制优先。未知价格需在开跑前披露。
- 先发现/去重/基础筛选，再深挖可能合适者，最后补需要的邮箱。相似作品内容为强信号而非绝对资格；不得把标题简介写成完整观看体验。
- Match Brief 使用 JSON，保存身份、发现链路、筛选结果、证据、匹配理由/不足、多个联系邮箱及用途来源、游戏版本和 run ID；不保存冗长内部推理。
- 跨轮先查平台稳定账号 ID；不同平台同名不自动合并。区分已见、已推荐、已拒绝、已联系；条件变化允许重新评估。成功步骤持久化，恢复只处理未完成部分。
- 原始 API 数据落文件；给模型小规模摘要，按需读取证据，不将所有响应塞入上下文。保持上游要求的保存/更新边界，不把本地缓存当永久有效资料。

### 邮件、首次使用与成本

- API 已有公开商务邮箱直接保留；需要但缺失时走邮箱补强。完成且无结果才是 Not Found，失败/限流不得伪装为无邮箱。公开邮箱不代表已验证可投递。
- 首次实际调用 Skill 时简短说明找人、继续找、解释、补邮箱、邮件与打开主页能力，不承诺安装事件自动触发会话。
- 打开主页使用 Codex 浏览器能力，不必调用额外平台 API。直接给定账号评估、仅补邮箱、重评已有资料、暂停恢复均复用同一文件体系。
- 网关按客户端 run ID +令牌归属记录请求、计费用量与可用模型 usage。区分实测金额、估算及 unknown，记录计价版本，不将限流余额等同计费余额。
- YouTube 单独报告配额单位；X/模型按已知计价依据估算或使用可归属实际费用；未知不算零。Codex/Work 单任务用量不可获取时明示，账户共享额度变化不冒充本任务准确消耗。
- Skill 不自动启动付费遍历、不凭空编造商务证据、不自动确认真实发信；用户确认一批后允许在该范围内自动逐封执行。
