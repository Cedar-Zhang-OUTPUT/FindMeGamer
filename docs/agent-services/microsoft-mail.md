# Hotmail sender and reply monitoring

Target mailbox: `ontologyplay@hotmail.com`. Use delegated OAuth2 for both SMTP
and IMAP. The account password is not deployed. Enabling IMAP in Outlook settings
is necessary but does not authorize the server application.

## One-time Microsoft app registration

An administrator with access to a Microsoft Entra directory registers the app.
A personal Hotmail mailbox alone does not supply an app registration/directory.
If no eligible directory exists, arrange one through the company's Azure/Entra
administrator; do not purchase a subscription automatically.

1. Open <https://entra.microsoft.com/> → Entra ID → App registrations → New
   registration. Name it `FindMeGamer Mail`.
2. Choose **Personal Microsoft accounts only**, or **Accounts in any
   organizational directory and personal Microsoft accounts**. A single-tenant
   organizational-only app cannot authorize this Hotmail mailbox.
3. Record the **Application (client) ID**. This identifier is not a secret.
4. Under Authentication, enable **Allow public client flows**. The administrator
   helper uses Microsoft's device authorization flow; no redirect URI or client
   secret is needed.
5. Request only delegated `https://outlook.office.com/SMTP.Send`,
   `https://outlook.office.com/IMAP.AccessAsUser.All`, and `offline_access`.
   The helper requests these scopes at user consent. Do not configure app-only
   Exchange permissions or use another application's client ID.

Official instructions:
- <https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app>
- <https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth>
- <https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code>

## Administrator enrollment

Provision a private directory owned by the service UID 10001, or a private local
administrator directory for enrollment. Never use the repository for tokens.
In the service's Python environment:

```sh
python -m fmg_agent.email.microsoft_admin authorize \
  --client-id YOUR_APPLICATION_CLIENT_ID \
  --mailbox ontologyplay@hotmail.com \
  --store /srv/microsoft-oauth/tokens.json
```

The command prints only Microsoft's verification URL, user code, mailbox, and
expiry. Have the mailbox owner visit the URL, enter that code, verify the
`FindMeGamer Mail` application and approve SMTP, IMAP and persistent access.
Consent is an explicit user action; browser login alone is not authorization.

After consent:

```sh
python -m fmg_agent.email.microsoft_admin complete \
  --store /srv/microsoft-oauth/tokens.json
```

Exit 3 means consent is still pending; wait the reported interval before retry.
Exit 0 confirms SMTP and read-only IMAP authentication. No SMTP MAIL/DATA or IMAP
message-body reads are performed by the probe. If a probe fails after consent,
the private authorization remains saved so it can be checked without enrolling
again. Never activate production on the basis of token acquisition alone.

## Production settings after successful enrollment

```dotenv
FMG_AGENT_SMTP_AUTH=microsoft_oauth
FMG_AGENT_SMTP_HOST=smtp-mail.outlook.com
FMG_AGENT_SMTP_PORT=587
FMG_AGENT_SMTP_ENCRYPTION=starttls
FMG_AGENT_SMTP_USERNAME=ontologyplay@hotmail.com
FMG_AGENT_SMTP_FROM=ontologyplay@hotmail.com
FMG_AGENT_SMTP_PASSWORD=
FMG_AGENT_IMAP_AUTH=microsoft_oauth
FMG_AGENT_IMAP_HOST=outlook.office365.com
FMG_AGENT_IMAP_PORT=993
FMG_AGENT_IMAP_USERNAME=ontologyplay@hotmail.com
FMG_AGENT_IMAP_PASSWORD=
FMG_AGENT_IMAP_FOLDER=INBOX
FMG_AGENT_MICROSOFT_CLIENT_ID=YOUR_APPLICATION_CLIENT_ID
FMG_AGENT_MICROSOFT_TOKEN_STORE=/srv/microsoft-oauth/tokens.json
```

Both API and Worker mount the **same** persistent `microsoft-oauth` volume.
Provisioned token files must be private (0600); the mounted directory is 0700,
owned by UID 10001. The service serializes refresh across processes and saves
rotated refresh tokens atomically before using them. Authorization errors are
returned as safe machine codes, without Microsoft's raw response or secrets.

Before switching, check for active sends/approved queued recipients. Back up
private env, database and the current deployment/image references. Preserve the
existing SMTP recipient allowlist. Verify both protocols with the proposed env
and new image, then recreate only the agent API and Worker. Verify health and
successful inbox polling. Test messages require a separately authorized test
recipient. No automated replay of historical sends is performed.

Changing the sender invalidates old immutable previews for sending; create and
approve fresh drafts under the new sender. Existing send/reply history stays in
the database. The single-mailbox monitor follows the new mailbox after switching,
so replies arriving only in the former mailbox need separate monitoring if that
is still required.

Rollback: restore the private env backup and previous image/compose references,
then recreate only API/Worker. No schema changes are required for OAuth support.
