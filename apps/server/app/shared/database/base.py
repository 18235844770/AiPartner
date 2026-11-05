from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.shared.database.naming import NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
