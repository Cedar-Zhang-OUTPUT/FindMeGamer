# Agent Workflow Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task inline in this task.

**Goal:** 将已确认的找人、去重、解释、邮箱及邮件工作流交付为可执行 Skill，补齐其依赖的服务能力。

**Architecture:** 网关保留薄封装与邮件任务；Agent 在本地持久化游戏资料、候选证据与匹配，不恢复旧客户端业务数据库。目录驱动 CLI 加少量确定性辅助命令。

**Tech Stack:** 现有 Go CLI、Python FastAPI/SQLAlchemy、JSON/Markdown、pytest/Go tests。

**Spec:** `docs/superpowers/specs/2026-09-15-cli-agent-services-design.md` 第 10 节。

## Global Constraints

- 继续同一 worktree，旧服务不启动；各模块 TDD、有限独立审查后提交。
- 基础计划 Task 1–3 已完成；先继续 Task 4 邮箱补强，再执行下面模板模块和基础 Task 5；随后完成其余增补与 Skill，最后基础 Task 7 发布。
- 默认 20 位合适结果，不凑数；默认有限请求预算见规格，实际请求前展示。未知金额、未知地区、未找到邮箱和任务失败分别表达。
- 平台身份去重、原始证据可追溯；不猜私人邮箱；发送确认绑定预览，未知投递不自动重试。

## A. 服务端版本化模板（基础 Task 5 前）

进度：模板定义/纯渲染/HTTP 目录与描述/Go CLI 已完成并通过独立审查，实际文件 `agent-service/src/fmg_agent/email/template_data/game-outreach.json` 随 Python 包分发。7 项模板测试通过，模板命令加入真实 CLI/HTTP 隔离端到端验收。不可变预览与确认发送现已在基础 Task 5 完成并通过独立审查。当前整体验证 89 项 Python 测试、18 项 Go 测试及 go vet 通过，未外发邮件或部署。

**Files:** create `agent-service/src/fmg_agent/email/templates.py`, `agent-service/email-templates/game-outreach.json`, `agent-service/tests/test_email_templates.py`; modify email routes, `cli/internal/email.go`, corresponding Go tests。

**Interfaces:** GET `/v1/email/templates`, GET `/v1/email/templates/{id}`；纯函数 `render_template(template, variables) -> {subject,text,html}`。preview 输入 `{template_id,template_version,variables,to}`，变量有 name/required/type 描述，缺失返回字段名而不泄漏值。初始模板含游戏名称/介绍/链接、创作者称呼、基于真实依据的个性化段落与公司签名；不硬编码 LIMINAL。

- [x] 添加测试并确认红灯：替换游戏不会残留旧介绍、未知模板/版本/必填缺失拒绝、HTML 变量转义。

```python
def test_template_escapes_html(template):
    result = render_template(template, {'creator_name': '<b>A</b>', **required_values})
    assert '&lt;b&gt;A&lt;/b&gt;' in result['html']
```

- [x] 实现固定目录加载和受限变量替换，不执行任意模板代码；模板版本写入不可变预览，现有发送只使用快照。
- [x] `.venv/bin/pytest tests/test_email_templates.py -q`；Go CLI 测试列表、描述和 preview 输入；独立审查、提交。

## B. Steam 游戏身份与相似推荐

**Files:** create `agent-service/src/fmg_agent/providers/steam_store.py`, `agent-service/tests/test_steam_store.py`; modify provider routes/catalog builder, `api-catalog/steam.json`, CLI tests。

**Interfaces:** 注册 `store.search` 与 `store.recommendations` 操作；返回候选 app ID/name/url 及 source_url/retrieved_at，不返回 AI 游戏判断。URL 和 App ID 从确定的 Steam 域名解析；多名字候选由 Agent 确认。

- [ ] 测试先行：名称返回多个候选不自动取第一个、推荐提取排除当前游戏且去重、空推荐与请求失败区分、固定主机与重定向安全。

```python
def test_recommendations_deduplicate(store_fixture):
    result = parse_recommendations(store_fixture, current_app_id='570')
    ids = [item['app_id'] for item in result]
    assert len(ids) == len(set(ids))
    assert '570' not in ids
```

- [ ] 参考旧 Steam 获取实现，验证当前可用页面/接口再注册辅助操作；HTTP 响应采用有界读取。将页面解析稳定性限制写入目录。
- [ ] 离线 fixture 回归与一次真实 Steam 游戏搜索/推荐 smoke；失败不伪装为空结果；审查提交。

## C. 按任务记录用量

**Files:** create `agent-service/src/fmg_agent/usage.py`, `agent-service/tests/test_usage.py`, next sequential Alembic migration for usage records; modify provider transport/routes, email worker, Go command/client。

**Interfaces:** CLI `--run-id` 传递 `X-FMG-Run-ID`；GET `/v1/usage?run_id=...` 只返回当前令牌归属。记录 request_id/provider/operation/status/resource_counts/usage/estimated_cost/actual_cost/currency/pricing_version，缺失保持 null。

- [ ] 红灯测试：不同令牌相同 run ID 不混账；成功/失败均记录；一个 request_id 不重复；未知金额不为零，估算与实际不相加重复计费。

```python
def test_unknown_cost_stays_unknown(ledger):
    ledger.record(request_id='r1', run_id='task1', provider='x', actual_cost=None)
    assert ledger.summary('task1')['complete_cost_known'] is False
```

- [ ] 实现 DB 唯一请求记录，使用上游实际 usage 与版本化价格依据；不使用全账户余额差额作为单任务费用。邮箱重试每次实际请求独立入账。
- [ ] pytest、Go test 和隔离网关 smoke，核对日志不包含公司密钥或邮件正文；审查提交。

## D. 本地资料辅助脚本与业务 Skill

**Files:** create `skills/fmg-research/SKILL.md`, `references/{research,outreach,files}.md`, `scripts/workspace.py`, `tests/test_workflow_workspace.py`; update技术 Skill 与 quickstart。

**Interfaces:** 辅助脚本 `workspace.py init --root PATH --app-id ID`、`index --root PATH --input JSON`、`summary --root PATH --run-id ID`。稳定 ID 用平台+账号 ID；保留 seen/recommended/rejected/contacted 状态与 run ID；原子保存小索引，不改用户已有证据文件。

- [ ] 先写测试：重复账号不重复深挖索引、同名异平台不合并、条件变化保留历史、原子保存中断不破坏上次索引、成本未知不归零。

```python
def test_cross_platform_names_do_not_merge(workspace):
    workspace.add(platform='youtube', account_id='1', name='Same')
    workspace.add(platform='x', account_id='2', name='Same')
    assert len(workspace.accounts()) == 2
```

- [ ] 读取 skill-creator/writing-skills 后编写最小入口及按需参考；默认预算、硬条件/偏好/扩展、先筛后深挖、公开邮箱补强、文件证据、局部恢复与批次确认均来自规格。已有用户信息不重复询问；首次实际使用简短介绍能力。
- [ ] 用隔离上游数据验证：首次找人、继续找去重、质疑匹配读取证据、直接给定账号评估、补邮箱失败不写 Not Found、模板变量与未确认不发信、usage unknown。独立 Agent 按 Skill 实际运行命令，报告偏差后修正。
- [ ] 校验 Skill、回归辅助脚本和 CLI 示例，提交；然后进入基础计划 Task 7 的部署与全平台打包发布，不提前宣称安装完成。
