"""Persona 主体与版本。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_persona"
down_revision: str | None = "0001_identity_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persona_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_persona_profiles_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_persona_profiles"),
        sa.UniqueConstraint("companion_id", name="uq_persona_profiles_companion_id"),
    )
    op.create_table(
        "persona_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("mbti_type", sa.String(4), nullable=False),
        sa.Column("core_traits", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("behavior_traits", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "communication_preferences",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["persona_profile_id"],
            ["persona_profiles.id"],
            name="fk_persona_versions_persona_profile_id_persona_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_persona_versions"),
        sa.UniqueConstraint("persona_profile_id", "id", name="uq_persona_versions_profile_id"),
        sa.UniqueConstraint("persona_profile_id", "version_number", name="uq_persona_versions_profile_version"),
        sa.CheckConstraint(
            "mbti_type IN ('INFJ', 'INFP', 'ENFP', 'ENFJ', 'INTJ', 'INTP')",
            name="ck_persona_versions_mbti_type",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_persona_versions_version_number_positive"),
        sa.CheckConstraint("char_length(change_reason) > 0", name="ck_persona_versions_change_reason_nonempty"),
    )
    op.create_foreign_key(
        "fk_persona_profiles_initial_version",
        "persona_profiles",
        "persona_versions",
        ["id", "initial_version_id"],
        ["persona_profile_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_persona_profiles_current_version",
        "persona_profiles",
        "persona_versions",
        ["id", "current_version_id"],
        ["persona_profile_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("fk_persona_profiles_current_version", "persona_profiles", type_="foreignkey")
    op.drop_constraint("fk_persona_profiles_initial_version", "persona_profiles", type_="foreignkey")
    op.drop_table("persona_versions")
    op.drop_table("persona_profiles")
