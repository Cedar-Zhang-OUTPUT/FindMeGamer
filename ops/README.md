# Find Me Gamer host operations

These procedures prepare the existing US EC2 host for the six-service Docker
Compose stack. They do not create or modify EC2 instances, Security Groups, or
IAM attachments.

## Bootstrap the host

Run the bootstrap from a trusted checkout as root:

```bash
sudo ops/bootstrap_server.sh
```

Production bootstrap requires Docker with Compose v2, `curl`, `jq`, `openssl`,
AWS CLI v2, and systemd. It creates `/opt/find-me-gamer` and two root-owned
mode-`0600` files under `/etc/find-me-gamer`. It builds the API image before it
silently reads the Workspace Access Key, then passes that plaintext to the
one-off backend hasher only through standard input. Reruns preserve both files.

Before deployment, set `SERVICE_DOMAIN` to the approved company hostname,
confirm that `BACKEND_SUBNET` does not overlap a host/VPC route, confirm
`FMG_AWS_REGION`, and replace every remaining `replace-with-` value in the
protected environment file:

```bash
sudoedit /etc/find-me-gamer/app.env
sudo chmod 0600 /etc/find-me-gamer/app.env /etc/find-me-gamer/master.key
sudo grep -En 'replace-with-|\.invalid$' /etc/find-me-gamer/app.env
sudo grep -Eq '^AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)=' \
  /etc/find-me-gamer/app.env && echo 'remove static AWS credentials' >&2 && false
```

The placeholder `grep` must produce no output. Keep one recovery copy of
`master.key` in the company password manager. Never store that recovery copy in
Git or S3, and never paste it into command arguments, tickets, or logs.

Confirm Docker data is on the existing EBS-backed filesystem:

```bash
findmnt -T /var/lib/docker -o SOURCE,FSTYPE,TARGET,OPTIONS
```

## Existing EC2 and network checks

The EC2 Instance Role supplies S3 credentials. Do not add static AWS access
keys to `app.env`, Compose, images, or shell profiles. Confirm the active
identity is an assumed role:

```bash
aws sts get-caller-identity --output json | jq -e \
  '.Arn | contains(":assumed-role/")'
```

The existing instance must enforce IMDSv2 with `HttpTokens=required` and use
`HttpPutResponseHopLimit=2`; the second hop is required for bridged containers.
Task 4 owns validation and any remediation. An operator can inspect the current
settings without changing them:

```bash
instance_id="$(curl -fsS -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
  -X PUT http://169.254.169.254/latest/api/token | {
    IFS= read -r token
    curl -fsS -H "X-aws-ec2-metadata-token: $token" \
      http://169.254.169.254/latest/meta-data/instance-id
  })"
aws ec2 describe-instances --instance-ids "$instance_id" \
  --query 'Reservations[0].Instances[0].MetadataOptions.{Tokens:HttpTokens,HopLimit:HttpPutResponseHopLimit}' \
  --output json | jq -e '.Tokens == "required" and .HopLimit == 2'
```

Review the existing Security Group before release: public inbound is TCP 80 and
443 only. Restrict SSH to the company's selected administration source, or use
SSM Session Manager instead. PostgreSQL 5432 and Redis 6379 must never be host
ports. From `/opt/find-me-gamer`, verify the rendered Compose publication:

```bash
docker compose --env-file /etc/find-me-gamer/app.env config --format json |
  jq -e '[.services | to_entries[] | select(.key != "proxy") | .value.ports // []] | flatten | length == 0'
```

## Instance Role policy template

Copy `ops/iam/ec2-s3-prefix-policy.json` outside the checkout and replace every
`REPLACE_WITH_...` token before attachment. Use the one configured private
bucket plus the approved backup and acquisition prefixes; enter prefixes
without leading or trailing slashes. Confirm `FMG_AWS_REGION` in `app.env` and
the AWS CLI Region match the existing EC2 host and bucket; S3 policy ARNs do
not contain a Region component. Refuse attachment while any placeholder remains:

```bash
jq empty /path/to/rendered-ec2-s3-prefix-policy.json
! grep -q 'REPLACE_WITH_' /path/to/rendered-ec2-s3-prefix-policy.json
```

Attach the rendered policy to the existing EC2 Instance Role, not to a user and
not as static credentials. The template permits object reads/writes only under
the backup and acquisition prefixes, bucket listing limited to those prefixes,
and bucket lifecycle inspection/update for retention setup. Object deletion is
limited to the acquisition health-probe subprefix used by Task 4; backups and
all other acquisition objects cannot be deleted by this policy.
