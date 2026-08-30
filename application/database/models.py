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

from application.database.db import Base

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
    ),

    # Search priority for this specific product+platform combination.
    # Lower value = searched first. Independent per platform so the same
    # product can be prioritised differently across its platforms.
    Column(
        "priority",
        Integer,
        nullable=False,
        default=0
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

    # Debug mode: True → visible browsers + attached console/logs.
    # False → headless scraping in the background. None → resolved from
    # the frozen-executable default in runtime_config.get_debug_mode().
    debug_mode = Column(Boolean)

    # Scrape several shops at once instead of one after another.
    # None → treated as False (sequential, the original behaviour).
    allow_parallel_scraping = Column(Boolean)

    # Worker threads used when allow_parallel_scraping is on. Each one launches
    # its own browser, so this caps both concurrency and memory use.
    max_parallel_workers = Column(Integer)

    # UI language as a catalog code ("en", "es", ...) matching a file in
    # language_selector/languages/. None → resolved from the system locale, then English,
    # in language_selector.translator.resolve_language().
    language = Column(String)

    # Telegram credentials. Stored here rather than only in .env so a packaged
    # build is configurable from its own Settings dialog — the people running a
    # distributed copy have no source tree to drop a .env into, and on Windows
    # a file named ".env" is genuinely awkward to create.
    #
    # Deliberately NOT mirrored to config.json like every other setting: that
    # file is tracked in git, and a bot token in it would be committed.
    telegram_bot_token = Column(String)
    telegram_chat_id = Column(String)

    # SMTP settings for the email channel. Same rule as the Telegram pair
    # above: stored here so a packaged build is configurable from its own
    # dialog, and never mirrored to config.json — smtp_password is an account
    # password, and that file is tracked in git.
    #
    # smtp_port is TEXT rather than INTEGER on purpose. Settings writes every
    # channel's fields on every Save, ticked or not, so an int() here would have
    # to cope with whatever is sitting in an untouched field; the raw string is
    # kept and parsed at use, where a bad one can be reported.
    #
    # There is no recipient column: the alert goes to smtp_user. That account
    # is already the only address the message can claim as its sender, so a
    # separate destination would be asking for the same address twice.
    smtp_host = Column(String)
    smtp_port = Column(String)
    smtp_user = Column(String)
    smtp_password = Column(String)

    # Which notification channels are switched on, as a CSV of channel keys
    # ("telegram,desktop"). A CSV rather than a table: it is at most a handful
    # of values from a closed set, on a table that only ever holds one row.
    #
    # Three states, and they are NOT the same thing:
    #   None  = never configured → application.notifications falls back to
    #           Telegram if credentials are already stored (the migration rule)
    #   ""    = explicitly no channels: the user turned them all off
    #   "..." = exactly these
    #
    # Unlike the credentials above, this one IS mirrored to config.json: a list
    # of channel names is not a secret.
    notification_channels = Column(String)


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