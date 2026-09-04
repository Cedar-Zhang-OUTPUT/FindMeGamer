# Local real backend

This profile keeps the real FastAPI, Celery Worker, PostgreSQL 17, and Redis 7
services running for the macOS client. It stores acquisition artifacts on a
shared Docker volume and does not require AWS or an S3-compatible server. Steam,
YouTube, DeepSeek, and SMTP remain real integrations and are configured from the
app's Settings screen when needed.

Prerequisites are Docker with the Compose v2 plugin and OpenSSL. From the
repository root, start the default services with:

```bash
script/local_real.sh start
```

The launcher creates private local credentials under
`.local/find-me-gamer/`, builds the backend, starts PostgreSQL and Redis, runs
`alembic upgrade head`, and only then starts the API and Worker. The API is
available only at `http://127.0.0.1:8000`; PostgreSQL and Redis have no host
ports. The filesystem artifact volume is shared by the API and Worker.

To include the periodic Celery Beat scheduler, opt in explicitly:

```bash
script/local_real.sh start --beat
```

The other commands are:

```bash
script/local_real.sh status
script/local_real.sh logs
script/local_real.sh logs worker
script/local_real.sh key
script/local_real.sh stop
```

`key` is the only command that prints the Workspace Access Key. Keep it private
and enter it in the macOS app when connecting to `http://127.0.0.1:8000`.
`logs` prints the latest 200 lines and never intentionally prints local key
files. `stop` removes this Compose project's containers and network while
retaining the PostgreSQL, Redis, and artifact volumes for the next start.

For the current v1 smoke flow, configure only YouTube and DeepSeek in Settings.
Steam Store analysis uses the public Store endpoint, so leave the optional Steam
credential empty; its Settings connection test is not used by this flow.

The generated directory is ignored by Git. Removing it loses the displayed
Workspace key and AES master key; existing encrypted settings cannot be
recovered without that master key. This local profile does not start Caddy,
publish database ports, send mail automatically, or configure provider secrets.
