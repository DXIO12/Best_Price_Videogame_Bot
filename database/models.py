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

    repeat_notification_minutes = Column(Integer)


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

    # Availability from the most recent price check:
    #   None  = never checked (or no URL yet)
    #   True  = last check found a price
    #   False = last check ran but the shop had no price (product unavailable)
    available = Column(Boolean, nullable=True)

    last_notified = Column(DateTime)

    retry_count = Column(Integer, default=0, nullable=False)

    next_retry_at = Column(DateTime, nullable=True)