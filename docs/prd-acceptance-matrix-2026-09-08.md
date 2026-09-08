# FindMeGamer 原始 PRD 验收与剩余工作矩阵

更新日期：2026-09-08。目标：公司内部可稳定使用的完整 Demo。本表用于需求追溯与安排后续单元，不是重新审查已接受代码，也不代表新版整体已完成。

## 来源、基线与状态

- **原始来源已现场核实**：[飞书 PRD](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh)，`revision_id=751`。本次以用户身份只读获取目录，并逐节读取 P1.1、P1.2、P2.1、P3、P4、P5.1、P6、P7、P9、P12.1、P12.2、P15、第三章模板和第四章验收；以下锚点来自该版本的真实 block ID。
- **已接受代码基线**：`cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5`。本次实现核对使用 `git show` 固定读取；其 `desktop/` 与已接受前端 `3abf262` 一致。文件链接便于定位，内容结论以此 commit 为准，不能把当前工作区的在制修改计为验收通过。
- **追加验收**：名单/准备批次 `8cabb11`（B7）、共享采集开关 `b2b15f4`（B8）及 P4/P12 后端读查询 `8cf755e`（B9）已接受；这些明确增量覆盖初始 `cad5565` 基线的对应状态。测试夹具 `4bb9d78` 是验收设施，不是业务功能交付。
- **最新前端与在制单元**：Match 客户端 `149bc69` 已固定快照通过源码验收（F4），但最终打包 E2E 仍待钥匙串授权，不是整单元已完成。Settings 渠道开关 UI `in-progress`，已接手独立 `59414` / `b2b15f4` / `0014` 的测试控制；旧 `53251` / `0012` 保留，`18090` 不动。P4/P12 新读查询前端尚未交付；命名候选集合后端正在完整回归/单次独立审查，未计为接受。
- **范围变更与过程记录**：[总管交接文档](prd-review-2026-09-08.md)。用户随后明确的范围优先于原 PRD；较早的等待、环境版本和“尚未实现”文字不能覆盖后续已接受记录。
- **状态**：`accepted`＝该行明确限定的增量已接受；`in-progress`＝已派发、尚未结项；`planned`＝完整 Demo 仍需交付的后续单元；`approved change`＝用户已改定需求，不等于实现完成。一个页面可同时有已接受基础和待交付行为，分别列行。
- **执行归属**：后端＝“FindMeGamer 后端开发”；前端＝“FindMeGamer 前端优化”；总管＝集成、固定环境与有限验收。下面的“下一单元”是工作分解，不将所有缺项追加入正在验收的增量。

## 可引用的实际验收记录

下列均是既有交付/总管记录。本次矩阵工作未运行测试、原型脚本、真实提供商、SMTP 或生产操作；测试数量不能跨增量相加为通过率。

| 编号 | 已接受实现与记录 | 实际证据及适用范围 |
| --- | --- | --- |
| B1 | Game `dd4b15d`；[Game 后端](backend-v2-library-games.md) | 1,854 passed / 3 skipped 后，将三项 opt-in Redis 测试启用并通过，合计覆盖 1,857 个不同测试；另有 6 个认证真实 HTTP 检查。覆盖手建、资料分层、参考作品、当前版本迁移；提供商为 fixture。 |
| B2 | Creator `275d072`；[Creator 后端](backend-v2-library-creators.md) | 后端全量 1,903 passed、无跳过；多平台身份、多邮箱/来源、作品、重绑定、迁移及来源刷新保留人工值。无真实平台或邮件。 |
| B3 | Discovery `0153a38`；[适配器](backend-v2-discovery.md) | 后端全量 1,973 passed；总管新增 70 项独立通过。YouTube/X 单页适配和连接契约，以 fixture 验证；用量探测不证明搜索授权。 |
| B4 | Activity `c8abe9b`；[持久化发现](backend-v2-activities.md) | 后端全量 2,019 passed；总管新增 46 项独立通过。HTTP→Celery→提供商 HTTP fixture→数据库/Library，含预算、去重追加、停止/继续、失败及未知结果恢复。 |
| B5 | Planning `c530be6`；[服务器规划](backend-v2-discovery-planning.md) | 后端全量 2,049 passed；总管新增 30 项独立通过。另有一次合成游戏输入的真实 DeepSeek HTTP 200 / 结构验证；未附带真实平台发现。 |
| B6 | Evaluation `67f836f`；[渐进式评价](backend-v2-evaluation.md)、[总管最新交接](prd-review-2026-09-08.md) | 执行方全量 2,094 passed，含 100 候选 fixture；总管固定 `cad5565`、独立环境新跑 45 项通过。真实 DeepSeek 三阶段适配器各通过一次，但筛选为零人，后两阶段是独立合成记录；不能宣称真实完整入选链路。 |
| B7 | Activity preparation `8cabb11`；[名单与准备批次](backend-v2-outreach-preparation.md) | 执行方全量 2,125 passed，一次有限独立审查无阻塞；总管固定归档独立复跑 31 项业务/迁移（15.32 秒）与 3 项相关 OpenAPI 契约（4.54 秒）全部通过。0012 历史 Activity/query/evaluation 升级0013保留。9个认证操作、缺项成员和初始快照保留；尚无模板/最终资格/SMTP发送。 |
| B8 | Collection switches `b2b15f4`；[共享渠道开关](backend-v2-collection-switches.md) | 全量2,140通过、3个旧writer活跃迁移测试明确deferred、0失败，一次有限独立审查无阻塞。总管固定归档独立18项通过（2.62秒），含0013→0014保留、独立渠道、在途保存、显式恢复及source checkpoint。仅后端，不代表新Settings界面或真实提供商验收。 |
| B9 | P4/P12 read queries `8cf755efc539f34e4abc8a885652fbcbe1ae8d85`；[读查询契约](backend-v2-query-options.md) | 执行方 2,152 passed、3 个已批准旧 live-writer 迁移用例 skipped、0 failed；总管核对固定归档 `/tmp/fmg-query-8cf755e.8Ybhcu` 的 12 项查询测试（4.04 秒）及 3 项 OpenAPI 测试（4.03 秒），全部通过并正式接受。数据库仍为 0014；临时验收资源已清理。覆盖全体结果先筛选/排序后分页及 Library 摘要；不含命名候选集合、前端 UI 或真实提供商。 |
| F1 | Game `8cbd937`；[Game 前端](../desktop/docs/game-v2-unit.md) | 213 项测试、类型检查、构建；4 条 packaged E2E。真实隔离 API/数据库验证手建、保存、冲突、丢响应重试、返回/凭据恢复。 |
| F2 | Settings `a418081`；[Settings 前端](../desktop/docs/settings-unit.md) | 312 项测试、类型检查、构建；5 条 packaged E2E；12 项 fixture 测试。真实探测器配 HTTP fixtures；SMTP 为无 socket 捕获，保存/连接测试零封、明确确认后捕获一封。 |
| F3 | Creator `3abf262`，已集成至 `cad5565`；[Creator 前端](../desktop/docs/creator-v2-unit.md) | 总管在交付树和集成树新跑 458 项测试、类型检查、构建均通过；前端最终 6 条 packaged E2E 通过。含真实隔离 API 写入、多邮箱、作品、身份重绑/历史只读以及 Game/Settings 回归。 |
| F4（仅源码） | Match `149bc69`；[Match前端交接](../desktop/docs/match-v2-unit.md) | 44文件仅desktop；执行方593测试/typecheck/build通过，总管固定归档独立593项/35文件通过（Vitest13.45秒）、typecheck/build通过。两条新packaged E2E为0完成、旧六条此单元未复跑；保留待授权包早于最终两项修复，不等于该提交产物。最终包/E2E/视觉仍待验收，源码可继续集成开发。 |
| L1 | [有界真实发现](discovery-smoke.md) | YouTube：一页 5 个作品，经 search/channels 各一次 HTTP 200、真实 Celery、数据库和 Library 读回，得到 4 个唯一账号；无追加/重试，实际停止原因 `target_reached`。X 新持久化流程当次零请求：指定 Keychain 读取未返回，不是鉴权/余额失败。 |

## 页面和功能追溯

| 原始页面 / 功能组与来源 | 已接受实现、当前差距与验收口径 | 证据 | 状态 / 负责人 / 下一有限单元 |
| --- | --- | --- | --- |
| [P1.1 选择游戏](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnjghsRhdnq5tKDR7PQFKrSf) | 共享 Game 搜索/详情已具备。Match 入口仍需实现 Library / Steam 同级切换、各自草稿保留、无结果直达 Steam、选择后进入可编辑 P2.1；不能要求先填全资料。基线 [App](../desktop/src/renderer/App.tsx) 中 Match 仍为未接通占位。 | B1、F1、F3；新版入口无已接受 E2E | `in-progress`：前端当前 Match 单元；Steam 分支按下一行另交付。 |
| [P1.2 Steam 提交与失败手填](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnu3Tplyh6cQoTvBzKZFDQSb) | 旧 [Game pipeline](../backend/app/analysis/game_pipeline.py) 可作为复用基础；手工 Game 创建不触发采集。仍需新版合法 `/app/` 提交/回车→来源客观字段→P2.1 的真实接线；粘贴不反复请求、标签不推断，失败保留链接并可重试/直接手填。现有手建 E2E 不能代替此流程。 | B1、F1 明确不包含自动分析；本行为无已接受新版验证 | `planned`：后端解析/Analyze 衔接 + 前端 Steam 入口，单独验证成功、来源冲突和失败手填。 |
| [P2.1 游戏编辑基础](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcn3lWs54B8k2VVIO8QNnpwch) | 名称或官网至少一项，其余业务资料/Steam ID 可空；全字段编辑、来源/人工分层、参考作品添加/去重/移除、保存返回 Library 已接受。来源刷新失败保留成功资料和人工覆盖。 | B1、F1、F3 | `accepted`：后端/前端；保留已接受结论。 |
| [P2.1 当次参考作品与草稿更新](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnvVUVyP5szoN2pVuZPAJaUf) | 后端 Activity 已能冻结明确选择的参考 ID，零参考合法。还需 Match 中选择/不选、返回原编辑上下文；移除只影响本次参考，不删 Library 历史。游戏/Creator 更新影响未发送草稿时须刷新并使旧个性化/资格失效，已发送快照保持不变；该新外联同步未交付。 | B4、B5；B1/F1 明确排除当次选择和新草稿同步 | 当次参考 UI `in-progress`（前端 Match）；新草稿同步 `planned`（后端/前端外联单元）。 |
| [P3 条件与规划](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcn5TxNcn4x9F1Sa1F3ku1czc) | 后端已接受 Game/参考作品→English 规划→查询，以及语言/地区独立、待确认地区文本不作已核验条件、联系方式和粉丝区间并集/未知值规则。前端仍需完整选项与交互：15 种语言及文本补充、30 个市场/代码检索/北美快捷、7 档粉丝精确范围、自定义至少一端、具体模式未知开关保持/回不限重置、应用/取消/Escape。约 100 是目标，600 是单查询上限，不保证凑齐。 | B3–B5；前端当前使用严格契约 fixtures，尚未交付 | 后端基础 `accepted`；前端 `in-progress`：当前 Match 条件与规划 UI。Twitch/Instagram 和采集开关按下方已确认变更执行。 |
| [P4 持续发现](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcndO2hkSU9CKy9XflflsZIeb) | 后端持久化 Activity/query/batch/page、按平台身份去重追加、每批目标/总上限、停止后保留在途结果、继续游标、不足/耗尽/失败可继续使用旧结果已接受。Match UI 尚需实际 API+Worker 串通及返回恢复。 | B3–B5、L1；真实 YouTube 只证明小页发现，不证明 100/600 或 UI 全流程 | 后端 `accepted`；前端/总管 `in-progress`：固定 `cad5565` 专用 API+Worker fixture 环境和 Match E2E。 |
| [P4 匹配评价与作品依据](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnMNjfwkPP5JxG3Mbmm0zAih) | 后端已接受冻结当前候选、Brief 分批筛选、逐人 Deep Match、Match Brief、分批校准/排序、成功步骤保留和失败重试；区分主题适合与实际内容依据，缺证据为未知，UI 不显示名次数字。后续追加不自动纳入旧评价，也不自动选中。完整 Creator Analyze/补充获取未包含在评价中，需后续接入口。 | B6；使用已有资料/最多 20 条已知作品，无新内容采集 | 后端 `accepted`；前端评价 UI `in-progress`；必要 Analyze/证据补齐入口 `planned`。 |
| [P4 用户选择、冻结 N 位](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnK489mc06ci75VcIPfIikHg) → [P6 缺项保留](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcncrNXorGNjuNQpIxsrYNmNg) | 必须跨所有已加载分页全选当前筛选结果；追加默认不选并提示新增数；筛选变化保留仍可见选中项并提示移出数，排序不改变选择。批量发信先停止后续查找并冻结当前账号集合，迟到账号不纳入。**缺邮箱/证据仍属于 N 位，进入准备后标需修复；准备快照允许 chosen email 为空，不能静默丢成员或先有邮箱才允许进入。**多个邮箱只明确选择一个。准备冻结不是最终发送授权。B7已提供显式增删/批量、跨query同账号去重、版本保护与冻结初始快照，前端仍须正确接线这些交互。 | B7；模型管线的 `selected=false` 不代表人选名单，新的 selection API 才是权威来源 | 后端基础 `accepted`；前端 `planned`：当前Match发现/评价结项后，接名单/准备契约与跨分页交互。 |
| [P4 名单保存、查询隔离、排序与证据过滤](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnkbXL4bsv7Uj1blrISCRyAd) | B9 已接受五类证据筛选和相关性/粉丝/最近发布/最近加入排序：完整查询结果筛选/排序后分页，缺失值在后，不修改人选名单或触发评价/采集。旧默认加入顺序保留，新 UI 须明确请求相关性默认；`related_content` 只表示其他已记录内容证据，不自动证明与推广游戏相关或实际观看。“有名称的候选集合”保存/恢复另行实现。 | B4、B6、B9；[读查询契约](backend-v2-query-options.md) | 后端读查询 `accepted`；命名集合后端 `in-progress`（完整回归/单次审查中，未接受）；前端完整筛选/排序与保存名单 `planned`，尚未交付。 |
| [P5.1 统一 Creator 资料与作品](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnBWPfJCXocEvg8n9gc7dPAg) | 多平台单账号建档、资料/人工来源编辑、多个邮箱及用途/来源、已知作品/片段/时间/指标/关联游戏、明确旧/新身份确认及历史只读已接受。未知不写零，标题命中不自动为实玩，已取得作品不宣称全部平台历史。 | B2、F3 | `accepted`：Library 来源的基础详情/编辑；不重开此增量。 |
| [P5.1 多入口与邀请合作](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcn88ke99s0CueqLISP9w8RKc) | Match/Outreach 应复用同一 Creator 和作品详情，返回保留加载、筛选、选择；Library 打开详情不凭空新建活动。名单加入/移出、单人进入 P6、按真实活动列邀请和合作/跟进编辑尚未完整交付。合作八状态、跟进四状态归属具体活动；一次拒绝不改永久可合作性。 | B2/F3 提供可复用详情；新 Activity 邀请关系无已接受 E2E | 复用 Match 详情 `in-progress`（前端）；邀请/合作/跟进 `planned`（后端/前端 P9 单元）。 |
| [P6 / 第三章 固定模板与四槽位](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnzqxjPvo7aWnAKZJZr2xU5b) | 必须绑定 LIMINAL: Within 模板 revision 69：仅称呼、频道名、参考游戏/视频、具体观察四字段可生成/改写，第四槽包含句末句点；主题、Unicode 标点、段落、加粗、Demo URL、签名固定，确定性渲染并验固定片段。换游戏/固定正文需明确新模板版本。旧 [通用模板](../backend/app/outreach/templates.py) 只是复用基础，尚不是新四槽位生产实现。 | PRD 第三章给出的固定片段 SHA-256：`0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93`；原型 21 项合约检查不证明本仓库新流程 | `planned`：后端模板版本/四槽位生成与渲染，再由前端 P6 接入；保留旧邮件/回调历史。 |
| [P6 依据补齐、事实确认、单人重试](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnruGetxmtZ3W9ZInw3g2fAd) | Creator 已有公开称呼确认、来源作品和人工笔记基础；仍需槽位逐项引用、具体可观察片段/笔记、缺项列表、补充后重算、失败只重试该人。模型看到资料不代表发件人实际 following/enjoyed/liked；发件人事实须真实依据或明确确认，不能自动勾选，也不能改中性问候绕过固定模板。 | B2/B6 明确不代表 `sender_watched`；F3 只验证资料确认/编辑 | `planned`：后端证据/资格与四槽位单元；前端同页补齐。允许对明确适用的一组收件人集中确认，不新增逐封审批。 |
| [P7 批量预览、资格、最终发送](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnUNlm8NKNMZWSb7WjdJFBMc) | 总数/可发送/需修复对应同一准备集合；完整邮件可滚动抽看、仅四槽高亮，筛选/抽看顺序不改收件人。全批次校验模板/游戏/哈希/引用/发件人事实/邮箱/发件账户，补证重算、明确排除、零可发送禁用。最后确认实际人/地址/数量/排除数/活动，冻结邮件快照并提交幂等发送；仅明确失败可重试，未知结果先核对。 | B7准备集合；旧发送队列/幂等、B2 历史保护及 F2 SMTP 捕获可复用；没有新 Activity→模板→发送 E2E | 后端准备集合 `accepted`，始终0可发送；资格/预览/最终发送 `planned`（后端/前端）。真实 SMTP 外发尚未验证且当前未授权，不阻塞 fixture 开发。 |
| [P9 同一名单的回复与跟进](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnRxBosYOWLOhvxucG08oVIe) | P4/P6/P7/P9 使用可追溯的同一账号集合；增加当次发送/邀请/跟进列与筛选。人工记录接受/婉拒须来源和时间，打开/点击/扫描不等于接受；继续查找回原 Activity/累计名单，新选择开新批次，不改已发历史。新模板不加 Yes/No 或跟踪链接，旧链接继续有效。 | B4 Activity、旧 [Outreach](../backend/app/api/routes/outreach.py) / [responses](../backend/app/outreach/responses.py) 是复用基础；新版无已接受 E2E | `planned`：后端 Activity 邀请/人工回复/跟进 + 前端 P9/统一详情。先完整实现人工来源路径；自动收件箱同步未获确认，不列为已批准依赖。 |
| [P12.1 Creator Library 基础](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnkgDcoK3VnFeAJHLD8cggpg) | 姓名/账号/已知作品搜索，四平台手工建档，当前单平台/语言筛选，分页、详情编辑、Creator/Game 独立搜索与返回上下文已接受。Twitch/Instagram 历史与手工资料仍可查看编辑。 | B2、F3 | `accepted`：当前 Library 基础；原文多选/排序等见下一行。 |
| [P12.1 完整筛选、排序与行摘要](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnxyKvfIDWqRswf5mjEPUZ0f) | B9 已接受平台/语言多选（字段内并集、字段间交集）、四种 PRD 排序、当前身份的近期作品/有效邮箱数量与联系状态、创建/更新时间；全体筛选/排序后分页。Library 相关性是搜索身份/作品命中相关性，不是游戏适配分；联系状态不等于发送资格。前端仍需同套枚举、多选控件、摘要和显式 PRD 默认排序。 | B2、B9；[读查询契约](backend-v2-query-options.md) | 后端读查询/摘要 `accepted`；前端控件/行展示 `planned`，尚未交付；F3 已接受资料写入/详情结论保留。 |
| [P12.2 Game Library 基础](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcn0s8PwNCYyQCwhVYnSeKRtc) | 名称/开发者/ID/官网搜索、资料不全仍列出，手动新增、全字段/参考作品编辑、保存与返回原列表已接受。 | B1、F1、F3 | `accepted`：Game 资料维护基础。 |
| [P12.2 官网状态、排序与 Match/Steam 入口](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnDooFzqEExqIRD60OtD45Ph) | B9 已接受全部/有官网/无官网筛选、最近更新/最近加入/名称 A–Z 排序及创建/更新时间；依据有效官网字段，包括已有来源回退，明确人工清空仍为无官网。新前端须明确请求最近更新默认并接入筛选/排序。“用此游戏匹配”先入 P2.1、Steam/手填入口仍按各自单元交付。 | B1、F1、B9；[读查询契约](backend-v2-query-options.md)；尚无完整新控件 E2E | 后端读查询 `accepted`；前端筛选/排序 `planned`，尚未交付；F4 限 Match 源码接受、packaged gate 未过，Steam 分支仍 `planned`。 |
| [P15 Settings 导航与必要配置](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnFOcwMeBgSftryeIM33iVHg) | 用户已将占位改为完整原有必要配置迁移：外观/字号、工作区连接、共享服务凭据状态/替换/测试、Game/Creator 周期、SMTP、更新检查/手动下载。六分组已接受；保存和连接测试不自动试发，SMTP 与外联使用同一配置。原文“返回来源页/无来源回匹配”的最终导航随 Match 页面接通一起核对。 | F2、F3；[范围确认第 9 节](prd-review-2026-09-08.md) | 迁移范围 `approved change`，已实现部分 `accepted`；来源返回由前端最终导航验收；新渠道开关见下表。 |

## 已确认的需求变更及交付边界

| 原文 / 既有约定 | 用户已确认的当前范围 | 状态与执行影响 |
| --- | --- | --- |
| 中文 OUTPUT 原型、原生工程样式 | Electron + React + TypeScript，FindMeGamer；macOS 14+；English UI、模型提示/输出和内容；云端后端与共享 Library | `approved change`；F1–F3 已交付桌面基础。保持原页面任务/同页状态要求，不能把原型本地 Store 当新业务后端。 |
| P3 四平台完整真实获取 | YouTube/X 优先；Twitch/Instagram 保留未接入预置和扩展接口，本版无需其真实采集或资格来解锁交付 | `approved change`；未接入不能伪装零搜索结果/可用探测。已存资料仍可用于 Library、匹配和外联。 |
| Settings 原先空容器；现有自动更新只有独立周期 | 新增**云端共享的逐渠道采集 on/off**（YouTube/X/Twitch/Instagram），同时保留每次 Match 的平台选择。关闭后停止该渠道后续采集，含该渠道 reanalysis；保留既有资料及匹配/外联，其他渠道继续 | `approved change`；后端B8 `accepted`，前端独立Settings/Match暂停投影 `in-progress`。在途有界采集单元可保存，随后暂停；重开不自动恢复已暂停任务，未接入平台不因开关变可用。 |
| P9 实际回复路径 | 先完整交付人工回复/来源/时间及活动隔离。自动邮箱同步需另行明确，不把 SMTP 配置成功视为已有收件能力 | `approved change` / 人工路径 `planned`。新模板不追加 Yes/No；既有发送历史和旧响应链接保留。 |
| 原型第四章验证 | [第四章](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh#doxcnHru0A7N3aZRVpgnoLjrJzd) 的 Swift 构建失败、18/31/21/43 项检查描述素材包 OUTPUT 原型，不是本仓库当前缺陷或通过率 | 将正常主流程/恢复场景转成新实现验收；不得执行原型脚本后宣称新服务通过，也不得用其构建失败重开本仓库已接受单元。 |
| 实际数据源与模型 | YouTube 已通过 L1 小页持久化流程；X 早前开发者工具真实搜索 10 位作者成功，但新版持久化 E2E 尚待完成。前端 Keychain 修复不是 X 凭据实测 | `planned`：后续完成已有授权边界内的 X 持久化验证；不伪报平台失败/余额不足，不把 fixture、模型合成结构检查说成真实全流程。必要模型推理已有用户授权，不能因节省推理而省略必要验证。 |
| 安装包 / 发布 | F3 Creator 阶段的旧本机 arm64 `.app` 有签名/图标、9 个 runtime 文件一致及六条 packaged E2E 记录；这些证据不覆盖 F4 Match。当前保留的待授权 Match 包早于最终两项 P2 修复，`app.asar` SHA-256 为 `def5533b90e4dbf3976f3885f5874c2551e5ce25a18de3975f7f8f174ec77ee7`，不等于 `149bc69` 源码产物 | F3 旧阶段包 `accepted`；F4 仅源码 593/typecheck/build `accepted`，Keychain 门禁仍在，两条新 packaged E2E **0 完成**、旧六条未在此单元重跑；最终准确版本包/E2E/视觉未接受。Intel、macOS 14 实机、DMG、Gatekeeper、公证/正式发行仍未验收；无上传、Release、部署或真实外发动作。 |

## 剩余工作顺序与结项条件

1. **完成当前独立单元与尚未通过的门禁。** 后端 B7 名单准备、B8 渠道开关和 B9 读查询已接受；命名候选集合仍在完整回归/单次审查中。前端 Settings 开关 UI 正在开发，独立 `59414` / `b2b15f4` / `0014` 控制已交接前端；旧 `53251` / `0012` 保留，`18090` 不动。F4 Match 源码已接受，最终包/Keychain/E2E 门禁仍待完成，环境 smoke 不替代桌面验收。
2. **接完已交付契约并补齐必要入口。** 前端接 P4/P12 的 B9 筛选/排序/摘要及明确默认、B7 选择跨追加/分页/筛选/返回语义；命名名单待后端结项后接入。Steam 自动解析/手填、必要 Analyze/证据获取入口仍须独立交付，不因读查询接受而删除，也不将前端尚未完成计为全页通过。
3. **完成准备→生成→预览→发送。** 严格 revision 69 四槽位、可追溯依据/发件人事实确认、缺项保留及重算、草稿失效、实际地址/内容最终冻结、幂等/明确失败恢复。先以隔离 SMTP capture 完成正常和异常流程，真实外发仅在获得指定发件账户/测试收件人授权后验证；未发真实邮件须明确写入结项限制。
4. **完成同一名单跟进与整条 Demo。** P9 人工回复来源/时间、活动隔离和合作/跟进状态；继续发现→新批次，历史快照/旧链接不变。最终 packaged E2E 应从 Library/Steam 两入口覆盖 P2→P3→P4→P6→P7→P9，并验证常见断线、取消后到达结果、返回、补证和重试。复用旧基础设施必须验证新版接线，不沿用旧测试数量代替。

每个单元按既有 TDD、适用回归和一次独立有限审查结项；发现新的普通功能缺口记为明确下一单元。范围为内部完整 Demo，不增加高可用、滚动迁移、极端脏数据、防御性 Minor 或生产化强化。已接受增量保持接受，整版完成声明取决于上表剩余正常功能和整条新流程的实际交付证据。
