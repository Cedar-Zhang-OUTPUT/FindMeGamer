# FMG CLI and Skills 0.5.1

- Suitable creator results now include business-contact lookup by default. Read
  public bio/profile contacts first, then use email enrichment when absent; retain
  jobs and distinguish pending/failed lookups from completed Not Found results.
- Browser and Excel share nine columns: sequence, Public name, email, detailed
  Match rationale, content direction, channel URL, followers, language and audience
  region. Display actual addresses and purposes, not only a status word.
- Match rationale has evidence, gameplay connection, assessment, collaboration
  angle and AI boundaries. Unknown facts remain explicit; no fabricated values.
- Added local result validation through research_dashboard.py --validate.
  Incomplete/legacy records remain visible, but final delivery must report missing
  fields and unfinished contact lookups rather than claim completeness.
- Liminal v4's approved inline signature-image exception is documented.

Upgrade with `fmg upgrade --latest --skills`. Reread both installed Skills and
restart the local dashboard. Existing briefs are not silently rewritten or enriched;
the Agent must fill their missing fields from evidence and complete pending contacts.
No server deployment or automatic sending is part of this release.
