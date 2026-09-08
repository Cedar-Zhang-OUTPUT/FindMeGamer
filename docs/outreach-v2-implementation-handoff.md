# P6/P7 → P9 后续实施交接

2026-09-08。供渠道采集开关单元结项后派工；不加入当前单元审查。这里只读核对了 `8cabb112f4b6f6b318aff2c2732cff71fe0beea8`、已核验的 PRD revision 751 及本地模板参考数据；未运行原型脚本、测试或提供商/SMTP，未改业务代码、配置、已有矩阵或 Git index。下述接口/对象是实施建议，不是已交付能力。

依据：[P6](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnAeqz3rolPlWxymtyTTmoKh)、[P7](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnUNlm8NKNMZWSb7WjdJFBMc)、[第三章](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnzqxjPvo7aWnAKZJZr2xU5b)、[P9](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnRxBosYOWLOhvxucG08oVIe)、[已接受准备批次契约](backend-v2-outreach-preparation.md)。各代码链接仅供定位，实现判断以固定 commit 为准。

## 1. Canonical 模板：必须从这份数据注册

| 项目 | 精确来源 / 规则 |
| --- | --- |
| 用户原稿 | [Overseas KOL Outreach Email Template｜LIMINAL: Within](https://k1mai98sti.feishu.cn/wiki/IKnNw200AiNDUek5aIIcAVmKnab)；底层文档 `Ieqid5pULoUSqMxOtKTc156xnLe`，revision **69**。PRD 第三章重新核实仍指向此版本。 |
| 本地原始数据 | [template.json](../.local/prd-review-20260908/unpacked/release-v5/validation/template.json) 的 `content` 与 [template.xml](../.local/prd-review-20260908/unpacked/release-v5/validation/template.xml) 字节一致；内容 SHA-256：`6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd`。实施时将此数据晋升为受版本管理的模板资源，不能依赖 `.local/` 在部署机器存在。 |
| 固定片段 SHA-256 | `0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93`。本次独立只读计算与 PRD、原型记录一致。它不是整个 XML 或最终 MIME 的哈希。 |
| 哈希输入 | 从 XML 只移除 ` id="…"`，去掉整个 `<title>`；提取首个 `<p><b>Subject:</b> …</p>` 中的主题文字，再移除该主题段。其余正文中四个黄色 `<span background-color="rgba(255,246,122,0.8)">…</span>` 整块替为 `<slot/>`；对 `subject + "\n" + body` 的 UTF-8 做 SHA-256。不要在此之前重新排版、trim、Markdown 重渲染或统一 Unicode 标点。 |
| 精确主题 | `Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG`；`Subject:` 是来源标签，不是邮件主题的一部分。 |
| 固定链接 / 签名 | `https://store.steampowered.com/app/4952700/_/`（末尾下划线/斜杠保留）；`Best,`、`Toki`、`Game Producer, Ontology Play`、`Hong Kong` 四个独立签名段。Settings 发件名不自动改正文签名。 |
| 版本与游戏 | 默认仅注册 `LIMINAL: Within · original locked`，绑定明确的本系统 Game UUID，并保存来源 Steam `4952700`/模板 revision/hash。不要只按显示名称猜绑定，也不要要求所有其他游戏必须有 Steam ID。其他游戏须用户明确保存其固定正文/四范围的新模板版本后才能发送；不能把游戏名变量塞进 revision 69。 |

正文共有 **20 个 `<p>`**：1 空；2 称呼；3 空；4 自我介绍与关注/观看句；5 邀请；6 空；7 Demo；8 空；9 游戏介绍；10 空；11 玩法；12 空；13 自由体验/分享邀请；14 空；15 致谢；16 空；17–20 四行签名。特别是第 4/5 段之间没有额外空段。原有 `<b>` 保留，包括游戏介绍里 `<b>LIMINAL: Within </b>` 的尾随空格，以及 Dispatch、PARANORMASIGHT 的加粗。直接以 canonical 片段拼接，避免从截图或手打全文重建。

| 唯一槽位（原型 key 可作为明确映射） | 源范围与依据 |
| --- | --- |
| `firstName` | `[First Name]`，第 2 段；仅确认的公开惯用称呼，不推断实名。固定 `Hi ` 和逗号均不在槽内。 |
| `channelName` | `[Channel Name]`，第 4 段；当前真实平台账号的频道名。 |
| `reference` | `[Reference Game / Video]`，第 4 段；真实作品/视频名及可核查来源。紧随其后的固定句点在槽外。 |
| `observation` | `[specific observation about their commentary, humor, pacing, or approach to story games].`，第 4 段；**包含最后句点**，需具体来源片段/时间点或核验笔记，标题不能支持幽默/节奏等断言。固定 `I liked how you ` 在槽外。 |

AI 输出仅四个结构化槽位；引用关联由服务器绑定到已选、当前身份的真实记录，不能接受模型凭空给出的来源链接。固定 `I’ve been following`、`especially enjoyed your video`、`I liked how you` 另需实际依据或发件人明确确认；模型生成、全局公开姓名确认、点击预览均不自动确认这些经历。可对明确适用的选中成员集中确认，无逐封打开/审批门槛。

[strict-template.mjs](../.local/prd-review-20260908/unpacked/release-v5/validation/strict-template.mjs) 与 [template-tests.mjs](../.local/prd-review-20260908/unpacked/release-v5/validation/template-tests.mjs) 仅作参考：前者的四槽/哈希/绑定边界可转成后端合约；其 `verified:true`、`confirmedFollowing`、`confirmedWatched` 是合成输入，不是现成证据系统。原型的 21 项通过不算本仓库验收；不要把脚本、dry-run 邮件或脚本中的固定输入当生产实现。

## 2. 最少三个可验收单元

| 单元 | 后端交付与前端接线 | 明确结项点 |
| --- | --- | --- |
| **A：模板版本 + 四槽位草稿/依据（P6）** | 注册 canonical 不可变版本，提供列表/读取及用户明确另存新版本的契约；以现有 recipient-batch 为成员来源，新建有版本的 compose/draft 与逐成员生成状态。冻结本轮模板/资料/已选依据输入，接既有模型网关生成恰好四槽，允许单条重试与四槽人工修改；记录每槽依据和明确发件人事实确认及其适用版本。保留全部 N 位、初始 RecipientSnapshot 和成员顺序；缺项可编辑后重算，失败保留其他成功草稿。前端 P6 完整模板只读、四槽可编辑、来源可查看/补齐。 | 真正通过 HTTP→任务→模型 HTTP fixture→数据库读取，正确/错误输出、缺项、重试、源变更、版本另存均可演示。此单元不发邮件；准备 `send_ready=false` 不先伪改成 true。 |
| **B：资格/完整预览 + 最终发送快照（P7）** | 独立 qualification 计算总数/可发送/需修复/明确排除，返回实际 From/Reply-To、每人地址/主题/全文/四槽/依据及确认版本。校验模板游戏绑定、固定 hash、槽位/观察事实、当前身份/邮箱及发件账户。修改相关 Game/Creator/证据/槽位/模板/发件身份，使旧资格和发送确认失效；新草稿刷新不改 Activity 查询或初始冻结历史。最后一次同页确认原子冻结**实际 eligible 子集、单个地址、From/Reply-To、模板版本/hash、正文、依据/确认版本**并入队。新增真实 Activity 发送来源，不造 MatchResult。接共享 SMTP/限速、发送结果、明确失败重试与未知结果核对。 | 隔离 API→Celery→socket-free SMTP capture 闭环；用户无需逐人打开也能全批校验并确认两封、明确排除一人。重复确认/丢响应不多建任务，worker 重复派发不重发已完成项；未知结果不会自动再送。 |
| **C：同一名单的邀请/回复/跟进（P9）** | 以 Activity + 原选择/准备成员 + 发送批次/Delivery 关联同一名单；展示发送/邀请/跟进状态。新增带来源和时间的人工接受/婉拒记录、按活动的四种跟进状态和八种合作进展；复用统一 Creator 详情。回 P4 保留累计发现，新选择→新批次，已发历史不改。 | 同一 Creator 在两活动的邀请/跟进互不覆盖；人工记录有来源/时间；打开/点击不变接受状态；继续发现后的新批次仍可追溯同一名单。自动收件箱同步不在已确认范围。 |

三单元均按现有 TDD、当前维护窗口迁移、适用回归与一次有界独立审查交付。A 的模板注册/生成和 B 的发送资格使用不同状态；不得把 A 的“生成完成”当 B 的“可发送”。每单元后由前端消费已接受类型化契约，不要求先铺一组新业务页。

## 3. 现有代码的准确接缝

| 已有位置 | 直接复用 / 必要变更 |
| --- | --- |
| [activity_outreach routes](../backend/app/api/routes/activity_outreach.py)、[activity_preparation](../backend/app/repositories/activity_preparation.py) | 复用 selections GET/update/cancel、明确 contact/work/evaluation 选择、`expected_revision/context_token`、活动内身份与公开称呼确认。`public_name_confirmed` 不等于 sender facts。现有 Preparation 的 `send_ready: Literal[False]` / `sender_watched: Literal[False]` 是准备单元边界，新增 draft/qualification DTO，不靠客户端覆盖这两个字面量。 |
| [recipient_batches](../backend/app/repositories/recipient_batches.py)、[新模型](../backend/app/db/models/activity_outreach.py) | 复用 `freeze_batch/get_batch/batch_detail`、持久 `request_id`、原始成员顺序、nullable contact 与 `snapshot`/实时 `preparation` 分层。`source_changed/current_missing_fields` 提示修复；新 draft/最终 SendBatch 引用 `RecipientSnapshot.id`，不要原地改初始快照或缩小 N。 |
| [SMTP gateway](../backend/app/outreach/smtp.py)、[限速](../backend/app/outreach/rate_limit.py)、[旧 SMTP routes](../backend/app/api/routes/outreach.py) | 共用 `SMTPConfig`、`SMTPGateway.probe/send`、`SMTPReceipt`、`SMTPRateLimiter.acquire` 和 `/api/v1/outreach/smtp` 的设置/测试契约。沿用实际 From/Reply-To 快照，不另存第二套 SMTP 设置。Gateway/worker 需补发送阶段与未知结果分类，见下方阻塞行为。 |
| [发送 worker](../backend/app/workers/outreach_tasks.py) | `DeliveryTaskStore.claim/mark_sent/mark_failed`、`DeliveryExecutor.execute`、`send_delivery/enqueue_send_batch` 的认领/汇总/限速流程可在接入新 Delivery 来源后复用；不能原样复用 `_message`：其强制派生响应 token 并要求两个 callback 占位符。新增持久化邮件模式，revision 69 模式直接构造冻结正文/MIME，无 token/CTA；旧模式继续原路径。 |
| [旧 composer](../backend/app/outreach/batches.py)、[旧模型](../backend/app/db/models/outreach.py)、[旧 repository](../backend/app/repositories/outreach.py) | **不调用旧 `_load_composition` 作为新入口**：它要求成功 MatchTask/MatchResult 与 `match_reasons`，缺邮箱整批失败。Campaign 非空且唯一 `match_task_id`、SendBatch/Delivery campaign FK、重发与列表的 Match joins 均需真正 Activity 来源的替代/分流。推荐新增 Activity final-send composer，显式来源映射后复用 transport；数据库可用新来源模型或清楚的来源模式，但不得填假 Match/YesNo 字段满足旧非空约束。 |
| [旧模板 renderer](../backend/app/outreach/templates.py)、[TemplateData/Context](../backend/app/schemas/outreach.py) | 旧七变量任意 Markdown 模板、正文 override、原地递增 `version` 都不能充当 immutable revision 69。`render_delivery` 无条件附加 Yes/No CTA，且 Markdown/HTML sanitizer 会改 canonical 结构。新专用 schema + 固定片段 renderer，仅转义槽位文本；保留旧 renderer/响应历史。预览与 worker 两端同时分流，不能只从页面隐藏按钮。 |
| [Activity `_write`](../backend/app/api/routes/activity.py)、[旧发送 route dispatcher](../backend/app/api/routes/outreach.py) | 复用 v2 原子写入/请求 hash/幂等模式及“提交后 dispatch，失败重派同一任务”的模式；旧 `_idempotent_replay` 响应类型固定为旧 `OutreachSendBatchResponse`，新 route 应用新的 typed response。最终发送有独立持久 request ID/确认内容 hash，不能把 recipient-batch 的 request ID 当发送授权。 |

## 4. 只需在对应新单元解决的普通流程冲突

1. **其他游戏没有可发送的默认模板。** 默认固定正文只写 LIMINAL，必须提供“明确新模板版本”路径及游戏绑定；无匹配版本时可继续保留名单/补资料，发送明确不可用。无需为开发 canonical 版本等用户再写一封邮件，也不能自动套改默认全文。
2. **不能机械用 `missing_fields == []` 定义最终资格。** 当前准备列出 `evaluation_missing/stale` 和 `work_relation_missing`；但 PRD 允许其他相关内容、实际可核查视频，并未要求一定成功 AI 排名或实玩当前/参考游戏。A/B 应将推荐评价状态与邮件事实依据分开；无匹配评分但有真实相关作品、具体观察和明确事实确认的成员不能被新增门槛挡死。无作品观察/邮箱等真正缺项仍必须阻止发送。
3. **游戏编辑后的未发同步必须有出口。** 当前 `game_changed` 比较实时 Game 与不可变 Activity source，重新读 preparation 不能清除此差异。Activity 用于发现的原始 **Game/reference snapshot 不可被草稿刷新覆盖**；后续草稿须另外区分当前有效资料/资格版本与原发现上下文。资料变更时失效旧个性化、资格及最终发送确认，刷新后可继续；原查询、RecipientSnapshot 和已发送快照保持不变。验收应证明修正游戏/参考资料不必丢掉已选 N 位重跑发现，不借此扩展永久 Profile 历史系统。
4. **预览与实际发件身份须一致。** 旧 worker 登录读取最新 SMTP 配置，From/Reply-To 来自冻结 Delivery；B 要比较预览时的发件身份版本，身份变化后重新确认再发送。换密码/连接测试不自动外发，也不自动改模板中的 Toki 签名。
5. **“可能已发送”不能当普通临时失败自动重试。** 基线 gateway 把 `send_message` 的断线/超时归为 `SMTPTransientError`，worker 会转可重试。B 至少区分提交前失败、明确 SMTP 拒收与发送调用后的不确定结果；最后一种标待核对，禁止自动重派/普通 Retry。Message-ID 固定不保证邮箱去重，SMTP 接受也不等于最终送达。此项是 PRD P7 的正常断线恢复要求，不扩大为投递回执/邮箱同步项目。

以上是新流程的实施约束，未重新否定已接受准备批次/旧发送单元。模板的新增正文来自用户明确保存的版本；自动 inbox 同步与真实 SMTP 外发另有范围/授权边界，其余无需新增产品许可。

## 5. 具体 fixture 验收清单（全部无外发）

| 场景 | 必须观察到的结果 |
| --- | --- |
| Canonical / MIME 保真 | 后端 canonical fixture 的来源/hash/主题/20 段/加粗/URL/四槽范围逐项一致；改主题、签名或追加 CTA 被拒绝；缺第四槽句点失败。capture 中解码后的 HTML/纯文本没有新 Yes/No、`/r/…?choice=`、追踪链接或未填槽，MIME 直接取冻结内容。保留一条旧邮件 fixture，旧 callback 仍有效。 |
| N 位完整保留 | 明确选择 3 人：完整、缺邮箱、缺观察各一位；recipient-batch 和 P6 始终 3 人/原顺序，空邮箱原快照不改，无假 MatchResult、Delivery 或发送任务；补第二人的一个明确邮箱/依据后重算，不自动选其另一地址。 |
| 生成/修复/确认 | 模型 HTTP fixture 返回四槽成功、坏结构、超时；只重试失败成员，已成功保留。只有标题时观察不可发送，补当前身份来源片段/笔记后通过内容校验；发件人事实仍需明确确认。无 AI 评价但证据完整的普通相关内容可通过邮件资格；重复邮箱须修复/明确排除，不静默合并名单。 |
| 原文游戏绑定 | LIMINAL 正确 Game/模板版本能生成；另一手工 Game 可保存名单但不能套用默认模板发送；明确另存该游戏的新版本后可用，原版及旧预览不变。 |
| 更新与未发草稿 | 预览后分别修改选中邮箱/来源、观察作品、槽位、公开称呼、Game 及发件身份；旧资格/确认失效，修复生成新版本可继续；原始 RecipientSnapshot 不变。重绑定不可用旧账号证据给新账号发信。最终已经冻结/发送的内容不能因 Library 编辑被静默改写。 |
| 预览/最终发送计数 | 3 人准备总数；2 人可发送、1 人需修复并明确排除。用户未逐封打开仍可全批验证/抽看，筛选只改变显示；最后确认显示 2 个准确地址、From/Reply-To/活动，创建 2 个 Delivery，P9 仍可追溯 3 人及排除原因。零 eligible 禁止发送。 |
| 幂等/队列恢复 | final-send 提交成功后模拟 HTTP 丢响应、broker 派发失败；相同 request/key/body 读回并重派同一批，不增加 Delivery；改内容复用 key 冲突。重复 worker 调用对已完成 Delivery 的 SMTP capture 数不增加。 |
| SMTP 结果 | socket-free fake SMTP：明确成功、连接前失败、明确拒收、进入 send_message 后断线。成功为 SMTP accepted/sent 而非 delivered；明确失败按新流程可重试，未知结果 capture 调用仅一次、暂停核对、不自动发送第二次。保存 SMTP、连接测试及取消最终确认均产生零封。 |
| P9 同名单/隔离 | 人工接受/婉拒必须附来源和时间；同一 Creator 的两 Activity 独立；跟进四状态、合作八状态可读写，返回保持列表位置/筛选；继续发现新成员不改旧发送快照，新批次有独立历史。 |

先由后端按 A→B→C 交付 typed API/任务/数据库 fixture 验收，前端分段接入最终 packaged E2E。此交接没有执行上述测试；真实 SMTP TLS、外部送达、自动收件同步、Release/部署均未被验证或执行。
