"""Validate X publications with platform identity and allow safe X failures."""

from importlib import import_module
from alembic import op

revision = "20260914_native_0010"
down_revision = "20260914_native_0009"
branch_labels = None
depends_on = None

PERMANENT = (
    "x_configuration_invalid",
    "x_target_invalid",
    "x_account_not_found",
    "x_response_invalid",
    "x_response_too_large",
    "x_source_identity_mismatch",
    "x_payment_required",
    "x_spend_cap_reached",
    "x_request_rejected",
)
RETRYABLE = ("x_rate_limited", "x_unavailable")


def upgrade():
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
        AND EXISTS (SELECT 1 FROM game_profiles p WHERE p.id = checked_profile_id
            AND p.steam_app_id = checked_target_id AND p.canonical_url = checked_canonical_url)
    WHEN 'creator' THEN EXISTS (
        SELECT 1 FROM creator_profiles p WHERE p.id = checked_profile_id
        AND p.canonical_url = checked_canonical_url AND (
            (p.platform = 'youtube' AND checked_target_id ~ '^UC[A-Za-z0-9_-]{6,126}$'
             AND p.platform_account_id = checked_target_id AND p.youtube_channel_id = checked_target_id
             AND checked_canonical_url = 'https://www.youtube.com/channel/' || checked_target_id)
            OR (p.platform = 'x' AND checked_target_id ~ '^x:[1-9][0-9]{0,19}$'
                AND p.platform_account_id = substring(checked_target_id from 3)
                AND p.youtube_channel_id IS NULL
                AND checked_canonical_url = 'https://x.com/i/user/' || p.platform_account_id)
        )) ELSE false END
    $$
    """
    )
    old = import_module("migrations.versions.20260902_0004_analysis_job_public_state")
    permanent = ", ".join(f"'{code}'" for code in PERMANENT)
    retryable = ", ".join(f"'{code}'" for code in RETRYABLE)
    op.drop_constraint("ck_analysis_jobs_error_mapping", "analysis_jobs", type_="check")
    op.create_check_constraint(
        "ck_analysis_jobs_error_mapping",
        "analysis_jobs",
        f"""
        status <> 'failed' OR ({old._ERROR_MAPPING_CHECK})
        OR (error_code IN ({permanent}) AND error_message = 'Analysis could not be completed for this target.' AND NOT retryable)
        OR (error_code IN ({retryable}) AND error_message = 'Analysis is temporarily unavailable. Please retry.' AND retryable)
    """,
    )


def downgrade():
    op.execute(
        """
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM analysis_jobs WHERE status = 'succeeded' AND canonical_target_id LIKE 'x:%') THEN
            RAISE EXCEPTION 'X publications require native0010.';
        END IF;
    END $$
    """
    )
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
        AND EXISTS (SELECT 1 FROM game_profiles p WHERE p.id = checked_profile_id
            AND p.steam_app_id = checked_target_id AND p.canonical_url = checked_canonical_url)
    WHEN 'creator' THEN checked_target_id ~ '^UC[A-Za-z0-9_-]{6,126}$'
        AND checked_canonical_url = 'https://www.youtube.com/channel/' || checked_target_id
        AND EXISTS (SELECT 1 FROM creator_profiles p WHERE p.id = checked_profile_id
            AND p.youtube_channel_id = checked_target_id AND p.canonical_url = checked_canonical_url)
    ELSE false END $$
    """
    )
    old = import_module("migrations.versions.20260902_0004_analysis_job_public_state")
    op.drop_constraint("ck_analysis_jobs_error_mapping", "analysis_jobs", type_="check")
    op.create_check_constraint(
        "ck_analysis_jobs_error_mapping",
        "analysis_jobs",
        f"status <> 'failed' OR ({old._ERROR_MAPPING_CHECK})",
    )
