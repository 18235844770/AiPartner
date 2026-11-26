"""Add account credentials and device sessions alongside local workspaces."""

from alembic import op
import sqlalchemy as sa


revision = "0019_account_sessions"
down_revision = "0018_one_active_conversation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(64)))
    op.add_column("users", sa.Column("password_hash", sa.Text()))
    op.add_column("users", sa.Column("avatar_url", sa.Text()))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_check_constraint("account_credentials_pair", "users", "(username IS NULL) = (password_hash IS NULL)")
    # 0001 used a pre-prefixed name before applying the metadata naming convention.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_ck_users_status")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_status")
    op.create_check_constraint("status", "users", "status IN ('active', 'deleting')")

    op.add_column("companions", sa.Column("initialization_status", sa.String(16)))
    op.add_column("companions", sa.Column("initialized_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "initialization_status", "companions", "initialization_status IN ('pending', 'ready', 'failed')",
    )
    op.create_index(
        "uq_companions_managed_owner", "companions", ["owner_user_id"], unique=True,
        postgresql_where=sa.text("initialization_status IS NOT NULL"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.add_column("conversations", sa.Column("is_managed", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_check_constraint("managed_is_active", "conversations", "NOT is_managed OR status = 'active'")
    op.create_index(
        "uq_conversations_managed_companion", "conversations", ["companion_id"], unique=True,
        postgresql_where=sa.text("is_managed"),
    )


def downgrade() -> None:
    op.drop_index("uq_conversations_managed_companion", table_name="conversations")
    op.drop_constraint(op.f("ck_conversations_managed_is_active"), "conversations", type_="check")
    op.drop_column("conversations", "is_managed")
    op.drop_table("auth_sessions")
    op.drop_index("uq_companions_managed_owner", table_name="companions")
    op.drop_constraint(op.f("ck_companions_initialization_status"), "companions", type_="check")
    op.drop_column("companions", "initialized_at")
    op.drop_column("companions", "initialization_status")
    op.drop_constraint(op.f("ck_users_status"), "users", type_="check")
    op.create_check_constraint("status", "users", "status = 'active'")
    op.drop_constraint(op.f("ck_users_account_credentials_pair"), "users", type_="check")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "username")
