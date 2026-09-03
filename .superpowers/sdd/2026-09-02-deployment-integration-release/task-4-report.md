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
