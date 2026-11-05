from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"


class CompanionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
