# Production-shape local integration

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
