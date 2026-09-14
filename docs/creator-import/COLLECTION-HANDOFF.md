# Instagram / Twitch 创作者数据采集交接包 v1

2026-09-14。可立即发给负责找人的同事或 Agent。两平台使用同一核心模型，不要求提供 API Key。

这是**采集输入模型**，不是直接写数据库的最终 Profile JSON。导入程序及平台分析接入仍在开发；我们会把这些有来源的材料转换为 Library 的公共资料、分析和 Brief。只收集到主页也可以先交付，但不等于已经具备匹配或发信条件。

## 直接开始

1. 每个平台复制对应的 `*.collection-template.json`。每个文件的 `creators` 可放多位创作者。
2. 填平台、主页 URL、用户名、显示名称和采集时间。正文分析说明用 English；原始简介/标题保留原文，不能翻译后冒充原文。
3. 每位尽量提供近期 5–10 个有代表性的作品，覆盖不同游戏或形式；这是采集建议，不是必须凑满的硬门槛。不足时如实交付。
4. 邮箱能找到就提供邮箱、用途及公开出处；找不到填 `contacts: []`，不猜邮箱。
5. 每项判断写明依据，尤其是语言、游戏偏好、合作信息和作品观察。没有观看就标 `metadata_only`，不能写“我看过”。
6. 把填好的 JSON 和可选证据截图一起给我们。不要传 Cookie、Token、API Key、私人通讯录或整段下载的视频。

模板含有一条空作品和一条空观察作为填写示意。没有对应材料时删除该空对象，使用 `[]`。空白模板本身不是合格的已完成采集记录。

## 核心字段

| 字段 | 是否必需 | 怎么填 |
|---|---|---|
| `platform` | 必填 | `instagram` 或 `twitch` |
| `profile_url` | 必填 | 真实作者主页，不是搜索页或单个作品页 |
| `username` | 必填 | 不带 `@` 的平台用户名；不是显示名 |
| `display_name` | 必填 | 主页展示名称；不需要查私人真实姓名 |
| `collected_at` | 必填 | 采集时刻，带时区，例如 `2026-09-14T12:00:00Z` |
| `platform_account_id` | 可空 | 官方稳定 ID，按字符串保存；不知道填 `null`，不要用用户名假装数字 ID |
| `account_id_source_url` | 有 ID 时必填 | ID 的来源记录位置；API 来源可填不含凭据的接口 URL，采集备注说明取得方式 |
| `bio_original` | 可空 | 原始公开简介 |
| `avatar_url` / `website_url` | 可空 | 公开链接；头像失效不应让整个记录作废 |
| `followers_count` | 可空 | 公开关注者数；Twitch followers 不是付费 subscribers |
| `followers_precision` | 必填枚举 | `exact` / `rounded` / `unknown`；比如页面显示 1.2K，填 1200 + rounded |
| `content_languages` | 可为空数组 | 对象包含语言代码 `code`、依据 `basis`、`source_url`；依据可为 `platform_metadata` / `observed_content` / `creator_statement` |
| `public_location` | 可空 | 作者公开填写的地区原文，仅资料展示，不用于本版 Discover 硬筛选 |
| `platform_metrics` | 可为空数组 | 平台专有公开指标，见下文，不把不存在的值填 0 |
| `works` | 可为空数组 | 作品材料；建议至少 3 条再做有依据的匹配，无法取得时注明限制 |
| `contacts` | 可为空数组 | 支持多个邮箱，各自保存用途与来源 |
| `observations` | 可为空数组 | 基于某个作品或简介的具体观察，不是与特定游戏绑定的排名 |
| `collection_notes` | 可空 | 获取限制、账号改名、来源疑点等；用 English |

所有未获取或无法确定的数字/文字用 `null`，集合用 `[]`。只有公开材料明确显示 0 才填 0。账号稳定 ID 未取得的记录先作为待核对材料，导入前需要解析或人工确认；不能把没有验证的身份当成稳定账号写入库。

## 每条作品 `works[]`

| 字段 | 要求 |
|---|---|
| `work_id` | 必填；此交接包内自定唯一标识，例如 `work-001`，供观察引用 |
| `platform_content_id` | 平台作品 ID，有则填；不知道可空，不能杜撰 |
| `url` | 必填，能打开的作品永久链接 |
| `kind` | Instagram: `post` / `reel` / `carousel`；Twitch: `vod` / `clip` / `stream` |
| `title_original` / `caption_original` | 原始标题/简介；没有标题可空，别把整段字幕塞进来 |
| `published_at` | 带时区的发布时间，可空；不是采集时间 |
| `language` | 实际内容语言代码，例如 `en`，可空；不可仅凭姓名国籍猜测 |
| `game_names` | 明确出现的游戏名列表，不确定就空 |
| `thumbnail_url` | 可空；只有图片不能证明观看过视频 |
| `metrics` | 公开指标对象，指标名、数字、快照时间、精度分开 |
| `summary_en` | 可空，English 简述内容；只概括有依据的事实 |

`metrics[]` 每项为 `{name, value, observed_at, precision}`。Instagram 可记公开的 `views` / `likes` / `comments`；Twitch 可记 `vod_views` / `clip_views` / `live_viewers` / `duration_seconds`。只保存该作品实际可见的字段，不把直播瞬时人数当平均观看人数，也不把视频播放量当独立观众数。

作品必须确实属于这位创作者。Twitch Clip 要核对被剪辑的主播身份，不要把制作 Clip 的观众误认作视频主播。来源只能证明字幕/说明使用某种语言时，不要直接宣称视频口播使用该语言。

`platform_metrics[]` 同样采用指标对象。可记录 Instagram `media_count` / `following_count`，Twitch 在有可靠来源时记录 `average_concurrent_viewers` / `paid_subscribers`。后两项需要说明统计区间和来源；没有就空，绝不是 API 默认都可读。额外写 `source_url` 和 `period_start`/`period_end`（不适用可空）。

## 邮箱与个性化证据

每条 `contacts[]`：

```json
{
  "email": "business@example.com",
  "purpose": "Business inquiries",
  "source_url": "https://example.com/contact",
  "observed_at": "2026-09-14T12:00:00Z"
}
```

上面只是格式示意，不是可以实际发信的联系人。用途区分商务、经纪人、一般联系。公开出现不等于验证可投递，更不等于已同意合作。

每条 `observations[]`：

```json
{
  "work_id": "work-001",
  "basis": "viewed_excerpt",
  "observation_en": "The creator explains a puzzle solution before continuing the playthrough.",
  "source_url": "https://example.com/work",
  "time_range": "00:02:10-00:02:40",
  "observed_at": "2026-09-14T12:00:00Z"
}
```

`basis` 允许 `metadata_only` / `viewed_excerpt` / `viewed_full` / `profile_statement`。没有观看就不要使用 viewed 类型；只看标题可以记录作品主题，但不能写人物反应、剪辑节奏或具体点评。简介观察时 `work_id` 可空，来源必须指向简介所在页面。文本不要含营销套话或无依据的赞美。

## 官方 API 能力：与采集模型不是一回事

Twitch 的官方 Users、Channels、Videos、Clips 接口可以支撑身份、简介、频道游戏/语言、作品及部分公开指标；一般读取需要 app 或 user token。邮箱需要对应用户授权，不能拿我们的 token 读取所有博主的邮箱；Users 的 `view_count` 已废弃，不能使用。关注者总数与关注者明细的权限不同，不能由“无权读明细”推断总数永远不可得。[Twitch 官方参考](https://dev.twitch.tv/docs/api/reference/)

Instagram 的 Meta 官方 SDK 定义了账号简介、用户名、关注者/作品数量，以及作品 caption、媒体类型、permalink 等字段，但 SDK 有字段不代表当前应用有权读取任意账号。本次官方权限文档返回 429，**没有完成 Instagram 授权范围核验，也没有实测接口**；因此不承诺私人账号、任意账号 Insights、受众画像或公开商务邮箱能由 API 直接取得。人工收集合法可见内容不必等待这项核验。[Meta IGUser 官方 SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/iguser.py)、[Meta IGMedia 官方 SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/igmedia.py)

本版两平台继续标记 live collection unavailable，不因人工导入而变成“API 已接通”。这些材料可用来建立共享结构的 Profile；能支持多强的分析取决于材料质量，不保证不同平台的数据丰富度完全一样。

## 交付后如何使用

我们负责校验身份、来源和重复项，再映射到统一 Creator Profile；必要的分析与 Brief 由同一套校验规则生成。原始事实与人工判断分开保存。只有具备可用 Brief 的 Profile 才按原有规则参与 Match；仅有主页/粉丝数不会被伪装成已分析。补资料、是否导入以及真实发信均是后续明确动作。

文件没有放入本系统内部的分数、Top 排名、模型密钥或个人隐私字段。其他 Agent 不需要模仿内部 Pydantic 输出结构。
