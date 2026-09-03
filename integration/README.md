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
fakes inside the API and Worker containers. SMTP is fail-closed and unused.
No public provider, AWS account, mailbox, production dotenv, user AWS config,
or Keychain is accessed.

The default cleanup trap always runs `docker compose down --volumes
--remove-orphans` for that exact unique project and deletes its mode-0600
temporary env/master-key directory. A failed run prints bounded service
diagnostics first. For a quick non-mutating Compose policy check, run:

```bash
bash integration/run.sh --contract
```
