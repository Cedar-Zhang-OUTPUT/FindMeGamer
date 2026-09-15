# Platform reads

Use `fmg youtube|x|steam operations`, then `describe OPERATION`. All calls go through the company server; never ask a user for provider keys. Catalog fields include parameters, authorization, stability and paging. `simulated` labels transport coverage, not guaranteed live authorization for every endpoint.

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

Default exactly one upstream page. `--max-pages N` deliberately requests up to N pages, emitting one JSON envelope per line. `--max-items N` stops at a completed page and can exceed N; pair with a small provider page size. Set a finite request budget before paging. Never assume a page count is a monetary limit. Save cursors, canonical account IDs and response request IDs. Repeated cursors stop. No automatic network retries. Instagram/Twitch are not supplied by this release; do not pretend they were searched.
