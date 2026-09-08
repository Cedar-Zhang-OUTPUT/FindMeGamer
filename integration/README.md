# Production-shape local integration

## Persistent frontend HTTP fixture server

For Electron Library/Settings integration, use the smaller **separate** stack:

```bash
python3 integration/frontend_local.py start
python3 integration/frontend_local.py smoke
python3 integration/frontend_local.py stop
```

Run from this checkout (not a different frontend worktree). Default API address:
`http://127.0.0.1:18090`. Only API publishes a loopback port. The fixed, dedicated
Compose project `fmg-frontend-http` has its own PostgreSQL volume and Redis; it
does not use the real local stack or the backend unit-test database. There is
**no Worker or Beat**, no real service configuration, and all provider base URLs
point to closed loopback port 9. Docker Desktop requires a normal bridge for
host access; this is not a network-level outbound firewall. Do not enter real
provider or SMTP credentials here or start background task processes.

The runner generates a random **test-only** Workspace Key and master key under
`.local/frontend-http/`, an existing Git-ignored path. Directory mode is 0700;
`client.json`, `master.key`, and `compose.env` are 0600. It never prints the key,
reads production dotenv/Keychain, or copies credentials from the native client.
Build context is allowlisted by `frontend.Dockerfile.dockerignore`.

The frontend developer may load `base_url` and `workspace_key` from the absolute
path `/Users/cedar/Documents/ChatGPT/FindMeGamer/.local/frontend-http/client.json`
in a local-only test driver/Electron main process, then submit through the same
Settings login flow used normally. Do not put the key in renderer source, URLs,
logs, chat, committed configuration, or screenshots. For manual entry, read it
locally into the secure Settings field; production login remains separate.

Synthetic fixtures (not real accounts):

- Game `Fixture Star Garden`, UUID `10000000-0000-4000-8000-000000000001`.
- Creator `Fixture Cozy Gamer`, UUID `20000000-0000-4000-8000-000000000001`,
  business email `fixture@example.invalid`.

Both are favorites and have simple detail/brief data. No remote image URLs are
seeded. `start` rebuilds current source, migrates the dedicated database, and
inserts fixtures only if absent; `stop` retains its volume and test credentials.
Thus restarting does not overwrite edits made during frontend testing.
`smoke` checks authenticated real HTTP session, v1 lists/details, and v2 games.
It does not enqueue analysis, Match, or outreach. New workflows should use their
own explicit fixtures/tests, not assume this read-only bootstrap validates them.

Configuration-only checks (no real provider use):

```bash
python3 -m unittest discover -s integration/tests -p test_frontend_local.py
python3 integration/frontend_local.py contract
```

## Complete recovery harness

Run the isolated recovery harness with:

```bash
bash integration/run.sh
```

Prerequisites are Docker with the Compose plugin, Python 3, OpenSSL, and enough
local capacity to build the backend image and run Caddy, FastAPI, one Celery
Worker, Celery Beat, PostgreSQL 17, and Redis 7. A typical run takes several
minutes.

The runner creates a unique `fmg-integration-<pid>-<random>` Compose project,
network, and PostgreSQL/Redis/Caddy/fake-state volumes. Only Caddy publishes a
host port, and it is bound to `127.0.0.1`; PostgreSQL and Redis publish none.
All Steam, YouTube, DeepSeek, and S3 traffic is served by deterministic loopback
fakes inside the API and Worker containers. SMTP uses the real gateway with a
capture-only connection factory in the integration Worker: synthetic messages
are saved to the disposable fake-state volume, and no SMTP socket is opened.
No public provider, AWS account, mailbox, production dotenv, user AWS config,
or Keychain is accessed.

Visual stages use small in-memory PNG fixtures through an integration-only image
loader. The fake DeepSeek endpoint requires inline Base64 images and rejects
remote image URLs; both Game and Creator profiles must publish an available
visual-analysis status. Production image fetching remains covered by the image
loader unit tests without introducing public image downloads into this harness.

The runner checks all six Creator Map-Reduce response schemas against the current
backend models, then exercises Analyze, Library detail/search/favorites, Match,
Outreach template/SMTP configuration, preview and send, and the public Yes/No
confirmation pages. Repeating a send request must not duplicate emails, opening
a response link must not record a response, and repeated/conflicting confirmation
POSTs must preserve the first choice. Worker restart, saved Match checkpoints,
scheduled re-analysis, and durable results after Redis loss are also covered.

All Docker and Compose operations have explicit time limits. The default cleanup
trap always runs bounded `docker compose down --volumes --remove-orphans` for
that exact unique project, validates the Compose project/service labels before
deleting only its three API/Worker/Beat build-image tags, and deletes its
mode-0600 temporary env/master-key directory. Cleanup continues to the remaining
exact resources when one step times out. A failed run prints bounded service
diagnostics first. For a quick non-mutating Compose policy check, run:

```bash
bash integration/run.sh --contract
```
