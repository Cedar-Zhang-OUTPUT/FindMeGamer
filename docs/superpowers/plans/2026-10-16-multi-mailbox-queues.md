# Multi-mailbox Queues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 两个 Agent 可同时通过 CLI 使用独立邮箱与明确模板发送邮件，Gemini 补全不再争用发信执行位。

**Architecture:** 一套 API/PostgreSQL/Redis，私有邮箱注册文件与持久身份绑定；独立补全 Worker、每邮箱发送 Worker、单一调度器和独立监控服务。现有发送锁、幂等及安全暂停保持为所有入口共用的最终保护。

**Tech Stack:** 现有 Python 3.13、FastAPI、Pydantic Settings、SQLAlchemy/Alembic、PostgreSQL、Celery/Redis、Go CLI 和 Python/HTML Skill 页面；不引入新供应商 SDK。

**Spec:** `docs/superpowers/specs/2026-10-16-multi-mailbox-queues-design.md`（2026-10-16 已由用户确认）。

## Global Constraints

- 每个启用邮箱独立配置、独立发送队列，各 2 个执行位，供正常发信和退信重试共用。
- Gemini 补全独立队列，4 个执行位；不增加单任务检索预算或自动重试次数。
- 收信与退信监控独立运行，不占用发送或补全执行位。
- 默认发送间隔仍为 5 秒，同一邮箱所有 API/Worker/重试共享发送锁，两个执行位不绕过该间隔。
- 退信一次重试、30 秒等待、现有失败阈值、无效地址排除、保护暂停保持原规则；unknown 不自动重发。
- 不改变历史正文、图片、receipt、审批 revision、幂等键、暂停状态；仅添加可验证的身份关联。
- 现有 LIMINAL 固定正文、签名图和尾图不变，其他游戏的通用模板保留。
- 本地实现和自动化测试不访问真实 Gemini，不实际发邮件，不启动用户已停用的本地 FMG Docker 服务。
- 第二邮箱未提供配置则禁用；不得继承第一邮箱凭证；不得自动跨邮箱重发或恢复历史暂停批次。
- CLI、交互页面、接口说明与 `fmg-api` / `fmg-research` Skills 同一版本交付；不恢复 Reply 展示。
- 真实 PostgreSQL/Redis 测试不可用时标记未验证，禁止仅凭 SQLite/模拟通过部署。
- 现有访问 token 所有权保持不变；两个独立批次相同联系人不在本期新增自动去重范围内。

## Review Focus

1. 历史幂等请求再次提交：不能因新增 mailbox_id 改变指纹而误建或破坏旧审批（任务 2）。
2. 注册文件修改/禁用与进程旧配置并存：同 ID 改地址、凭证路径复用必须失败关闭（任务 1、3、8）。
3. SMTP/Graph 已提交后进程退出、消息重投：不能把 unknown 当失败自动重发（任务 3、5、7）。
4. 两邮箱相同 IMAP UID 或跨邮箱转发：游标和回执匹配不能污染另一邮箱（任务 4）。
5. 旧队列积压和单封 API 在部署时仍发送：闸门、排空与迁移不能遗漏绕过 Worker 的入口（任务 5、8）。

## 执行约定与文件边界

工作目录：现有干净 checkout `.worktrees/native-profile-editing`，计划基线 `00c3980`（实施开始重新检查 git 状态、AGENTS.md 和远端变化）。不清理用户未提交文件，不另启生产测试任务。

下文 `A` 表示 `agent-service/src/fmg_agent`，`T` 表示 `agent-service/tests`。命令 `cd agent-service && .venv/bin/pytest …` 均相对仓库根目录；开始执行时先验证该解释器为 Python 3.13。若环境缺失，报告依赖，不用生产容器运行写入测试。

新模块职责：`A/mailboxes.py` 解析私有配置与公开摘要；`A/email/identity.py` 固化身份并解析历史归属；`A/dispatch.py` 调度及 leader 锁；`A/email/monitor.py` 分邮箱监控；`A/mail_runtime.py` 运行控制与就绪检查。保留现有 `sending.py` 为所有发送入口的共享保护，不复制一套发送业务。

依赖顺序：1 → 2 → 3 → 4 → 5 → 6 → 7 → 8。每个任务独立经过红/绿测试与提交；所有测试名称与断言以下文为合同，测试辅助对象统一放在测试模块，不给生产添加仅供测试的分支。

### Task 1: 独立邮箱配置与安全发现接口

**Files:** 新建 `A/mailboxes.py`、`T/test_mailboxes.py`；修改 `A/config.py`、`A/app.py`、`A/email/routes.py`、`deploy/agent-services/env.example`。

**Interfaces:**
- `MailboxProfile`：`id: str`、`enabled: bool`、`display_name: str`、`allowed_templates: list[str]` 和设计文档列出的各邮箱发信/收信配置；秘密字段 `repr=False`，不整体序列化为公开响应。
- `MailboxRegistry.load(settings: Settings) -> MailboxRegistry`；`select(mailbox_id: str | None, *, allow_legacy: bool) -> MailboxProfile`；`settings_for(mailbox_id: str) -> Settings`（显式替换全部邮件配置，不继承另一邮箱字段）；`public_entries() -> list[dict]`。
- 新增 `Settings.mailboxes_file: Path | None`。未配置文件时只生成兼容邮箱 `ontologyplay`，对应原 Settings；启用注册文件后邮箱配置完全来自各项，默认 SMTP/IMAP 密码为空。
- `GET /v1/email/mailboxes` 要求 `email:send`，返回 `{data: [...], meta: {request_id, mailboxes_version: 1}}`；公开字段仅 `id, from, display_name, enabled, ready, allowed_templates, send_interval_seconds`。

- [ ] **1. 写失败测试**：`test_registry_isolates_credentials` 断言两个邮箱的 host/password/token path 各自匹配且 B 缺密码不回退到 A；`test_rejects_duplicate_identity_and_token_paths` 覆盖大小写地址重复、Graph/IMAP 同路径及跨邮箱复用、非法 ID、符号链接解析后重复；`test_public_mailboxes_redacts_secrets` 断言原密码与路径均不出现在 JSON/日志/异常；`test_multi_mailbox_requires_selection` 断言省略 ID 返回 `mailbox_selection_required`，单邮箱兼容可解析。
- [ ] **2. 验证 RED**：`cd agent-service && .venv/bin/pytest tests/test_mailboxes.py -q`，确认因缺少功能失败，而非依赖/语法错误。
- [ ] **3. 实现接口**：ID 匹配 `^[a-z][a-z0-9-]{0,39}$`；配置文件非公开可读、token store 绝对路径且唯一；畸形文件整体拒绝启动，合法但未配置完整的 disabled 项可保留。明确错误 `mailbox_not_found` / `mailbox_disabled` / `mailbox_configuration_invalid`，不回显输入。认证 ready 检查不得刷新 token 或外调上游。
- [ ] **4. 验证 GREEN**：运行任务测试及 `tests/test_auth.py tests/test_microsoft_mail.py tests/test_graph_mail.py`，全部通过。
- [ ] **5. 提交**：仅本任务改动，`feat: add isolated mailbox registry and safe discovery`。

### Task 2: 持久身份、历史迁移及任务审批绑定

**Files:** 新建 `A/email/identity.py`、`agent-service/migrations/versions/0012_mailbox_identity.py`、`deploy/agent-services/mailbox_preflight.py`、`T/test_mailbox_migration.py`、`T/test_mailbox_outreach.py`；修改 `A/email/models.py`、`A/email/routes.py`、`A/outreach.py`、`A/email/sending.py`。

**Interfaces:**
- `MailboxIdentity` 表：稳定 `id` 与唯一规范化 `sender`，无密码。`EmailPreview.mailbox_id` / `OutreachTask.mailbox_id` 新关联列；发送/重试通过 preview 取身份，不存第三份可漂移配置。
- `register_identities(session, registry) -> None`：同 ID 改 sender 或同 sender 改 ID 拒绝；配置禁用不删除历史身份。
- `preview_mailbox(session, preview, registry) -> MailboxProfile`；`backfill_mailboxes(session, registry, *, apply: bool = False) -> dict` 返回计数与原字段摘要核对结果，dry-run 不写入。
- `TaskInput` / `PreviewRequest` 增加可选 `mailbox_id` 仅用于兼容旧请求；新记录必须持久填写。JSON 响应增加邮箱、显示名称、模板版本。

- [ ] **1. 写失败测试**：`test_backfill_preserves_frozen_approval` 用旧 migration 构造任务与单封预览，迁移后断言 revision/fingerprint/message/receipt/暂停摘要逐项相同；`test_mixed_or_unmapped_from_aborts_backfill` 断言无部分写入；`test_new_task_fingerprint_includes_mailbox` 断言同键换邮箱 409；`test_legacy_idempotency_replay_returns_original` 断言旧请求重放返回原 ID/原 revision，无新预览。
- [ ] **2. 验证 RED**：`cd agent-service && .venv/bin/pytest tests/test_mailbox_migration.py tests/test_mailbox_outreach.py -q`；真实迁移部分须指定隔离数据库。
- [ ] **3. 实现迁移与绑定**：0012 仅创建表及 nullable 历史关联列；部署工具在静默窗口精确回填并核对零未映射记录，才允许新调度器就绪。新建请求必须非空落库；尚未回填的记录禁止发送。旧请求重放先按 owner/key 查原记录并使用旧指纹算法核对，不能改变原记录来凑新算法；新请求统一纳入 mailbox_id 与 display_name 的确认摘要。
- [ ] **4. 验证 GREEN**：任务测试与 `tests/test_migrations.py tests/test_outreach.py tests/test_outreach_compact.py tests/test_email_sending.py` 全通过；大任务 summary 仍不读取图片 JSON。
- [ ] **5. 提交**：`feat: bind mailbox identity to approved outreach and previews`。

### Task 3: 发信、显示名称、模板许可与安全隔离

**Files:** 修改 `A/email/sending.py`、`A/email/smtp.py`、`A/email/graph.py`、`A/email/mime.py`、`A/email/safety.py`、`A/email/retries.py`、`A/outreach.py`；新建 `T/test_mailbox_delivery.py`。

**Interfaces:**
- 所有 `SendStore.send(...)` 调用从持久预览解析 `MailboxProfile`，再调用 `settings_for(id)`；直接 `/v1/email/sends` 保持现有同步回执语义，但同样走身份、闸门与共享发送锁，不另开绕过路径。
- `process_recipient(..., *, expected_mailbox_id: str | None = None)` 与 `process_retry(..., *, expected_mailbox_id: str | None = None)`；Worker 必须传入自身 ID，直调 API 不用队列 ID 但仍校验预览身份。
- 冻结消息增加 `from_name`；`build_message` 用安全格式化名称，拒绝 CR/LF 注入，信封地址和 Message-ID 关联仍使用裸地址。

- [ ] **1. 写失败测试**：`test_transport_uses_bound_profile` 断言 A Graph、B SMTP 收到各自配置/From；`test_wrong_worker_never_calls_transport` 断言调用数 0；`test_identity_or_template_changed_blocks` 覆盖改地址、禁用、模板不允许、OAuth 实际账号不符；`test_unknown_and_sent_replay_never_deliver_again` 断言各自只有原一次调用；`test_pause_affects_only_bound_mailbox` 断言 A 暂停、B 可发送。
- [ ] **2. 验证 RED**：`cd agent-service && .venv/bin/pytest tests/test_mailbox_delivery.py -q`。
- [ ] **3. 实现统一校验**：冻结姓名与当前姓名不一致须重新预览；认证轮换不改正文/revision。LIMINAL 模板允许列表仅现有邮箱；通用模板需要显式许可。错队列返回无发送的结构化诊断，不把另一邮箱任务误标 blocked。重试子预览继承 mailbox_id/from_name；不要清除现有 pause/retry 计数。
- [ ] **4. 验证 GREEN**：任务测试及 `tests/test_send_pacing.py tests/test_graph_diagnostics.py tests/test_bounce_retry.py tests/test_bounce_safety.py tests/test_invalid_recipients.py tests/test_liminal_fixed_copy.py tests/test_liminal_banner.py tests/test_smtp_delivery.py` 全通过。
- [ ] **5. 提交**：`feat: isolate mailbox delivery credentials templates and retry safety`。

### Task 4: 独立收信服务与跨邮箱关联保护

**Files:** 新建 `A/email/monitor.py`、`T/test_mailbox_monitor.py`；修改 `A/email/inbox.py`、`A/worker.py`。

**Interfaces:**
- `monitor_mailbox(settings: Settings, mailbox_id: str, stop: Event) -> None`；`run_monitors(settings: Settings, stop: Event) -> None` 按启用邮箱创建一个受控循环。
- `matching_send(session, message, *, mailbox_id: str)` 和 `ingest(..., *, mailbox_id: str)` 只关联同邮箱发送；保留现有 host/username/folder 游标散列，避免重新扫描历史邮箱。
- 每 mailbox_id 独立 PostgreSQL advisory leader 锁；第二个监控进程不得重复扫描同邮箱。公开健康信息不携带原始邮件内容或认证异常。

- [ ] **1. 写失败测试**：`test_same_uid_across_mailboxes_is_independent` 断言两条回执归属各自邮箱；`test_foreign_reference_does_not_pause_other_mailbox` 断言转发/引用不串账；`test_stalled_a_does_not_stop_b_monitor` 用 Event 卡住 A，断言 B 在释放 A 前更新游标；`test_existing_cursor_is_preserved` 断言升级不重置 UID；`test_duplicate_monitor_has_one_owner` 在 PG 验证 leader。
- [ ] **2. 验证 RED**：`cd agent-service && .venv/bin/pytest tests/test_mailbox_monitor.py -q`。
- [ ] **3. 实现监控入口**：网络调用有超时，stop 可退出，单邮箱错误只更新该邮箱健康状态；Worker 不再自动启动 inbox_loop。停止/重启恢复原游标，不批量重放过去退信。
- [ ] **4. 验证 GREEN**：任务测试及 `tests/test_inbox.py tests/test_bounce_safety_postgres.py` 全通过；无 PostgreSQL 时该门未通过。
- [ ] **5. 提交**：`feat: run mailbox monitors independently with scoped correlation`。

### Task 5: 队列拆分、角色进程与维护闸门

**Files:** 新建 `A/dispatch.py`、`A/mail_runtime.py`、`agent-service/migrations/versions/0013_mail_runtime.py`、`T/test_queue_isolation.py`、`T/test_mail_runtime.py`；修改 `A/worker.py`、`A/outreach.py`、`A/email/retries.py`、`A/email/sending.py`、`deploy/agent-services/compose.yaml`。

**Interfaces:**
- `queue_for_mailbox(mailbox_id: str) -> str` 返回 `fmg_mail.ID`；`worker_args(role: str, mailbox_id: str | None) -> list[str]` 只允许 `enrichment`（4）或 `mail`（2）。角色命令 `python -m fmg_agent.worker --role mail --mailbox ID`，补全用 `--role enrichment`；独立入口 `python -m fmg_agent.dispatch` 和 `python -m fmg_agent.email.monitor`。
- `pending(sessions, *, mailbox_id: str)`、`pending_retries(sessions, *, mailbox_id: str)` 按身份筛选；调度器每轮对每邮箱取至多 20 条，每 10 秒一轮，补全也至多 20 条；轮询顺序不导致一个邮箱饿死。
- `dispatch_once(settings, sessions, publish) -> dict` 返回按队列发布计数；单一 PG advisory leader 锁贯穿调度循环，失去数据库连接则停止发布。
- `MailRuntime` 单行持久控制：`dispatch_enabled` / `send_enabled`，迁移默认均 false；`set_runtime(sessions, *, dispatch_enabled: bool, send_enabled: bool) -> dict` 仅管理员工具调用；发送入口在实际发送前共享锁校验，关闭闸门获取排他锁后保证没有新发送穿过。禁发返回 `mail_service_maintenance`，不创建发送尝试、不重写任务审批。

- [ ] **1. 写失败测试**：`test_worker_routes_and_concurrency` 断言 enrichment=4、mail A/B 各2且不消费彼此队列；`test_dispatch_filters_each_mailbox` 断言发布 ID 与 DB 归属一致；`test_second_dispatcher_does_not_publish` 在 PG 持锁竞争只一方发布；`test_send_gate_blocks_api_and_worker` 断言闸门关闭直接 API/批次/重试上游调用均0；`test_broker_failure_preserves_pending` 断言 DB 待办未丢失。
- [ ] **2. 验证 RED**：`cd agent-service && .venv/bin/pytest tests/test_queue_isolation.py tests/test_mail_runtime.py -q`。
- [ ] **3. 实现角色与部署配置**：去除 worker_ready 内置线程；Compose 分离四种角色，第二邮件 Worker 通过显式 profile 启动，未配置不启动；各进程就绪校验注册身份/迁移/schema，发布预算/任务超时仍保留。邮件 Worker 不消费旧 fmg_agent 队列；遗留队列由任务8审计迁移。
- [ ] **4. 验证 GREEN**：任务测试及 `tests/test_email_worker.py tests/test_send_pacing_postgres.py tests/test_deploy_tools.py` 全通过，真实队列饱和验证由任务7完成。
- [ ] **5. 提交**：`feat: isolate enrichment and mailbox workers with guarded dispatch`。

### Task 6: CLI、页面与两套 Skill 的一致选择合同

**Files:** 修改 `cli/internal/email.go`、`cli/internal/email_sending.go`、`cli/internal/outreach.go`、`cli/internal/command.go` 及对应 `_test.go`；`skills/fmg-api/scripts/outreach_dashboard.py`、`outreach_dashboard.html`；两套 `skills/{fmg-api,fmg-research}/SKILL.md` 和各自 `references/outreach.md`、`references/email-template.md`；`skills/fmg-api/references/email.md`、`cli/README.md`、`docs/agent-services/AGENT-INSTALL.md`；新增 `docs/agent-services/mailboxes-api.md`、`T/test_mailbox_dashboard.py`。

**Interfaces:**
- `fmg email mailboxes` 调用任务1接口；新 CLI 遇到旧服务无该能力时明确更新提示，不推断已支持。
- `outreach task create` 保留 `--input` / `--idempotency-key`，新增 `--mailbox` / `--template` / `--template-version`；与 JSON 中 `mailbox_id/template_id/template_version` 合并，相等允许、不同拒绝、缺必填拒绝。
- 单封 preview 同合同；send/start 仍基于原 preview/task ID 与用户确认，不提供切换 mailbox flag。
- API 文档记录发现与请求/响应 schema，不往仅存平台 API 的 `api-catalog` 塞无关服务。页面渲染冻结邮箱/模板信息，汇总接口保持轻量。

- [ ] **1. 写失败测试**：Go `TestMailboxSelectionRequired`、`TestMailboxFlagsConflictWithJSON`、`TestMailboxDiscoveryOldServer` 断言错误时不发送创建请求；`TestTaskStartCannotOverrideMailbox` 拒绝 override；`test_dashboard_shows_frozen_mailbox_and_template` 断言显示身份且不显示 Reply/秘密；将 CLI 真实示例加入 `cli/tests/skill_examples.sh` 对应离线场景。
- [ ] **2. 验证 RED**：`cd cli && go test ./internal -run 'Mailbox|TaskStartCannotOverride'`；`cd agent-service && .venv/bin/pytest tests/test_mailbox_dashboard.py -q`。
- [ ] **3. 实现接口与文档**：改 Skill 前执行 `skill-creator` / `writing-skills` 的适用流程，明确使用目的；文档固定新客户端必须显式邮箱，两个 Agent 划分联系人、稳定幂等键、不自动切换发件账号。创建草稿不代表已同意发送，start/send 前仍需用户确认。现有升级器负责同步 Skills，不另建凭证安装流程。
- [ ] **4. 验证 GREEN**：`cd cli && go test ./... && go vet ./...`；运行页面、workflow、outreach 回归及 `sh cli/tests/skill_examples.sh`（须先通过任务7隔离环境检查），验证 help 和真实 CLI 请求，不仅匹配文档字符串。
- [ ] **5. 提交**：`feat: expose explicit mailbox template selection across CLI and skills`。

### Task 7: 双 Agent、真实队列和资源隔离验收

**Files:** 新建 `T/mailbox_runtime_fixture.py`、`T/test_multi_agent_mailboxes.py`、`T/test_queue_isolation_integration.py`；修改 `T/test_release_container.py`、`T/email_worker_fixture.py` 与必要的现有集成 fixtures。

**Interfaces:**
- fixture `mailbox_runtime` 提供隔离 PG schema/Redis命名空间、两个独立 CLI 配置目录/token、真实 API+角色子进程与虚拟上游；`run_cli(agent, args) -> CompletedProcess`、`provider_calls(mailbox_id) -> list[dict]`、`block_enrichment()/release_enrichment()` 用 Event/IPC 条件同步。只使用测试进程启动工厂注入虚拟 transport，不给生产开放测试 URL 绕过开关。
- 必须连接名为 `find_me_gamer_agent_test` 的隔离 PG 及专用 Redis，绝不 FLUSHALL/清生产 key。若本机无服务，不启动已停 Docker；请求可用测试环境后再继续该验收门。

- [ ] **1. 编写并观察 RED**：`test_two_agents_separate_tokens` 断言创建各自任务、对方 get/start 返回404/403；`test_two_agents_shared_token_same_key` 用并发 barrier 断言同请求同 ID、变邮箱409；`test_duplicate_start_and_send` 断言每 preview 上游调用≤1、重复队列与不同 send key 亦然。先用原单队列版本或隔离分支运行同一测试证明缺失能力，保存失败证据，不修改生产版本。
- [ ] **2. 编写节流与暂停断言**：`test_same_mailbox_combines_api_batch_and_retry_pacing` 断言相邻调用开始不早于上次结束+5秒；`test_two_mailboxes_overlap` 用 barrier 证明两邮箱可重叠；`test_a_failure_leaves_b_progressing` 逐一模拟429/禁用/退信保护，断言 A 无后续调用且 B 成功。
- [ ] **3. 编写队列与恢复断言**：`test_four_blocked_enrichments_do_not_block_mail` 等待四个补全调用已进入，提交两邮箱任务，断言在释放补全前两邮箱已开始调用；`test_worker_loss_keeps_unknown_unreplayed` 模拟提交后崩溃再投递，断言未再次调用；`test_old_expired_message_keeps_pending_recoverable` 断言数据库任务不因队列 expires 丢失。
- [ ] **4. 运行 GREEN 与修复**：`cd cli && go build -o fmg ./cmd/fmg`；`cd agent-service && FMG_AGENT_TEST_CLI=../cli/fmg .venv/bin/pytest tests/test_multi_agent_mailboxes.py tests/test_queue_isolation_integration.py -q`。修复所属任务生产代码并先保留失败测试；报告全部 skip，必需的 PG/Redis 场景一个也不能跳过。
- [ ] **5. 资源验证**：同机同隔离环境分别运行20封虚拟单邮箱基线与双邮箱+20条虚拟慢补全，采集 CPU、峰值 RSS、DB 连接数、队列等待 p95、积压排空情况；发信等待相对基线 p95 不增加超过一轮10秒调度，所有任务有终态且无重复。资源条件为无 OOM、连接峰值<测试配置 max_connections 的70%、整组进程峰值RSS≤2 GiB；这只是预部署预算，不把虚拟吞吐当真实提供商能力。
- [ ] **6. 提交验收记录**：`docs/agent-services/multi-mailbox-acceptance-20261016.md` 记录环境/命令/通过失败跳过/资源数据/无真实外调，`test: verify concurrent agents and isolated mailbox workers`。

### Task 8: 全套回归、发布包和生产安全切换

**Files:** 新建 `deploy/agent-services/mail_runtime.py`、`queue_cutover.py`、`mailboxes.example.json`、`docs/agent-services/multi-mailbox-deployment.md`；修改 `deploy/agent-services/deploy.sh`、`rollback.md`、`smoke.sh`、`T/test_deploy_tools.py`、`cli/tests/test_release_bundle.py`、`.github/workflows/agent-cli-release.yml`（仅需要时）；补充任务7验收记录。

**Interfaces:**
- 管理命令 `mail_runtime.py status|hold|release`：hold 关闭两闸门；release 要求身份回填完整、Worker/监控就绪、schema匹配，不清除 SenderSafety、不批准任务。
- `queue_cutover.py audit` 默认只读：列出旧队列三类任务 ID、可识别/未知类型数、DB状态聚合；`migrate --manifest FILE --confirm` 仅处理已审计清单。运行前必须旧 producer/consumer 已退出，快照可恢复；按当前 DB 状态路由 queued enrichment、已批准且无发送尝试的 recipient、合法 due retry。sent/unknown 不重放，未知类型停止并报告。不用 purge/FLUSHALL；成功发布后方可按清单确认旧消息，跨 Redis 操作失败依靠原 DB 幂等防重复并记录待核对。

- [ ] **1. 写部署失败测试**：`test_cutover_refuses_inflight_send`、`test_queue_audit_unknown_type_blocks`、`test_release_refuses_unmapped_identity`、`test_rollback_refuses_legacy_worker_with_second_mailbox`，断言非零退出且未更改原任务；`test_maintenance_keeps_read_only_status_available` 断言读可用、所有发送入口无调用。
- [ ] **2. 实现并验证工具**：在虚拟环境演练旧版本升级、温和退出、迁移、重复执行、断点重启、备份恢复；只有命名的测试 schema/队列可清理，远端生产切换尚不执行。
- [ ] **3. 运行完整测试**：`cd agent-service && .venv/bin/pytest`（带任务7真实隔离服务变量）；`cd cli && go test ./... && go vet ./...`；`agent-service/.venv/bin/python -m pytest cli/tests/test_release_bundle.py cli/tests/test_installer.py`；Skill可执行示例、浏览器预览回归及容器备份/恢复演练。实施前读取 verification-before-completion；任何失败按名称报告，任何关键 skip 阻止上线。
- [ ] **4. 构建发布候选**：暂定 `fmg-v0.8.0`，开始发布前检查远端 tag 未占用；`sh cli/scripts/build-release.sh fmg-v0.8.0 .local/releases/fmg-v0.8.0` 仅产本地包，验证4平台 CLI、Skills包和SHA。在临时目录验证安装/升级保留认证、Skills版本一致。发布前用户审阅实际测试结果与停机切换窗口。
- [ ] **5. 生产只读预检与停机闸门**：核对当前任务、在途尝试/发送锁、旧队列、镜像与资源，备份数据库/配置。旧 API 无新维护闸门，须在代理临时阻止发信及任务/补全写入口（读回执保留），停止已有 API 写入并等待在途完成；旧 Worker 发起 warm shutdown，等待任务退出。绝不在620秒到点强杀，若未排空则停止部署、保留证据并请用户处理。旧调度线程随旧进程退出，退出后才快照队列。
- [ ] **6. 迁移并静默启动**：执行schema及归属回填、验证原摘要/零未映射；新角色在闸门关闭时启动，仅现有 mailbox 启用；旧队列按审计清单迁移。验证 API、各角色健康及5秒间隔、2/4并发配置，检查第二邮箱缺配置仍禁用，确认不发生实际外调。
- [ ] **7. 发布和恢复边界**：在用户确认的窗口切换代理，解除维护闸门仅恢复切换前已批准且未受保护暂停的待办；若仍无恢复授权则保持 hold，报告部署就绪。发布同源 CLI/Skill release 与升级说明，创建PR时按工具要求附加PR。无测试邮件/付费检索授权不得用真实调用验证；第二邮箱接入另行获取安全配置和授权。
- [ ] **8. 回滚与交付核对**：保护暂停/审批/unknown 数量不变，历史内容摘要不变，新旧队列待办守恒；若不满足，先 hold，不启动旧单邮箱 Worker 猜测恢复。分开报告代码测试、CLI/Skill发布、服务器部署、第二邮箱授权四项结果，并提供用户可执行的实际版本命令。

## 计划自检与执行选择

覆盖映射：设计1–3→任务1/5；设计4→任务2/3；设计5→任务6；设计6→任务3/4；设计7→任务2/8；设计8的12项→任务1–8（并发核心集中任务7）；设计9→任务8交付门。

现阶段只编写计划，不把计划中的命令或测试名称当成已实现能力。不存在生产变更、真实付费调用或发送授权。

推荐 **Subagent-driven**：身份迁移、邮件防重发、真实并发和CLI接口之间有明确依赖，逐任务独立审查更适合防止误发；代价是更多审查上下文。另一选项 **Native**：主 Agent 在本会话按序实施，最后独立全分支审查，开销更低。用户审阅计划并选择方式后进入执行。
