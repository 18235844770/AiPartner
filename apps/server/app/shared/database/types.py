"""PostgreSQL 类型约定。业务模型直接使用这些方言类型，避免散落导入。"""

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB, UUID

TimezoneAwareDateTime = DateTime(timezone=True)

__all__ = ["JSONB", "TimezoneAwareDateTime", "UUID"]
