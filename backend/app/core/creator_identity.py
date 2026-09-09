"""Activity identity for saved accounts, including URL-only Library records."""


def creator_account_key(creator):
    # The prefix is an internal reference, never an invented provider account ID.
    # Binding a real ID increments identity_revision and invalidates old snapshots.
    return (
        creator.platform_account_id
        or creator.youtube_channel_id
        or f"library:{creator.id}"
    )
