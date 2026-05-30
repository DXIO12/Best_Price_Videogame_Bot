from sqlalchemy import Table
from sqlalchemy.orm import relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime
)

from database.db import Base

product_platforms = Table(
    "product_platforms",
    Base.metadata,

    Column(
        "product_id",
        Integer,
        ForeignKey("products.id")
    ),

    Column(
        "platform_id",
        Integer,
        ForeignKey("platforms.id")
    )
)

class Platform(Base):

    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)

    name = Column(
        String,
        nullable=False,
        unique=True
    )

class Setting(Base):

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)

    check_interval_minutes = Column(Integer)

    notify_only_best_price = Column(Boolean)

    repeat_notifications = Column(Boolean)

    repeat_notification_hours = Column(Integer)


class Product(Base):

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)

    name = Column(String, nullable=False)

    platforms = relationship(
    "Platform",
    secondary=product_platforms,
    backref="products"
    )

    target_price = Column(Float, nullable=False)


class ProductShop(Base):

    __tablename__ = "product_shops"

    id = Column(Integer, primary_key=True)

    product_id = Column(
        Integer,
        ForeignKey("products.id")
    )

    shop = Column(String, nullable=False)

    url = Column(String, nullable=False)

    last_price = Column(Float)

    last_notified = Column(DateTime)

    retry_count = Column(Integer, default=0, nullable=False)

    next_retry_at = Column(DateTime, nullable=True)