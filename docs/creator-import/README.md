# Curated Twitch / Instagram import v1

The importer accepts the already shared [collection handoff](COLLECTION-HANDOFF.md) and its empty [Twitch](twitch.collection-template.json) / [Instagram](instagram.collection-template.json) templates unchanged. Colleagues supply public facts and observations in that format; they do **not** need to rewrite works into internal AI response schemas. Templates contain empty placeholder objects: fill them or remove them as the handoff describes.

`twitch.example.json` and `instagram.example.json` are **synthetic validation examples**, not real creators or verified stable IDs. Never use them to populate a real Library. The [JSON Schema](creator-import.schema.json) documents both envelopes. Real validation also checks identity, source references, credential-bearing URLs, duplicate contacts and platform metric compatibility; JSON Schema alone cannot express all cross-field rules.

## Required collection fields

Each creator requires `platform` (`twitch` / `instagram`), `profile_url` (the account homepage), `username` (without `@`), `display_name`, timezone-bearing `collected_at`, and `followers_precision` (`exact` / `rounded` / `unknown`). Unknown followers, country, language, email and optional metadata remain null or empty collections. Do not substitute Twitch paid subscribers for followers, or YouTube fields for native metrics.

For insertion, normally supply a confirmed numeric-string `platform_account_id` and its credential-free `account_id_source_url`. Confirm it belongs to the homepage: this offline importer validates structure and provenance links, not the truth of a provider response. A null ID still reports `needs_identity_resolution` and cannot be inserted.

For manually collected Instagram accounts only, an explicitly provisional key is also supported: `platform_account_id: "ig-<lowercase username>"`, with `account_id_source_url: null`. It must match the record's username and validated homepage; it is not an official platform ID. The Library keeps its own UUID and marks `source_status.identity` as `{status: "provisional", platform_account_id: null, key: "ig-..."}`. No source URL is fabricated. Matching Instagram usernames also deduplicate across numeric and provisional IDs; `--on-conflict skip` preserves the existing record. Identity conversion/rebinding must be handled separately, never by silently overwriting through import. This exception does not enable live Instagram collection, generate analysis or invent contacts.

Each work requires a locally unique `work_id`, platform work `url`, and native `kind`; publication time may be unknown. Each metric requires its name, value, timezone-bearing `observed_at`, and precision. Optional Twitch aggregate audience/subscriber metrics also require source and reporting period. Each contact requires `email`, `purpose`, public `source_url` and `observed_at`; case-insensitive repeated emails are rejected. Each observation requires its basis, English observation, matching source URL and observation time; work observations reference a supplied `work_id`, and excerpts require `time_range`. Clip ownership means the featured broadcaster, not the clipping viewer. The collector must verify ownership because this command does not fetch works.

All collection fields are preserved under `current_facts.curated_collection`; common identity/name/bio/avatar/follower facts are also projected to the shared Profile core. Contacts become unverified, source-attributed contacts; import never sends mail or marks an address deliverable. Existing contacts and manually owned Profile fields are preserved.

## Validate and explicitly import

From `backend`, with the normal Python environment:

```sh
python -m app.cli.import_creator_profiles --file /path/to/collection.json --dry-run
python -m app.cli.import_creator_profiles --file /path/to/collection.json
```

Dry-run is offline: no database, credentials, providers or model calls. Its `ready` status means structurally ready for insertion, **not** Match-ready, and cannot predict conflicts with existing database records. It reports whether separately supplied analysis exists. Without `--dry-run`, the command uses the configured database and commits the whole batch atomically. Review identities (including explicitly provisional Instagram keys) and material first. Any refusal rolls back the batch. Errors deliberately do not echo rejected input or potentially secret values.

The default conflict policy refuses changed existing records. Identical material and analysis timestamp deduplicate by `(platform, platform_account_id)`. `--on-conflict skip` explicitly preserves existing records, including manually edited Profiles. `--on-conflict replace-unedited` explicitly updates only an existing unedited curated Profile; it refuses manual notes, overrides, editorial revisions or manual contacts, non-curated Profiles, and degrading analyzed Profiles to fact-only. It preserves existing contacts and historical Match snapshots. Updating analysis timestamps also requires this explicit replacement policy.

## Optional analysis belongs to the operator

Both envelopes permit an optional `analysis` per record: `{ "analyzed_at": "<timezone timestamp>", "synthesis": <validated CreatorSynthesis> }`. The synthesis includes the common `creator_brief`; the generated JSON Schema contains the complete internal types. The operator may attach separately prepared analysis after reviewing the supplied sources. This importer does not generate or infer analysis from collection facts/observations and adds no AI calls. Colleagues can deliver the original collection format with this field omitted.

Common evidence references must use `source_type: public_link` and one of `profile`, `work:<work_id>`, or `observation:<zero-based index>` from the same record. No absent work, another platform's source type, or invented visual asset is accepted. Contacts stay in the collection `contacts` array; AI contact selections must be unavailable. Available inference retains the common schema's `ai_inference` labeling. Source-reference validation proves a supplied reference exists, not that every interpretation is substantively correct; operators remain responsible for checking claims against evidence. Do not claim watched content from metadata-only evidence.

Only a resolved, explicitly curated record with validated synthesis and matching Brief, a current analysis timestamp, and current source freshness participates in ordinary Library-wide Match. The existing 30-day analysis cutoff still applies. `analyzed_at` must follow collection and cannot be in the future. Fact-only imports have no analysis timestamp or Brief and remain ineligible. Neither platform is automatically reacquired or reanalyzed; the next analysis schedule remains disabled. Importing never changes the platform's live collection status from unavailable.

Expired analysis is marked stale on import and by the existing periodic stale-marker. Public Profile and Match views also enforce aging at read time, so the interval between marker runs cannot expose expired source facts, analysis, Brief or nonmanual contacts. Historical Match outreach requires a manual contact once curated material expires. Manual overrides and contacts remain available, and the live platform status remains unavailable.

## Official API availability and authorization

Research checked 2026-09-14; this contract does not claim successful provider calls or verified app authorization.

| Source | Potentially obtainable public material | Authorization / limitations |
|---|---|---|
| Twitch Users / Channels | Stable ID, login, name, bio, images; channel language/game/title | Endpoint-specific authenticated app or user token. Server app-token endpoints do not require each creator to sign in. |
| Twitch Videos / Clips | Dated public works, descriptions, durations and endpoint-native view counts | Appropriate authenticated token; verify broadcaster identity for clips. No invented average views or unique audiences. |
| Twitch Followers | Total followers | Total-only access differs from privileged follower-list access. Do not infer the same permissions for both. |
| Twitch email / paid subscribers | Arbitrary creator email or subscriber detail is not generally public API material | Email scope concerns the token owner; privileged details need relevant creator authorization. Deprecated Users `view_count` must not be used. |
| Instagram professional accounts / media | Depending on authorized API path: account identity/bio, followers/media counts, captions/type/permalink and available public metrics | Facebook Login path requires a linked Page and professional account. SDK fields are not proof of authorization or arbitrary-account access. Consumer/private account coverage, arbitrary Insights, audience breakdowns and email are not promised. |

Sources: [Twitch endpoint reference](https://dev.twitch.tv/docs/api/reference/), [Twitch app token flow](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#client-credentials-grant-flow), [Meta official Instagram Facebook Login collection](https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login), [Meta IGUser SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/iguser.py), [Meta IGMedia SDK](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/igmedia.py).

The [Meta Business Discovery documentation](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery/) was rate-limited/unavailable during research. Exact minimum read permissions and this application's qualification remain unverified. Broad permissions listed for an entire API collection are not a reason to request publishing/comment scopes. This limitation does not block curated public-material imports; live Twitch and Instagram collection remains unavailable.
