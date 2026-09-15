# FindMeGamer CLI & Agent Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 发布通过公司服务器调用 YouTube、X、Steam、邮箱补强和发信的 CLI，以及技术使用 Skill。

**Architecture:** Go CLI 调用独立 FastAPI 网关；公司凭据仅在服务器。网关使用独立 PostgreSQL 数据库及 Celery 队列，复用现有服务器而不恢复旧客户端服务。

**Tech Stack:** Go、Python 3.13、FastAPI、httpx、SQLAlchemy/Alembic、Celery、PostgreSQL、Redis、Docker Compose。执行时记录确切工具链版本并锁定依赖。

**Spec:** `docs/superpowers/specs/2026-09-15-cli-agent-services-design.md`

## Global Constraints

- CLI 名称 `fmg`；macOS/Linux，arm64/amd64；JSON stdout，诊断 stderr。
- 公司密钥只在服务器；每位同事或 Agent 独立可撤销令牌。
- 新数据库 `find_me_gamer_agent`，新队列 `fmg_agent`；不消费旧任务，不恢复旧 API/Worker/Beat。
- 网关不实现 Library、Profile、Match；用户已确认本地 Agent 工作流，按补充计划实现技术 Skill 和业务 Skill。
- 默认一页，显式有限分页；不无限重试、不默认付费遍历、不自动发真实邮件。
- 每单元 TDD、独立审查、针对性回归后提交。审查阻塞项限于正常业务、数据/重复执行、明确安全问题、当前迁移和真实操作错误；纯防御性扩展记后续。
- 本文为开发计划，未执行项全部保持未勾选。测试示例定义验收接口，不代表已有实现。

## 执行顺序与文件边界

1–3 为可单独验收的只读 API/CLI 子项目；4–5 为邮件子项目；6–7 为 Skill 与发布子项目。默认在本任务逐单元执行，独立审查可在执行时安排，不同时修改相同文件。

| 目录 | 责任 |
|---|---|
| `agent-service/src/fmg_agent/` | 新服务，独立于旧 `backend/app` 业务模型 |
| `agent-service/tests/` | 单元、数据库与隔离端到端测试 |
| `cli/` | Go 命令行、HTTP 客户端、安装与输出契约 |
| `api-catalog/` | 已核验的操作目录、认证/配额信息、覆盖说明 |
| `skills/fmg-api/` | 技术调用说明及按平台拆分的参考文档 |
| `deploy/agent-services/` | 新服务编排、迁移、备份、回滚与烟测 |

旧集成只作为参考：`backend/app/integrations/{youtube,x,steam,gemini_email,http,public_pages}.py`、`backend/app/outreach/smtp.py`。适用的纯传输逻辑搬入新包并补测试，不使新服务导入旧 Profile/ORM。

## Task 1：独立网关、数据库、访问令牌

**Files — create:** `agent-service/pyproject.toml`、`agent-service/src/fmg_agent/{__init__,app,config,db,auth,admin}.py`、`agent-service/alembic.ini`、`agent-service/migrations/env.py`、`agent-service/migrations/versions/0001_tokens.py`、`agent-service/tests/{conftest,test_auth}.py`、`agent-service/compose.test.yaml`。

**Interfaces:** `create_app(settings) -> FastAPI`；管理命令 `python -m fmg_agent.admin token create/revoke`；`GET /v1/health`；受保护路由依赖 `require_scope(scope)`。令牌明文仅签发时显示一次，持久化 SHA256 摘要及标识、scope、撤销时间。

- [x] 创建隔离测试依赖与测试：无令牌/撤销令牌 401，只读令牌调用发送 403；健康接口不泄露配置。

```python
def test_revoked_token_is_rejected(client, issued_token, revoke_token):
    revoke_token(issued_token)
    response = client.get('/v1/auth/check', headers={'Authorization': f'Bearer {issued_token}'})
    assert response.status_code == 401
    assert issued_token not in response.text
```

- [x] 在 `agent-service` 建 `.venv`，安装 editable dev 依赖，运行 `.venv/bin/pytest tests/test_auth.py -q`，确认失败来自未实现认证而非数据库未启动。
- [x] 实现摘要查询、scope 检查、认证路由和新库迁移；未知令牌与撤销令牌返回相同安全错误。配置必须拒绝误连旧生产数据库进行迁移。

```python
digest = hashlib.sha256(raw_token.encode()).hexdigest()
record = session.scalar(select(AccessToken).where(AccessToken.digest == digest))
if record is None or record.revoked_at is not None:
    raise HTTPException(status_code=401, detail='invalid_access_token')
```

- [x] 重跑认证测试，并在隔离 PostgreSQL 执行 `alembic upgrade head` 两次，第二次无新增迁移；记录实际版本。
- [x] 审查、仅暂存本单元文件，提交 `feat: add isolated agent gateway and access tokens`。

Task 1 验证记录：Python 3.13.15，PostgreSQL 17.11。实现前测试记录为缺少 app/config/迁移导致失败；实现后 20 项通过，独立审查无阻塞项且复跑 20 项通过。加强存储失败断言并增加 API 503 脱敏检查后最终 21 项通过；pip check 通过。保留一项上游测试依赖弃用警告。仅本地新增服务代码，无线上部署或外部 API 调用。

## Task 2：官方操作目录与薄封装

**Files — create:** `api-catalog/{youtube,x,steam}.json`、`api-catalog/coverage.md`、`agent-service/src/fmg_agent/providers/{__init__,catalog,transport,routes}.py`、`agent-service/tests/test_provider_calls.py`。**Modify:** `app.py` 注册路由。

**Interfaces:** `POST /v1/providers/{provider}/call` 输入 `{operation:str,params:object}`，输出 `{data:any,meta:object}`；`GET /v1/providers/{provider}/operations` 及 `/operations/{operation}`；错误契约见规格第 4 节。

- [x] 根据规格中的官方文档核验只读操作清单，记录 operation、method、host、path、参数位置、分页字段、所需授权、文档 URL、核验日期、测试状态。YouTube 使用官方 Discovery 元数据；X 依据官方端点目录；Steam 依据 GetSupportedAPIList，Store 辅助接口单列。不能仅收录旧 Profile 使用的少量操作。
- [x] 写 mock 上游测试，验证未知响应字段保留、分页游标原样返回、401/429/余额错误脱敏分类、嵌套部分错误保留、任意 host/认证参数拒绝。

```python
def test_preserves_provider_fields(client, youtube_mock, read_headers):
    youtube_mock.json({'items': [], 'futureField': {'x': 1}, 'nextPageToken': 'p2'})
    r = client.post('/v1/providers/youtube/call', headers=read_headers,
                    json={'operation': 'search.list', 'params': {'part': 'snippet', 'q': 'indie'}})
    assert r.json()['data']['futureField'] == {'x': 1}
    assert r.json()['data']['nextPageToken'] == 'p2'
```

- [x] 运行 `.venv/bin/pytest tests/test_provider_calls.py -q`，确认未注册路由/实现导致失败。
- [x] 实现目录驱动请求；服务器注入密钥，固定主机且禁用任意重定向，不以严格 Profile schema 校验上游响应。批量参数保留原语义，CLI 的分页上限不是上游新增参数。

```python
operation = catalog.resolve(provider, request.operation)
params = operation.validate_params(request.params, reject_credentials=True)
payload, headers = await transport.call(operation, params)
return {'data': payload, 'meta': safe_metadata(headers, request_id)}
```

- [x] 重跑测试；各平台至少一次低成本真实只读 smoke，实际权限不足记录 requires-authorization，不扩大授权或自动重试消费。核对目录缺项并明确不支持的流式/二进制能力。
- [x] 审查提交 `feat: expose catalog-driven platform read APIs`。

Task 2 验证记录：最终 51 项测试通过。独立审查发现并修复 Steam optional key 和 indexed batch 参数两项 P2，红→绿测试及审查复核通过。服务器临时一次性容器用新代码、旧环境依赖及只读 SQL 读取公司凭据，分别真实成功调用 YouTube `i18nLanguages.list`、X `getUsersByUsername`、Steam `store.appdetails`；凭据没有输出或下发至开发机。此 smoke 不代表新网关已部署或全部操作已实测。API 目录覆盖边界见 `api-catalog/coverage.md`。旧 API/Worker/Beat 未启动。

## Task 3：可安装 CLI 与有限分页

**Files — create:** `cli/go.mod`、`cli/cmd/fmg/main.go`、`cli/internal/{command,client,config,output,pagination}.go`、`cli/internal/{command,pagination}_test.go`。

**Interfaces:** `Run(args []string, stdin io.Reader, stdout, stderr io.Writer) int`；命令 `auth login/logout`、`version`、`{provider} operations/describe/call`。登录 token 从交互隐藏输入或 stdin 获取，不推荐放 shell 参数；配置文件权限 0600，地址必须 HTTPS（本地测试 loopback 除外）。

- [x] 用 Go httptest 写测试：默认一页，`--max-pages 2` 恰两页，达到 max-items 停止，Ctrl-C 保留已写出的页，401 非零退出，日志不含令牌。

```go
func TestUnknownCommand(t *testing.T) {
    var out, err bytes.Buffer
    code := Run([]string{"unknown"}, strings.NewReader(""), &out, &err)
    if code != 2 { t.Fatalf("exit = %d", code) }
}
```

- [x] 在 `cli` 运行 `go test ./...` 确认测试因缺 Run/行为而失败。
- [x] 实现单页 JSON 与分页 NDJSON（每行一页 `{data,meta}`）；帮助明确输出区别。用共享 catalog 的分页描述读取游标，不推测分页。有限重试只用于安全读取，发送请求禁止通用 HTTP 自动重试。

```go
for page := 0; page < limits.MaxPages; page++ {
    result, err := api.Call(ctx, provider, operation, params)
    if err != nil { return writeError(stderr, err) }
    if err := encoder.Encode(result); err != nil { return 5 }
    if !advanceCursor(params, result, descriptor) { break }
}
```

- [x] `go test ./...`、`go vet ./...`、`go build ./cmd/fmg`；用 Task 2 测试网关验 `operations → describe → call`，确认 stdout 可 JSON 解析。
- [x] 审查提交 `feat: add agent-friendly platform CLI`。

Task 3 验证记录：官方校验和确认的 Go 1.27.1（本机 macOS arm64）；12 项 Go 测试、go vet 和编译通过。编译后的 CLI 连接真实本地 FastAPI 与隔离数据库，完成登录、目录、描述、单页、两页、认证检查和退出，只有上游响应模拟，不产生平台费用。独立审查发现读取正文时取消及未登录 auth check 两项退出码问题，补充红→绿测试并复核通过。max-items 按完整页边界停止，可能超过 N，帮助和 README 明示；无自动网络重试。此阶段尚未发布安装器、多平台二进制或部署新网关。

## Task 4：独立邮箱补强异步任务

Task 4 完成记录：基础持久化已于 d486d00 提交。现接入独立安全公开网页抓取、Gemini 多邮箱/来源/usage、专用 Celery Worker 与内置恢复派发/30天清理、CLI enrich/job/retry。72 项 Python 测试、15 项 Go 测试及 go vet/pip check 通过。编译 CLI→真实 HTTP→隔离 PostgreSQL→Redis→Celery，失败后重启 Worker 再显式续跑测试通过；仅外部网页/模型模拟。另真实访问 example.com 验证新网络传输成功。独立审查两项问题均通过红→绿修复及复核。没有执行付费 Gemini smoke，没有部署或真实发信。

**Files — create:** `agent-service/src/fmg_agent/email/{__init__,models,jobs,enrichment,routes}.py`、`agent-service/src/fmg_agent/worker.py`、`agent-service/migrations/versions/0002_email_jobs.py`、`agent-service/tests/test_email_enrichment.py`、`cli/internal/email.go`、`cli/internal/email_test.go`。**Modify:** `app.py`、CLI command 路由。

**Interfaces:** `POST /v1/email/enrich`（Idempotency-Key）；`GET /v1/email/jobs/{id}`；`POST /v1/email/jobs/{id}/retry`。结果字段见规格第 5 节。CLI `email enrich --url`、`email job <id> --wait`。

- [x] 写测试：公开主页有邮箱不调用 Gemini，无邮箱触发补强，多邮箱含 purpose/source，失败续跑复用已成功阶段；同幂等键不重复计费，跨令牌无法读取任务，私网 URL 和重定向到私网均拒绝。

```python
def test_direct_email_skips_enrichment(enrichment_service, public_page, gemini):
    public_page.text = 'Business: press@example.com'
    result = enrichment_service.run('https://example.com/creator')
    assert result['emails'][0]['email'] == 'press@example.com'
    gemini.assert_not_called()
```

- [x] 运行 `.venv/bin/pytest tests/test_email_enrichment.py -q`，确认预期失败。
- [x] 迁移旧提取/补强中的纯逻辑，改成公开商务用途输入输出；写入 durable checkpoint、任务租约/终态、retry；新队列专用 Worker 不订阅旧队列。使用数据库待派发记录恢复入库后尚未入队的任务，Worker 启动及周期循环扫描，不另加 Beat 服务。

```python
if not checkpoint.has('public_pages'):
    checkpoint.save('public_pages', extract_public_business_contacts(target))
if not checkpoint.emails and not checkpoint.has('enrichment'):
    checkpoint.save('enrichment', gemini.find_public_business_contacts(target))
return checkpoint.result()
```

- [x] 单元测试通过后跑真实 API + Worker + 隔离 DB/Redis（上游 mock），重启 Worker 验证续跑。最多用一个用户认可的公开账号真实验证补强，报告来源而非“保证可投递”。本次未消耗模型额度，真实 Gemini 验证仍未执行。
- [x] 审查提交 `feat: add resumable business email enrichment jobs`。

## Task 5：邮件预览、确认发送与未知结果保护

Task 5 完成记录：模板变量生成不可变预览，显式 confirm、token scope、每预览一次 SMTP 尝试、幂等回执、未知结果不自动重发均已实现。新服务完整 89 项 Python 测试通过（含真实 PostgreSQL 并发和迁移、CLI→HTTP→DB→本地 SMTP 捕获、Worker 断点续跑）；18 项 Go 测试、go vet、编译通过。独立审查通过。全量测试暴露的 READ COMMITTED 并发查询冲突已修复并复跑通过，未出现重复投递。沿用 TLS/错误分类原则独立实现 SMTP 传输，不导入旧后端。Demo 采用先持久化 sending 再同步投递，不新增发信队列；SMTP 接受不代表进箱。没有外发、部署或发布，真实 SMTP 配置和指定收件人验收仍待后续。

本单元开始前先完成补充计划的版本化模板模块；preview 输入模板 ID、版本与变量，随后继续本单元的快照和发送保护。不得回退成仅支持任意正文的旧计划。

**Files — create:** `agent-service/src/fmg_agent/email/{sending,smtp}.py`、`agent-service/migrations/versions/0003_email_sends.py`、`agent-service/tests/test_email_sending.py`。**Modify:** email routes/models、`cli/internal/email.go` 及测试。

**Interfaces:** `POST /v1/email/previews` → 不可变 `preview_id`；`POST /v1/email/sends` 输入 `{preview_id,confirm:true}` + Idempotency-Key；`GET /v1/email/sends/{id}`。CLI `email preview --input message.json`、`email send --preview-id <id> --confirm --idempotency-key <key>`、`email receipt <id>`。

- [x] 写测试：无 confirm 拒绝；相同键同内容只投递一次、异内容冲突；无 SMTP 可预览但不能发送；收件人拒绝/网络断开安全分类；SMTP 接受后丢确认为 unknown 且不重试；并发发送也保持一次。

```python
def test_ambiguous_send_is_not_retried(sender, smtp, preview):
    smtp.accept_then_disconnect()
    first = sender.send(preview.id, key='test-send-1', confirm=True)
    second = sender.send(preview.id, key='test-send-1', confirm=True)
    assert first.state == second.state == 'unknown'
    assert smtp.delivery_attempts == 1
```

- [x] 运行 `.venv/bin/pytest tests/test_email_sending.py -q`，确认预期失败。
- [x] 复用旧 SMTP TLS/错误处理；先提交唯一发送记录与 sending 状态再执行网络投递。进程中断后遗留 sending 不自动重发，标为 unknown；返回已有记录，不声称 exactly-once SMTP。预览快照不可修改。

```python
record, created = reserve_send(token_id, idempotency_key, preview_id)
if not created:
    return record
mark_sending(record.id)
return deliver_and_record_outcome(record, smtp)
```

- [x] 运行全部邮箱测试，用本地邮件捕获器检验正文、收件人、HTML/text 与附件策略（第一版无附件则明确拒绝）。不外发；实投仅待 SMTP 与指定测试收件人就绪。
- [x] 审查提交 `feat: add confirmed idempotent email sending`。

## Task 6：技术 Skill 与文档行为验证

用户已授权工作流 Skill；本单元技术说明保留，新增业务 Skill 按 `2026-09-15-agent-workflow-extension.md` 实施。完成补充计划全部验收后再执行 Task 7 发布。

**Files — create:** `skills/fmg-api/SKILL.md`、`skills/fmg-api/references/{youtube,x,steam,email,errors-and-quotas}.md`、`cli/tests/skill_examples.sh`、`docs/agent-services/quickstart.md`。

**Interfaces:** 只使用 Tasks 1–5 已验证命令；入口说明如何查目录，平台参考按需读取。业务工作流不在本 Task 编写。

- [x] 使用 skill-creator 和 writing-skills，完整读取其要求再创建文件；先把技术示例作为可执行验收脚本，使尚未支持的命令产生明确失败。脚本使用隔离网关和 mock 上游，不默认消费真实额度。

```sh
set -eu
fmg youtube operations > operations.json
fmg youtube describe search.list > search-schema.json
fmg youtube call search.list --params '{"part":"snippet","q":"indie","maxResults":1}' > result.json
jq -e '.data' result.json >/dev/null
```

- [x] Skill 入口包含真实元数据与范围声明：

```yaml
---
name: fmg-api
description: Use the fmg CLI to access company-hosted YouTube, X, Steam, public business email enrichment and confirmed email sending. Covers API mechanics, pagination, quotas and recovery, not business selection or outreach strategy.
---
```

- [x] 写参数发现、授权不足、429/余额、分页保存、异步查询、发信确认示例；“不知道配额”必须输出 unknown，不把 API 成功等同于内容证据充分。
- [x] 运行脚本及 Skill 校验器；按照 Skill 让隔离 Agent 或独立审查者完成查目录、取一页、查任务、预览、不确认则不发送的场景，记录实际命令。禁止臆造业务步骤。
- [x] 独立审查完成，技术及业务 Skill 一并保存提交。

## Task 7：部署、安装升级与 GitHub 发布

2026-09-15 执行边界更新：用户要求完成到部署上线前。本地实现、四平台构建、安装/升级、镜像运行、迁移和备份恢复演练完成后结项本轮；下列生产配置、部署、代理切换、GitHub 推送及发布项明确留待后续授权，不因本地验收通过而标成已上线。Task 6 的技术 Skill、独立行为验证和校验均已完成，实际文件布局与验收见 `docs/agent-services/skill-validation.md`。

同日后续授权更新：用户明确要求部署服务、推送源码并让新 Codex 环境使用。现已完成新服务上线、源码分支推送、`fmg-v0.1.0` 公开发行，以及重新下载/校验/安装/在线升级/生产连接验收。下列生产项已按该授权完成；完整证据和仍未配置的 SMTP、Steam key 限制见 `docs/agent-services/rollout-2026-09-15.md`。没有合并或强推 main，没有启动旧客户端后端。

**Files — create:** `deploy/agent-services/{compose.yaml,Caddyfile.fragment,env.example,deploy.sh,smoke.sh,rollback.md}`、`cli/scripts/{build-release.sh,install.sh}`、`.github/workflows/agent-cli-release.yml`、`docs/agent-services/release-acceptance.md`。**Modify:** CLI command 路由添加 `upgrade`，新增 `cli/internal/upgrade.go` 与测试。

**Interfaces:** 四个独立发行包、SHA256SUMS、固定 release tag、安装器；新 HTTPS `/v1` 服务。公开下载地址不能包含访问令牌；token 仍单独提供。安装器默认不安装业务工作流 Skill，技术 Skill 提供明确安装选项。

- [x] 写安装测试：校验和不匹配不覆盖旧二进制；不支持平台明确退出；升级失败保留旧版本；shell 脚本不得输出配置中的秘密。

```sh
GOOS=darwin GOARCH=arm64 go build -trimpath -o dist/darwin-arm64/fmg ./cmd/fmg
GOOS=darwin GOARCH=amd64 go build -trimpath -o dist/darwin-amd64/fmg ./cmd/fmg
GOOS=linux GOARCH=arm64 go build -trimpath -o dist/linux-arm64/fmg ./cmd/fmg
GOOS=linux GOARCH=amd64 go build -trimpath -o dist/linux-amd64/fmg ./cmd/fmg
```

- [x] 先在本地 release fixture 验证损坏归档拒绝，再实现下载到临时目录、SHA256 验证、原子替换；从 GitHub release 元数据确定精确资产 URL，不能猜 latest 资源文件名。
- [x] 完整回归：Python 全量新服务测试、Go tests/vet、CLI/Skill smoke；真实 macOS 执行与 Linux 容器执行分别记录。没有执行的平台只记交叉编译成功，不写运行验收成功。
- [x] 只读核对服务器状态、旧备份仍在、数据库/Redis隔离、HTTPS证书；新建新服务私有配置，受控复用公司密钥，避免明文进入 shell 历史/日志。部署前备份新服务已有状态；首次部署不迁移旧业务数据。
- [x] 执行新库迁移，启动新 API/Worker，代理路由指向新服务；确认旧 API/Worker/Beat 仍停止。健康、撤销令牌、只读 API、异步任务、预览、错误分类实测，禁止真实外发。
- [x] 提供明确回滚步骤；新服务备份恢复在本地真实 PostgreSQL 已演练，线上备份上传 S3 成功并启用每日定时器。没有为了验收而破坏性恢复生产库，也没有恢复旧客户端服务。
- [x] 独立审查通过，部署记录保存提交；使用 `gh` 上传源码分支及 release，重新下载、校验、安装和在线升级通过。安装入口与 SMTP 等限制已写入 quickstart 和 rollout 记录。

## 验收覆盖与停止点

| 要求 | 验收单元 |
|---|---|
| 公司凭据、独立令牌、旧服务隔离 | 1、7 |
| 官方只读参数/字段、真实权限、配额 | 2、3 |
| 公共商务邮箱、多邮箱来源、续跑 | 4 |
| 人工确认、预览与幂等/unknown | 5 |
| 技术 Skill，不代写业务流程 | 6 |
| 一行安装、macOS/Linux、源码与附件发布 | 7 |

配额或授权不足只阻塞对应真实验收，不伪称成功；付费上限不得擅自提高。SMTP 未配置时交付可使用的预览与其他能力，明确实投未验。任务记录默认 30 天清理由 Worker 的新服务维护循环实现，只作用于新表且保留未终结发送记录，不额外启动旧 Beat。

文档完成后可选择在本任务按单元执行，或经用户选择采用子任务开发；业务工作流 Skill 始终等用户给出具体顺序和决策规则。
