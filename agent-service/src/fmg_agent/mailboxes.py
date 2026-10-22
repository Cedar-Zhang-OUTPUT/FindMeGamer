"""Private mailbox configuration and read-only, allowlisted discovery."""

from copy import deepcopy
import json
import stat

from pydantic import BaseModel, ConfigDict, Field, create_model

from .config import Settings
from .errors import ApiError


# This is the complete isolation boundary. Shared infrastructure is retained,
# while every mail field is replaced even when absent from a registry entry.
MAIL_FIELDS = (
    "email_retention_days",
    "email_transport",
    "email_send_interval_seconds",
    "smtp_host",
    "smtp_port",
    "smtp_encryption",
    "smtp_username",
    "smtp_password",
    "smtp_auth",
    "smtp_from",
    "smtp_allowed_recipients",
    "smtp_save_sent_copy",
    "imap_sent_folder",
    "imap_host",
    "imap_port",
    "imap_username",
    "imap_password",
    "imap_auth",
    "microsoft_client_id",
    "microsoft_token_store",
    "microsoft_graph_token_store",
    "imap_folder",
    "imap_extra_folders",
    "imap_poll_seconds",
    "imap_lookback_days",
    "smtp_allow_insecure_loopback",
)


class _ProfileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    enabled: bool = True
    display_name: str = ""
    allowed_templates: list[str] = Field(default_factory=list)


def _mail_field(name):
    field = deepcopy(Settings.model_fields[name])
    if name.endswith("token_store"):
        field.repr = False
    return field.annotation, field


# Reuse Settings' types, validation constraints and defaults without invoking
# BaseSettings: registry entries must never consult process environment secrets.
MailboxProfile = create_model(
    "MailboxProfile",
    __base__=_ProfileIdentity,
    **{name: _mail_field(name) for name in MAIL_FIELDS},
)


def configuration_invalid():
    return ApiError(
        503, "mailbox_configuration_invalid", "Mailbox configuration is invalid."
    )


class MailboxRegistry:
    def __init__(self, settings, profiles, *, legacy):
        self._settings = settings
        self._profiles = {profile.id: profile for profile in profiles}
        self._legacy = legacy

    @classmethod
    def load(cls, settings: Settings) -> "MailboxRegistry":
        if settings.mailboxes_file is None:
            profile = MailboxProfile(
                id="ontologyplay",
                display_name="Ontology Play",
                allowed_templates=["liminal-outreach", "game-outreach"],
                **{name: getattr(settings, name) for name in MAIL_FIELDS},
            )
            return cls(settings, [profile], legacy=True)
        try:
            path = settings.mailboxes_file
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError()
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or set(data) != {"mailboxes"}:
                raise ValueError()
            entries = data["mailboxes"]
            if not isinstance(entries, list) or not entries:
                raise ValueError()
            profiles = [MailboxProfile.model_validate(entry) for entry in entries]
            identities, addresses, paths = set(), set(), set()
            for profile in profiles:
                if profile.id in identities:
                    raise ValueError()
                identities.add(profile.id)
                if profile.smtp_from:
                    from .email.sending import email_address

                    address = email_address(profile.smtp_from).casefold()
                    if address in addresses:
                        raise ValueError()
                    addresses.add(address)
                elif profile.enabled:
                    raise ValueError()
                for name in ("microsoft_token_store", "microsoft_graph_token_store"):
                    token_path = getattr(profile, name)
                    if token_path is None:
                        continue
                    if not token_path.is_absolute():
                        raise ValueError()
                    resolved = token_path.resolve()
                    if resolved in paths:
                        raise ValueError()
                    paths.add(resolved)
        except (OSError, ValueError, TypeError, RuntimeError):
            raise configuration_invalid() from None
        return cls(settings, profiles, legacy=False)

    def select(self, mailbox_id: str | None, *, allow_legacy: bool) -> MailboxProfile:
        if mailbox_id is None:
            if not (allow_legacy and self._legacy):
                raise ApiError(422, "mailbox_selection_required", "Select a mailbox.")
            mailbox_id = "ontologyplay"
        profile = self._profiles.get(mailbox_id)
        if profile is None:
            raise ApiError(404, "mailbox_not_found", "Mailbox was not found.")
        if not profile.enabled:
            raise ApiError(409, "mailbox_disabled", "Mailbox is disabled.")
        return profile

    def settings_for(self, mailbox_id: str) -> Settings:
        profile = self.select(mailbox_id, allow_legacy=False)
        return self._settings.model_copy(
            update={name: deepcopy(getattr(profile, name)) for name in MAIL_FIELDS}
        )

    def profiles(self) -> tuple[MailboxProfile, ...]:
        """All configured identities, including disabled historical senders."""
        return tuple(self._profiles.values())

    def current(self) -> "MailboxRegistry":
        """Revalidate the authoritative private file at operation boundaries.

        Without a file, the process configuration is the authority. Retain
        explicit in-memory registries used by embedded callers in that mode.
        """
        return self.load(self._settings) if self._settings.mailboxes_file else self

    def _ready(self, profile):
        if not profile.enabled:
            return False
        from .email.sending import smtp_ready
        from .email.microsoft import MailOAuthError, client_id, read_store

        config = self.settings_for(profile.id)
        if not smtp_ready(config):
            return False
        if (
            config.email_transport == "microsoft_graph"
            or config.smtp_auth == "microsoft_oauth"
        ):
            graph = config.email_transport == "microsoft_graph"
            path = (
                config.microsoft_graph_token_store
                if graph
                else config.microsoft_token_store
            )
            try:
                client_id(config.microsoft_client_id)
                read_store(
                    path,
                    config.microsoft_client_id,
                    config.smtp_from if graph else config.smtp_username,
                    profile="graph" if graph else "outlook",
                )
            except (MailOAuthError, OSError, AttributeError):
                return False
        return True

    def public_entries(self) -> list[dict]:
        from .email.pacing import interval_choices, minimum_interval

        return [
            {
                "id": profile.id,
                "from": profile.smtp_from,
                "display_name": profile.display_name,
                "enabled": profile.enabled,
                "ready": self._ready(profile),
                "allowed_templates": list(profile.allowed_templates),
                "send_interval_seconds": minimum_interval(
                    profile.email_send_interval_seconds
                ),
                "send_interval_choices_seconds": list(
                    interval_choices(profile.email_send_interval_seconds)
                ),
            }
            for profile in self._profiles.values()
        ]
