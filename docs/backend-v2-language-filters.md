# Language comparison integration correction

The desktop's15 presets send language codes (for example `en`), while editable
Creator fields and source metadata may store labels (`English`). The prior
casefold-only comparison incorrectly excluded a known English creator.

This correction affects **comparison only** in both Creator Library (singular and
repeated language filters) and discovery candidate filtering. Stored manual/source
fields, returned labels and raw work metadata are not rewritten. No migration,
language detection, acquisition, paid model call or frontend change is included.

| Code | English label | Existing localized label |
| --- | --- | --- |
| en | English | 英语 |
| ja | Japanese | 日语 |
| ko | Korean | 韩语 |
| zh-Hans | Simplified Chinese | 简体中文 |
| zh-Hant | Traditional Chinese | 繁体中文 |
| es | Spanish | 西班牙语 |
| pt | Portuguese | 葡萄牙语 |
| fr | French | 法语 |
| de | German | 德语 |
| it | Italian | 意大利语 |
| ru | Russian | 俄语 |
| ar | Arabic | 阿拉伯语 |
| id | Indonesian | 印尼语 |
| th | Thai | 泰语 |
| vi | Vietnamese | 越南语 |

Comparison trims and casefolds. Only the explicit aliases above collapse to a
shared key. Custom labels keep trimmed/casefolded exact matching. `zh` does not
imply either script; `zh-Hans` and `zh-Hant` stay distinct. Regional or unspecified
variants are not guessed. Manual overrides keep their existing priority over
content metadata; `und`/`zxx` remain unusable provider language evidence.

This supersedes only the literal-label comparison description in
[query options](backend-v2-query-options.md). All other filter/order/evidence
semantics remain unchanged.

TDD:24new cases first produced18 intended failures/6 existing-behavior passes;
then the relevant Library/discovery/candidate/saved-set group passed62 tests. One
bounded independent read-only review found no blocker. Full isolated PG17/realRedis
regression: **2184 passed, 3 skipped, 0 failed**,190.01s; one existing Starlette
deprecation warning. Skips remain only the approved old-live-writer migration
cases. The future Outreach A unit's red test was written after this full run's
collection and is not included in this commit or result. No API/migration changes,
real provider, model, SMTP or deployment were used.
