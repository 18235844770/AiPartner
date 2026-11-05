import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.identity.domain.enums import CompanionStatus, UserStatus
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.database.types import UUID


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status = 'active'", name="status"),
        CheckConstraint("char_length(display_name) > 0", name="display_name_nonempty"),
    )

    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        server_default=text("'UTC'"),
    )
    locale: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh-CN",
        server_default=text("'zh-CN'"),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=UserStatus.ACTIVE.value,
        server_default=text("'active'"),
    )


class Companion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companions"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "id", name="uq_companions_owner_user_id_id"),
        CheckConstraint("status IN ('active', 'paused', 'archived')", name="status"),
        CheckConstraint("char_length(name) > 0", name="name_nonempty"),
        CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR (status <> 'archived' AND archived_at IS NULL)",
            name="archive_consistency",
        ),
        Index(
            "uq_companion_default",
            "owner_user_id",
            unique=True,
            postgresql_where=text("is_default = true AND status = 'active'"),
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=CompanionStatus.ACTIVE.value,
        server_default=text("'active'"),
    )
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=text("false"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
