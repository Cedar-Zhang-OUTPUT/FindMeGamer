"""Accept canonical X Analyze results and safe X failures during maintenance."""

from importlib import import_module

from alembic import op
import sqlalchemy as sa

revision = "20260908_0019"
down_revision = "20260908_0018"
branch_labels = None
depends_on = None

# Refer only to frozen historical migration code, never the current application.
_old = import_module("migrations.versions.20260902_0004_analysis_job_public_state")
_creator = import_module("migrations.versions.20260908_0009_creator_library")
_X_ERRORS = """OR (
    error_code IN ('x_account_id_invalid', 'x_account_not_found', 'x_request_rejected',
                   'x_response_invalid', 'x_source_identity_mismatch')
    AND error_message = 'Analysis could not be completed for this target.' AND NOT retryable
) OR (
    error_code = 'x_unavailable'
    AND error_message = 'Analysis is temporarily unavailable. Please retry.' AND retryable
)"""


def _errors(include_x):
    op.drop_constraint("ck_analysis_jobs_error_mapping", "analysis_jobs", type_="check")
    op.create_check_constraint(
        "ck_analysis_jobs_error_mapping",
        "analysis_jobs",
        f"status <> 'failed' OR ({_old._ERROR_MAPPING_CHECK} {_X_ERRORS if include_x else ''})",
    )


def upgrade():
    _errors(True)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION analysis_job_succeeded_profile_is_valid(
            checked_target_type text, checked_profile_id uuid,
            checked_target_id text, checked_canonical_url text
        ) RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT CASE checked_target_type
                WHEN 'game' THEN
                    CASE WHEN checked_target_id ~ '^[1-9][0-9]{0,9}$'
                        THEN checked_target_id::bigint <= 2147483647 ELSE false END
                    AND checked_canonical_url = 'https://store.steampowered.com/app/' || checked_target_id
                    AND EXISTS (SELECT 1 FROM game_profiles AS profile
                        WHERE profile.id = checked_profile_id AND profile.steam_app_id = checked_target_id
                          AND profile.canonical_url = checked_canonical_url)
                WHEN 'creator' THEN (
                    checked_target_id ~ '^UC[A-Za-z0-9_-]{6,126}$'
                    AND checked_canonical_url = 'https://www.youtube.com/channel/' || checked_target_id
                    AND EXISTS (SELECT 1 FROM creator_profiles AS profile
                        WHERE profile.id = checked_profile_id
                          AND ((profile.youtube_channel_id = checked_target_id AND profile.canonical_url = checked_canonical_url)
                              OR EXISTS (SELECT 1 FROM creator_identity_bindings AS binding
                                WHERE binding.creator_id = profile.id AND binding.revision < profile.identity_revision
                                  AND binding.platform = 'youtube' AND binding.account_id = checked_target_id
                                  AND binding.canonical_url = checked_canonical_url)))
                ) OR (
                    checked_target_id ~ '^x:[1-9][0-9]{0,31}$'
                    AND checked_canonical_url = 'https://x.com/i/user/' || substring(checked_target_id from 3)
                    AND EXISTS (SELECT 1 FROM creator_profiles AS profile
                        WHERE profile.id = checked_profile_id
                          AND ((profile.platform = 'x' AND profile.platform_account_id = substring(checked_target_id from 3)
                                AND profile.canonical_url = checked_canonical_url)
                              OR EXISTS (SELECT 1 FROM creator_identity_bindings AS binding
                                WHERE binding.creator_id = profile.id AND binding.revision < profile.identity_revision
                                  AND binding.platform = 'x' AND binding.account_id = substring(checked_target_id from 3)
                                  AND binding.canonical_url = checked_canonical_url)))
                ) ELSE false
            END
        $$
    """
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            """SELECT EXISTS(SELECT 1 FROM analysis_jobs
        WHERE canonical_target_id LIKE 'x:%' OR error_code LIKE 'x_%')"""
        )
    ):
        raise RuntimeError(
            "Back up X Analyze jobs before downgrading; no records were removed."
        )
    _creator._replace_succeeded_identity_validator(allow_history=True)
    _errors(False)
