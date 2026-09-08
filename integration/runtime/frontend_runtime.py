"""Synthetic fixture bootstrap; deliberately no provider settings or task process."""

import json
import os
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, "/app")


def main():
    from app.core.security import hash_workspace_key

    private = json.loads(Path("/private/client.json").read_text())
    os.environ["WORKSPACE_ACCESS_KEY_HASH"] = hash_workspace_key(
        private["workspace_key"]
    )
    if sys.argv[1] == "serve":
        from app.run import main as serve

        serve()
        return

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.models.profiles import CreatorContact, CreatorProfile, GameProfile

    command.upgrade(Config("/app/alembic.ini"), "head")
    with Session(create_engine(os.environ["DATABASE_URL"])) as session:
        game_id = UUID("10000000-0000-4000-8000-000000000001")
        creator_id = UUID("20000000-0000-4000-8000-000000000001")
        if session.get(GameProfile, game_id) is None:
            session.add(
                GameProfile(
                    id=game_id,
                    steam_app_id="999999991",
                    canonical_url="https://store.steampowered.com/app/999999991",
                    sort_name="Fixture Star Garden",
                    favorite=True,
                    current_facts={
                        "name": "Fixture Star Garden",
                        "genres": ["Strategy"],
                        "short_description": "Synthetic local UI fixture, not a real game.",
                    },
                    analysis={"gameplay": {"core_loop": "Plant, explore, and build"}},
                    brief={"summary": "Synthetic cozy strategy game fixture."},
                )
            )
        if session.get(CreatorProfile, creator_id) is None:
            session.add(
                CreatorProfile(
                    id=creator_id,
                    youtube_channel_id="UC_SYNTHETIC_LOCAL_ONLY",
                    canonical_url="https://www.youtube.com/channel/UC_SYNTHETIC_LOCAL_ONLY",
                    sort_name="Fixture Cozy Gamer",
                    favorite=True,
                    current_facts={
                        "channel_name": "Fixture Cozy Gamer",
                        "subscriber_count": 42000,
                    },
                    analysis={"content": {"primary_genres": ["cozy", "strategy"]}},
                    brief={
                        "summary": "Synthetic creator fixture; no real account or email."
                    },
                    contacts=[
                        CreatorContact(
                            email="fixture@example.invalid",
                            purpose="Business",
                            source_type="manual",
                            is_manual=True,
                        )
                    ],
                )
            )
        session.commit()
    print(
        "Synthetic Game and Creator fixtures ready; provider and SMTP configuration empty."
    )


if __name__ == "__main__":
    main()
