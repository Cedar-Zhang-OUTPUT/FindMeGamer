# P1.2 Steam 解析与 Library Analyze 最小实现交接

依据：已接受提交 `8cabb112f4b6f6b318aff2c2732cff71fe0beea8`（2026-09-08），以及协调任务已核验的 PRD 751 相关要求。
本次仅检查固定归档中的相关代码并准备交接；没有实现、执行测试、stage，未据当前渠道在制代码作结论。
下列新方法/路径是建议接口，尚未成为已接受契约；采集开关只消费后续最终接受的契约，不在此推定字段或行为。

## 1. P1.2：显式提交 Steam 链接，来源字段进入可编辑 P2

- 输入/粘贴仅更新草稿；有效 `https://store.steampowered.com/app/<id>[/slug]` 在 Submit 或 Enter 后才请求一次解析。
- 复用 `backend/app/analysis/targets.py::canonicalize_target` 的 Steam 规范化及 `backend/app/integrations/steam.py::SteamGateway.fetch_game`。
- `SteamGameSource` 已包含名称、开发商、简介、genres/categories、语言、发布日期、封面等客观来源；缺失字段保持空值，P2 可手填。
- 现有 appdetails 提供 genres/categories，未提供“Steam 用户标签”专用采集；可明确标注来源地使用 genres，不能借 AI 补造用户标签。
- `backend/app/repositories/library_v2.py::source_fields` 已把当前来源投影到 `GameFields`；沿用开发商、语言、简介、封面等映射规则。
- **正常流程缺口：没有公开 Steam 来源解析接口。** 旧 `GameAnalysisPipeline.run` 会继续调用 DeepSeek extraction/vision/synthesis，不能把整条分析任务当作仅来源解析。
- 建议新增一个专用来源导入桥接：`games.parseSteam({url, gameId?, expectedRevision?, idempotencyKey}) -> GameDetail`；对应例如 `POST /api/v2/library/games/steam-import`，由后端冻结实际名称。
- 此桥接读取 Steam，按来源 Steam ID 查找/建立 Game，写来源字段并返回原有 v2 `GameDetail`；不调用模型、不标记 `last_analyzed_at`，新建记录遵循 v2 首次分析 seed 语义。
- 解析成功即将返回的 `game.id` 和 `revision` 交给 P2；P2 修改只通过现有 `PATCH /api/v2/library/games/{id}` 写人工覆盖，不能把所有解析字段再次作为人工覆盖保存。
- 同一 Steam ID 已存在时复用该 Game；保留其人工字段、参考作品和完整分析历史。来源解析成功本身不代表已有分析已更新。
- 请求失败保留原链接、已填字段和已知 Game ID，展示 Retry / 手填；普通网络重试沿用本次请求键，不重新建立另一条 Game。
- 首次尚未有 Game ID 时，手填复用现有 v2 create：至少名称或 `website_url`；有效 Steam 链接可带规范化 `steam_app_id` 建立绑定 seed，原输入链接仍留在草稿。
- 已有 Game ID 的失败手填继续 PATCH 该 Game；来源请求失败不能擦除已保存来源或人工字段。改了输入链接是新的显式请求，不应重用旧请求键。

## 2. Library Analyze：复用旧任务 API，补 typed 接线

| 业务动作 | 已有后端接口 / 返回 |
| --- | --- |
| 新 URL Analyze | `POST /api/v1/jobs/analysis`，`{target_type:"game"|"creator",url,mode:"create"}`，必带 `Idempotency-Key` |
| 已选且已绑定 Library 条目补分析 | 同一路由，建议统一 `mode:"reanalyze"`，目标取 `source_identity.canonical_url` |
| 读取一项任务 | `GET /api/v1/jobs/{job_id}`，返回 `AnalysisJobResponse` |
| 恢复/刷新 Analyze Request 抽屉 | `GET /api/v1/jobs?changed_after=<cursor>&limit=...`；响应含 analysis/match 联合类型、cursor、has_more、affected_profile_ids |
| 已失败任务普通重试 | `POST /api/v1/jobs/analysis/{job_id}/retry`，空 body，新的重试动作使用一个稳定请求键 |

- 创建结果是 `outcome:"job"` 或 `outcome:"existing_profile"`；后者是已有条目导航结果，不可渲染成新完成任务。
- `create` 已分析目标会返回 existing_profile；`reanalyze` 绕过该短路，已有 queued/running 任务仍会复用。
- Retry 只对 failed 且 `retryable=true` 开放；创建新的历史 job 或复用活跃 job，不能把失败任务直接改成 queued，也不能用全新 URL Analyze 代替普通重试。
- 抽屉按 job ID 保留 queued/running/failed/succeeded、阶段/进度/错误、Retry 和结果跳转；关闭抽屉不取消任务，恢复时消费已有 jobs cursor 协议。
- 成功后用 `profile_id` 重新读取 v2 Game/Creator detail 并刷新 Library；`canonical_target_id` 是 Steam/YouTube 账号 ID，不是库内 UUID。
- 固定版 `desktop/src/shared/bridge.ts`、`preload/index.ts` 和 `main/application.ts` 只有 Library/Game/Creator CRUD，没有 jobs 业务方法；`main/transport.ts` 的旧 Library GET 也不允许 jobs 路径。
- 最小新增 typed `AnalysisAPI`（create/read/changed/retry 与 outcome/status DTO）及专用 main client/transport/IPC；Steam 解析方法接同一业务边界，继续复用 `Result<T>` 和公共错误结构。
- `sharedLibrary` 消费方应使用 v2 `GameDetail` / `CreatorDetail`，与 Library 共用已选 UUID、当前 revision 和重新读取动作；固定版没有名为 sharedLibrary 的实现，具体前端挂载位置以届时接受版本为准。
- 保留 Library 的 Analyze 入口和 Analyze Request 抽屉，以及 Game/Creator 详情补分析入口；不能以只交付手工 CRUD 代替这些能力。

## 3. 首次分析与身份边界

| 条目状态 | 最小接线 / 必须补齐的普通流程 |
| --- | --- |
| 新建时已带 Steam ID 的手工 Game | 已绑定；`GameAnalysisService.finalize` 按来源 Steam ID 找回原 UUID，人工覆盖和参考作品保留；首次与后续都可由详情 `reanalyze` 触发 |
| Game 先无 Steam ID，之后只改业务 Steam 字段 | `LibraryGamesRepository.patch` 只写 manual_overrides，来源仍未绑定；直接用新 URL 建旧 job 可能生成另一 Game，不能承诺原 UUID 补分析 |
| 对上述未绑定 Game 显式首次绑定 | 来源导入桥接必须支持选定 `gameId + expectedRevision` 后首次绑定并复用 UUID；用户提交来源链接是明确绑定动作，不可把普通字段编辑默认为绑定；这是待实现的小后端桥接 |
| 已绑定 Game 的业务 URL/Steam 字段与来源不同 | Analyze 仍使用 source_identity；更换已绑定来源不属于此次最小接线，不拿业务覆盖重定向历史任务 |
| 手工 YouTube Creator 已带 UC ID | 现有 create/首次 pipeline 会复用 UUID，后续 `reanalyze` 更新来源和分析并保留人工资料、联系人/作品覆盖 |
| 仅 profile_url 的 YouTube Creator | 当前 create 不解析 URL，youtube_channel_id 为空；直接旧 jobs Analyze 会另建 UUID。需先解析 handle/channel 并显式绑定到选定 Creator，再排队；可复用现有 PUT `/api/v2/library/creators/{id}/identity` 的绑定逻辑 |
| discovery 导入的 YouTube metadata 条目 | `manual_revision=0` 且无 last_analyzed_at，旧 jobs `create` 会返回 existing_profile；详情统一 `reanalyze` 即可进入首次真实分析，不要仅按 last_analyzed_at 选择 create |

Creator 分析目标同样取 `source_identity`，可编辑的顶层 `profile_url` 不是账号绑定。首次 URL 解析/绑定桥接必须保住选定 UUID，再复用旧任务排队与发布，不重写已接受 pipeline。

## 4. Creator 平台能力：保留 Analyze，并如实列出待实现部分

- **YouTube：完整 Analyze 可复用。** `analysis/runtime.py` 生产组装 `CreatorMapReducePipeline`，采集最多 50 条视频并调用 DeepSeek 文本/视觉分析；Google AI 邮箱研究为可选部分。
- **X：当前只有真实 metadata discovery。** `integrations/x_discovery.py::XDiscoveryGateway` 读取 `/tweets/search/recent` 的近期帖子、作者及公开指标；`discovery/library.py::import_discovered_account` 落入 metadata_only 来源/作品。
- 这条 X 链路没有完整 Creator DeepSeek 分析；旧 jobs URL 规范化也只支持 YouTube Creator。不能展示“X 已完成完整 Analyze”，也不能用候选评价结果冒充完整 Creator 分析。
- 要交付 X 完整 Analyze，需要新增 X 任务目标接线、面向选定账号的证据采集/覆盖说明、适配 X 的分析 pipeline 与 v2 同 UUID 发布；可复用现有公开账号/帖子 metadata、结构化来源与作品存储、任务状态协议和 DeepSeek 网关，不能把近期搜索当完整账号历史。
- X Analyze 是明确待实现能力，入口保留并呈现当前可用范围；若本单元要求 X 完整成功闭环，上述后端工作就是交付阻塞项，不能通过隐藏 Analyze 将其结项。
- **Twitch / Instagram：预置/手工记录。** 当前无 Creator Analyze pipeline，discovery worker 返回 not_supported；入口/平台选择应说明未支持，不能伪装可执行或成功。
- 当前 v2 `analysis_available` 仅对已绑定 YouTube 为 true；该字段不表示渠道采集开关。开关独立开发，最终按已接受契约展示能力/禁用原因和可执行动作。

## 5. 对应 fixture：只覆盖上述普通流程

- Steam 客观来源：复用 `backend/tests/unit/integrations/test_steam.py::_steam_payload` / `httpx.MockTransport`，补解析成功、缺字段、超时/不存在→保留链接→Retry/手填；断言解析阶段模型调用为零。
- v2 Game：复用 `test_library_v2_games.py` 和 `test_library_v2_analysis.py`；已有 `test_first_analysis_reuses_manual_steam_seed_uuid`、成功/失败保持人工字段测试，新增来源导入→P2 PATCH→Analyze 同 UUID、未绑定 Game 显式绑定同 UUID。
- 任务 API：复用 `test_analysis_job_creation.py` 的 existing_profile、reanalyze、active job 复用和 `test_retry_creates_new_historical_job_and_replays_same_key`；前端 fixture 要区分创建响应不明的同键重放与失败 job 的 Retry。
- Creator：复用 `test_library_v2_creators.py::new_creator`、`test_library_v2_creator_analysis.py`、`test_creator_analysis_commit.py`；新增 URL-only 绑定后首析、discovery metadata YouTube 详情 Analyze，均核对原 UUID。
- 生产 YouTube 路径：复用 `test_creator_map_reduce_pipeline.py` 的 pipeline fixture 和 `test_runtime.py` 的生产装配；部分旧 v2 集成 fixture 使用旧 CreatorAnalysisPipeline，不能单凭它声称已覆盖生产 MapReduce。
- X：复用 `backend/tests/test_x_discovery.py`、`tests/test_discovery_library.py` 的账号/帖子 fixture；当前只能证明 metadata。完整 X Analyze 另需 pipeline→job→同 UUID 发布 fixture。
- 桌面：扩展 `desktop/tests/game-fixtures.ts`、`creator-fixtures.ts`、`games-renderer.test.tsx`、`game-client.test.ts`；增加 Submit/Enter、粘贴不请求、失败手填、任务抽屉恢复/重试和成功回写 Library 的 typed fixture。
- 后端端到端模板可借 `test_analyze_vertical_slice.py` 的离线 resolver/AfterCommitDispatcher；`integration/compose.frontend.yaml` 只有静态 Library fixture、无 worker且提供商指向关闭端口，不足以验证 Analyze 完成闭环。
- 实施时另建独立 fixture 展示上述成功/失败过程；本准备任务未启动服务、未执行测试，未触碰 18090 或已交给前端的 53251 项目。

## 6. 新查询联调观察：自动资料的语言投影

这是后续 Analyze/来源发布单元的接线核验项，不加入正在开发的 Outreach A，也不重开已接受的语言别名比较修复。`a852307` 的别名比较只处理已有语言值；当前 `CreatorLibraryRepository.source_fields` 仅从 `current_facts.languages` 取值，而 YouTube `CreatorAnalysisService._current_facts` 与 discovery 的账号元数据发布均未填此字段。X 作品已有 `source_fields.language`，发现过滤可以据此次内容语言工作，但 Library 的 Creator 语言列表不会自动因此获得值。新 fixture 六名自动导入账号的 Creator 语言都是空值，手工写入后 en/English 比较则正常。

完成 Analyze→新版 Library 时，应验证有明确内容语言来源的已抓取/已分析账号确实能在详情和语言筛选中使用该信息，同时保持人工覆盖优先、当前账号身份限制和未知值语义。不要把 `audience_inference.primary_language` 的 AI 受众推测直接写成已核实的内容语言事实；如需展示推断须保留其推断性质与来源。不新增语言识别服务，不把没有可靠语言依据的账号硬标英文。对应正常夹具应包含自动来源有语言/无语言、人工覆盖及身份变化，而不是仅用手建三个语言样本声称自动来源接线已验收。
