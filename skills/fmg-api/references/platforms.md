# Platform reads

Use `fmg youtube|x|twitch|steam operations`, then `describe OPERATION`. All calls go through the company server; never ask a user for provider keys. Catalog fields include parameters, authorization, stability and paging. `simulated` labels transport coverage, not guaranteed live authorization for every endpoint. Upgrade CLI and Skills together if Twitch is missing; a new CLI alone does not upgrade the gateway.

```sh
fmg youtube describe search.list
fmg --run-id demo-1 youtube call search.list --params '{"part":"snippet","q":"indie horror gameplay","type":"video","maxResults":5}'
fmg x describe searchPostsRecent
fmg --run-id demo-1 x call searchPostsRecent --params '{"query":"indie horror -is:retweet","max_results":10,"expansions":["author_id"],"user.fields":["description","public_metrics","location"]}'
fmg --run-id demo-1 steam call store.search --params '{"term":"LIMINAL: Within"}'
fmg --run-id demo-1 steam call store.appdetails --params '{"appids":"4952700","l":"english","cc":"US"}'
fmg --run-id demo-1 steam call store.recommendations --params '{"appid":"4952700"}'
```

Resolve game-name ambiguity before research. Store search adds `data.candidates` while preserving original JSON in `data.upstream`. Similar-product helper returns unique non-self `data.items`, source URL/time; `name_hint` is a URL slug, not a verified name. Fetch appdetails for selected related IDs. These Store helpers are not guaranteed official Web API methods, may differ by locale and return only one page.

YouTube video search yields `snippet.channelId`; inspect `channels.list` and upload playlist/`playlistItems.list`/`videos.list` for creator context. Batch IDs when supported. `regionCode` affects search market, not proof of creator nationality; `relevanceLanguage` is a relevance hint, not a hard creator-language filter. X recent search yields post authors; `user.fields` and `post.fields` in the current catalog must be explicitly requested. Recent search is not full-history search. Missing country/language is unknown, and follower counts need actual returned metrics.

Default exactly one upstream page. `--max-pages N` deliberately requests up to N pages, emitting one JSON envelope per line. `--max-items N` stops at a completed page and can exceed N; pair with a small provider page size. Set a finite request budget before paging. Never assume a page count is a monetary limit. Save cursors, canonical account IDs and response request IDs. Repeated cursors stop. No automatic data-request retries. Instagram is not supplied; do not pretend it was searched.

Creator research requires count lookup even with no follower filter: YouTube `channels.list` with `part=statistics` → `statistics.subscriberCount` (check `hiddenSubscriberCount`); X account lookup with `user.fields=public_metrics` → `public_metrics.followers_count`. Save source response and timestamp. Unqueried, blocked and genuinely hidden/unavailable are distinct; missing values are never zero. Batch reads where supported and reuse suitable saved responses.

## Twitch (Helix)

```sh
fmg twitch describe searchCategories
fmg --run-id demo-1 twitch call searchCategories --params '{"query":"Minecraft","first":5}'
fmg --run-id demo-1 twitch call getStreams --params '{"game_id":["27471"],"language":["en"],"first":10}'
fmg --run-id demo-1 twitch call getVideos --params '{"game_id":"27471","first":10,"period":"week","sort":"views"}'
fmg --run-id demo-1 twitch call getUsers --params '{"id":["61852275"]}'
fmg --run-id demo-1 twitch call getChannelInformation --params '{"broadcaster_id":["61852275"]}'
fmg --run-id demo-1 twitch call getChannelFollowers --params '{"broadcaster_id":"61852275","first":1}'
```

These IDs are examples, not research targets. The gateway preserves full upstream JSON and encodes repeated array parameters correctly. `response_fields` in `describe` records official field descriptions. Most public reads use server-managed App OAuth; follower totals use company User OAuth. Clients never receive provider tokens. Permission-gated reads are listed as requires-authorization; secrets/media/deprecated operations are unsupported and writes are not exposed.

Use category discovery → streams/videos/clips → unique broadcaster IDs → batched profile/channel reads, with `searchChannels` as an additional channel-name lead. Twitch IDs differ from Steam IDs. On clips, `broadcaster_id` is the stream owner; `creator_id` is the person who clipped it. For every suitable creator, explicitly call `getChannelFollowers` (broadcaster ID, first=1) unless a suitable saved response already exists. `getChannelFollowers.total` is the follower count; `data: []` does not mean zero followers. Detailed follower lists require additional broadcaster/moderator permissions not included here. `getUsers.view_count` is deprecated; don't use it. `getUsers.email` cannot reveal arbitrary creators' private email. A canonical profile is `https://www.twitch.tv/<login>`.

No general country/region or minimum-followers discovery filter exists: inspect returned facts and follower totals, keep unknown location unknown. Language filters refer to content/broadcast language, not nationality. `getVideos` by game is capped at 500 videos; documented cursor paging is for user-based retrieval, so don't promise exhaustive category history. Streams are live snapshots, not proof of past work. Missing videos can mean no retained VODs, not no relevant content. Honor field-specific restrictions in `describe` and upstream rejections; don't silently broaden filters.

Respect `meta.rate_limit` derived from `Ratelimit-Limit/Remaining/Reset`; App and User buckets differ, so one response does not describe all capacity. No fixed unlimited or guaranteed 800-per-minute assumption. A 429 requires respecting reset/Retry-After within the task budget. User-token refresh is server-managed; expired/revoked authorization needs administrator repair, not user recharge. For business contact lookup use the email reference when public API/profile evidence has no email.
