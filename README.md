# Find Me Gamer

## Current delivery: FMG CLI + Codex Skills

The current company service is the independent CLI gateway, not the legacy macOS
backend. Install the CLI and `fmg-api` / `fmg-research` Skills using the
[CLI quickstart](docs/agent-services/quickstart.md). Provider keys stay on the
company server; each user needs a separate revocable gateway token.

The original macOS source is retained below for reference. Its production API,
Worker and Beat are intentionally stopped; installing an old DMG does not connect
it to the CLI service. CLI releases use `fmg-v...` tags and are separate from DMGs.

## Legacy macOS application

An internal macOS workspace for game publishers to analyze Steam games and YouTube
creators, match games with creators in a shared library, and manage email outreach.

The native SwiftUI client supports macOS 14 and later. The backend runs FastAPI,
Celery Worker and Beat, PostgreSQL, Redis, and Caddy through Docker Compose.
Profiles, analysis jobs, matches, service credentials, and outreach records live
on the backend. The interface and AI analysis use English.

## Internal macOS build

Download the DMG and its SHA-256 file from
[GitHub Releases](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases).
The initial internal build connects to **http://127.0.0.1:8000** and requires the
local real backend plus its Workspace Access Key. It does not connect to AWS or
start a backend automatically. A later build will target the deployed HTTPS
service.

1. Verify the downloaded DMG using its `.sha256` sidecar.
2. Open the DMG and drag Find Me Gamer to Applications.
3. Start the local backend using the instructions below, then open the app.
4. If macOS blocks the app because the developer cannot be verified, open
   System Settings → Privacy & Security → Open Anyway after the first launch
   attempt. Follow the confirmation for this app.

This build uses ad-hoc signing, without a Developer ID or Apple notarization.
Company-managed Macs may require IT approval. See
[Apple's installation guidance](https://support.apple.com/en-us/102445).

## Run locally

Follow [Local real services](docs/local-real.md) to start the backend and configure
DeepSeek, YouTube, optional Steam, Google AI email discovery, and SMTP connections.
External service keys are entered through the app and stored encrypted by the
backend; do not commit them to Git.

For an independent UI preview with synthetic data and no backend:

```sh
./script/build_and_run.sh --demo
```

The DMG uses real-service mode; `--demo` is an explicit development option.
See [macOS build and packaging](macos/README.md) for build details.

## Verification

```sh
# Swift client tests
swift test --package-path macos

# Backend tests with isolated PostgreSQL and Redis
docker compose -p fmg-backend-tests -f backend/compose.test.yaml run --build --rm test pytest -q
docker compose -p fmg-backend-tests -f backend/compose.test.yaml down --volumes

# Production-shaped container integration with synthetic external providers
bash integration/run.sh
```

See [Integration testing](integration/README.md) for covered workflows and isolation.
Real cloud/provider acceptance follows deployment; passing synthetic integration
tests does not establish live provider availability or SMTP deliverability.

## Deployment

Server deployment is a separate step. The [operations guide](ops/README.md)
documents the existing EC2 and S3 setup, maintenance-window deployment, database
backups, migrations, and readiness checks. The internal release is intended for
company colleagues; public multi-tenant deployment is outside its scope.

## Repository layout

- `macos/`: SwiftUI client and client tests.
- `backend/`: API, workers, analysis, matching, outreach, and migrations.
- `integration/`: isolated container workflow tests and local provider fakes.
- `ops/`: deployment, backup, restore, smoke, and creator-seeding scripts.
- `script/`: local development and macOS packaging utilities.
- `docs/`: product design and operational instructions.
