# Deployment Task 4 implementation report

## Scope and outcome

Implemented the checked-in S3 lifecycle template, idempotent lifecycle merge,
EC2 Instance Role and IMDSv2 validation, and the isolated one-object S3 access
probe. The implementation is limited to:

- `ops/s3-lifecycle.json`
- `ops/configure_s3_lifecycle.sh`
- `ops/validate_instance_access.sh`
- `ops/tests/test_s3_configuration.sh`

This report is the only additional task artifact. No AWS, IMDS, S3, EC2,
Docker, IAM, lifecycle, systemd, or production host operation was run from the
development machine.

## Applied AWS guidance

The EC2 provisioning guidance confirms that bridged containers need
`HttpPutResponseHopLimit=2`, while `HttpTokens=required` is the setting that
enforces IMDSv2. The implementation validates both, plus an enabled metadata
endpoint. It never runs metadata remediation: on mismatch it prints the exact
`aws ec2 modify-instance-metadata-options` command with the already-resolved
instance ID and exits.

The application remains on the plan's existing EC2 Docker Compose topology.
The access probe uses exactly one `docker compose run --rm --no-deps -T api`
container, which therefore follows the same bridged network and boto3
Instance Role credential path as production application writes.

## TDD evidence

### RED 1: absent Task 4 artifacts

The focused test was created before any production Task 4 file and invoked
immediately:

```text
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: ops/s3-lifecycle.json is required
$ echo $?
1
```

This was a genuine missing-artifact RED.

### GREEN 1

The minimal lifecycle template, merge script, and access validator were then
added. After correcting one shell conditional typo discovered by `bash -n`, the
focused behavior passed:

```text
$ bash -n ops/configure_s3_lifecycle.sh ops/validate_instance_access.sh \
    ops/tests/test_s3_configuration.sh
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
```

### RED 2: both production prefixes are mandatory

The controller requires production access validation to accept explicit
bucket, Region, and both nonempty, safe, distinct prefixes. A focused
regression removed `FMG_BACKUP_PREFIX` from an otherwise valid fake-backed run:

```text
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: access validation accepted a missing backup prefix
$ echo $?
1
```

The access validator was minimally changed to require and validate both
prefixes and reject equal or nested pairs. The focused test returned to PASS.

## Lifecycle behavior

The checked-in JSON contains exactly these enabled 30-day rules:

- `FindMeGamerAcquisition30Days` for `acquisition/`
- `FindMeGamerBackups30Days` for `backups/`

Runtime configuration requires an explicit bucket, Region, and both normalized
slash-terminated prefixes, rejecting unsafe, equal, or overlapping values.
The script renders those exact prefixes into the managed rules, fetches the
current bucket lifecycle, removes only the two managed IDs, appends their
current definitions, and applies a `Rules` document. The focused fake-backed
test proves a nested unrelated rule remains semantically identical and each
managed rule is replaced exactly once.

`NoSuchLifecycleConfiguration` is treated as an empty rule list. Any other Get
failure exits before Put; the test proves the fake AWS command log contains no
Put in that case. Temporary current/error/merged documents are confined to a
`mktemp -d` directory removed by an EXIT trap.

## Instance Role, metadata, and access probe

The validator rejects `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` before any
AWS, IMDS, or container operation. It requests an IMDSv2 token, resolves the
instance ID without printing the token, and requires the AWS identity ARN to
be an assumed-role session whose session name is that exact instance ID.

The read-only `ec2:DescribeInstances` response must report:

- `HttpTokens=required`
- `HttpPutResponseHopLimit=2`
- `HttpEndpoint=enabled`

A missing read-only permission produces a direct message to ensure the
Instance Role permits `ec2:DescribeInstances`; validation does not weaken the
identity check. A mismatch prints the exact remediation command but never
executes it.

Only after those gates pass does the script generate a 32-byte random hex ID
and invoke one API container. Its boto3 program creates one random in-memory
payload under the exact `<acquisition-prefix>health/<random-id>` key, reads and
compares it, then deletes that same key in `finally`. It never touches the
backup prefix or any broader acquisition key, and it does not log credentials,
the metadata token, the random payload, or AWS response bodies.

The test replaces AWS CLI, curl, OpenSSL, Docker, and boto3 at the external
boundary. The real embedded probe program executes locally against the fake
boto3 module. Assertions prove exactly one put, one get, and one delete use the
same literal bucket/key, and a simulated get failure still performs the exact
delete before returning failure.

## Dry-run and security evidence

Both environment-free commands render conspicuous inert values and make no
external call:

```text
$ FMG_DRY_RUN=1 bash ops/configure_s3_lifecycle.sh
aws s3api get-bucket-lifecycle-configuration --bucket find-me-gamer-example-bucket --region us-east-1
preserve unrelated lifecycle rules; replace only acquisition prefix acquisition/ and backup prefix backups/
aws s3api put-bucket-lifecycle-configuration --bucket find-me-gamer-example-bucket --region us-east-1 --lifecycle-configuration <merged-rules-document>

$ FMG_DRY_RUN=1 bash ops/validate_instance_access.sh
request an IMDSv2 token without logging its value
resolve the EC2 instance ID with that token
aws sts get-caller-identity --output json --region us-east-1
aws ec2 describe-instances --instance-ids <resolved-instance-id> --region us-east-1 --output json
require HttpTokens=required and HttpPutResponseHopLimit=2; print remediation only on mismatch
...
probe target: s3://find-me-gamer-example-bucket/acquisition/health/dry-run-probe
```

The focused test additionally runs both dry-run paths with fake commands first
on `PATH` and proves their AWS, curl, and Docker logs remain empty.

## Final verification

The final gate covers focused tests twice, both required dry runs, Bash syntax,
exact lifecycle JSON, diff whitespace, exact task scope and executable modes,
credential/private-key patterns, prohibited metadata mutation, unsafe prefix
targets, and generated backup artifacts. ShellCheck and shfmt are not installed
on this host; deterministic Bash execution and `bash -n` provide the available
shell validation.

Fresh final output:

```text
$ bash -n <all three Task 4 shell files>
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
$ FMG_DRY_RUN=1 bash ops/configure_s3_lifecycle.sh
3-line inert lifecycle plan; exit 0
$ FMG_DRY_RUN=1 bash ops/validate_instance_access.sh
7-line inert identity/metadata/probe plan; exit 0
$ jq empty ops/s3-lifecycle.json && <exact lifecycle assertions>
$ <diff, scope, mode, secret, metadata-mutation, prefix, and artifact gates>
task4 final gate: PASS
```

## Self-review and concerns

- The lifecycle merge mutates only the two owned IDs and preserves all
  unrelated rule values.
- Failure to read a nonempty lifecycle never falls through to a destructive
  Put.
- Static credentials are refused; neither scripts nor tests read the real home
  AWS configuration.
- The metadata token and S3 payload are never printed or written to the
  repository.
- The only S3 delete is the exact random health object covered by Task 2's
  health-subprefix delete grant, including cleanup after a read failure.
- No live external operation was performed.

No binding concern remains. The only tooling limitation is that ShellCheck and
shfmt are unavailable on this host.

---

## Fix round 1: protected configuration and Compose rendering

### Reviewed finding

The fixed base expected all four S3 configuration values in the inherited
environment and ran the API probe without `--env-file`. The later normal sudo
deployment path does not preserve `FMG_BACKUP_PREFIX`, and Compose could not
reliably interpolate the Task 1 configuration. The finding was reproducible
and binding for the ordinary operator flow.

This fix changes only `ops/validate_instance_access.sh`, its focused test, and
this appended report. Lifecycle behavior/template, IAM, `.env.example`,
bootstrap, Compose/Caddy, backup/restore, application code, and the recorded
StreamingBody Minor remain unchanged.

### Genuine RED

The focused regression first created a disposable current-user-owned mode-0600
`app.env` containing every Task 1 variable, the four safe S3 settings, literal
Argon/password canaries, and a command-substitution canary. It cleared all
inherited FMG and AWS values, invoked the real validator through the existing
external fakes, and required the protected file to drive both the probe and
Compose commands.

Against base `b8bb9177a6a3f9f8f80a70b9b5e7ac47f7a1a705`:

```text
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: validator must load the protected env and render Compose before the probe
$ echo $?
1
```

The failure was caused by the real validator requiring the cleared inherited
`FMG_S3_BUCKET`, before either the file or Compose could be used.

### Minimal GREEN

Live mode now fixes the configuration path to exact
`/etc/find-me-gamer/app.env`. Only explicit
`--test-mode /path/to/app.env` can select a disposable test file. Live mode
requires a regular non-symlink, root-owned, exact mode-0600 file; test mode
retains the type/mode checks and requires ownership by the executing test user.

The parser reads the file line-by-line and assigns only these exact keys,
without `source`, `eval`, expansion, or logging:

- `FMG_S3_BUCKET`
- `FMG_AWS_REGION`
- `FMG_ACQUISITION_PREFIX`
- `FMG_BACKUP_PREFIX`

Each must occur exactly once. The file values replace conflicting inherited
FMG values deterministically before the existing validation. Static inherited
AWS access-key credentials are still rejected before Compose, IMDS, or AWS
operations.

Before requesting IMDS or creating a container, the validator now runs:

```text
docker compose --project-directory <repository> --env-file <protected-file> config --quiet
```

The single probe uses the same global project-directory and env-file options
before `run --rm --no-deps -T api`. A failed Compose render stops before run.
The environment-free dry run does not read `/etc`; it visibly plans both
commands with exact `/etc/find-me-gamer/app.env` and remains inert.

Focused GREEN:

```text
$ bash -n ops/validate_instance_access.sh ops/tests/test_s3_configuration.sh
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
```

### Regression and security evidence

The focused test proves:

- cleared inherited FMG/AWS values are supplied by the protected file;
- conflicting inherited FMG values are replaced by exact file values;
- one successful `config --quiet` precedes exactly one `run`, with the same
  exact env-file path on both commands;
- missing file/key, unsafe mode, overlapping prefixes, and a symlink fail
  before AWS, curl, or Docker boundaries;
- Compose-render failure never reaches container creation;
- the dotenv command-substitution marker is never created;
- password/hash canaries and file contents do not appear in stdout, stderr, or
  Docker command logs;
- all previously approved Instance Role, IMDS, remediation, single-key probe,
  cleanup, failure, and lifecycle cases remain covered.

The Task 1 Compose regression uses only local `config` rendering and starts no
container. Task 2 bootstrap, Task 3 backup/restore fakes, and Task 4 focused
tests pass. No AWS, IMDS, S3, EC2, IAM, lifecycle, systemd, or production host
operation was executed.

### Final verification

The final gate runs focused twice, Task 1–4 regressions, both environment-free
dry runs, Bash syntax, jq lifecycle validation, Compose render, diff/scope,
secret/config-output/AWS-mutation/artifact scans, and exact executable modes.
ShellCheck and shfmt remain unavailable on this host.

Fresh pre-commit output:

```text
$ bash -n <Task 1-4 scripts and tests>
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
$ bash ops/tests/test_s3_configuration.sh
s3 configuration test: PASS
$ bash ops/tests/test_bootstrap_server.sh
bootstrap server test: PASS
$ bash ops/tests/test_backup_scripts.sh
backup scripts test: PASS
$ docker compose --env-file .env.example config --quiet
$ bash ops/tests/test_compose_config.sh
true  # repeated for all 16 assertions
$ FMG_DRY_RUN=1 bash ops/configure_s3_lifecycle.sh
3-line inert plan; exit 0
$ FMG_DRY_RUN=1 bash ops/validate_instance_access.sh
8-line inert plan with explicit protected env-file; exit 0
$ <jq, diff, exact scope/mode, secret/config-output, no-eval,
   metadata-mutation, and artifact gates>
task4 fix1 final gate: PASS
```

The Compose commands above only rendered configuration; no container or stack
was started. ShellCheck was conditionally skipped because it is unavailable.
The fix commit subject is exactly
`fix: load protected env for instance probe`; its immutable hash is supplied
after commit.
