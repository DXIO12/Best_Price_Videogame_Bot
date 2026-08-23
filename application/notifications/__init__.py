"""Notification channels: the registry, and the one call the bot makes.

``send_to_enabled(alert)`` is the whole public surface for sending. Adding a
channel means adding a module here and one entry in ``_CHANNELS`` — no caller
changes.

The channel list is an explicit tuple of imports rather than a scan of this
directory. ``shops/`` and the language catalogs are discovered with
``os.listdir()`` and both had to be shipped as ``--add-data`` for the frozen
build to see them; an import is analysed by PyInstaller on its own and cannot
go missing that way.
"""

from application.config.logger import get_logger
from application.notifications import telegram
from application.notifications.channel import Alert

log = get_logger("notifications")


_CHANNELS = (telegram,)

# What an installation that has never seen the Notifications tab uses. Telegram
# was the only channel before it existed, so this is also the migration rule:
# credentials already stored keep working with nothing to reconfigure.
DEFAULT_CHANNELS = ("telegram",)


def available_channels() -> list:
    """Every channel module, in display order — including ones this machine
    cannot use. The Settings dialog needs those too, to show them as
    unavailable rather than silently omitting them."""
    return list(_CHANNELS)


def get_channel(key: str):
    for channel in _CHANNELS:
        if channel.KEY == key:
            return channel
    return None


def default_keys() -> list[str]:
    """What an installation that predates the Notifications tab gets.

    Telegram, but **only if it is already configured**. Returning it
    unconditionally would tick a channel nobody set up, and the dialog would
    then refuse to save until it was either filled in or turned off — a fresh
    install being nagged about a bot token it never asked for.
    """
    return [
        channel.KEY for channel in _CHANNELS
        if channel.KEY in DEFAULT_CHANNELS
        and channel.is_available()
        and channel.is_configured(channel.load_credentials())
    ]


def enabled_keys() -> list[str]:
    """Channel keys the user has switched on, from ``Setting``.

    ``None`` and ``""`` are different answers: never configured falls back to
    :func:`default_keys`, while an empty string is the user having turned every
    channel off, and that has to be obeyed rather than helpfully undone.

    ``getattr`` rather than a plain attribute: on a database written before the
    column existed this has to resolve to the default instead of raising in the
    middle of a scraping pass.
    """
    try:
        from application.database.db import SessionLocal
        from application.database.models import Setting

        db = SessionLocal()
        try:
            setting = db.query(Setting).first()
            raw = getattr(setting, "notification_channels", None) if setting else None
        finally:
            db.close()
    except Exception:
        raw = None

    if raw is None:
        return default_keys()

    keys = [part.strip() for part in raw.split(",") if part.strip()]
    return [key for key in keys if get_channel(key) is not None]


def send_to_enabled(alert: Alert) -> bool:
    """Send one alert through every enabled channel.

    Returns True when **at least one** channel accepted it. That is what the
    caller writes into ``last_notified``: one working channel means the person
    was told, and re-alerting on the next pass because a second channel is
    misconfigured would spam the one that works.
    """
    keys = enabled_keys()
    if not keys:
        log.warning("No notification channel is enabled — alert not sent.")
        return False

    delivered = False

    for key in keys:
        channel = get_channel(key)
        if channel is None:
            continue

        if not channel.is_available():
            log.warning(f"Notification channel '{key}' is not available on this system.")
            continue

        credentials = channel.load_credentials()
        if not channel.is_configured(credentials):
            log.error(f"Notification channel '{key}' is enabled but not configured.")
            continue

        try:
            if channel.send(credentials, alert):
                delivered = True
        except Exception as error:
            # One broken channel must not take down the pass, nor stop the
            # channels after it in the list.
            log.error(f"Notification channel '{key}' raised: {error}")

    return delivered


__all__ = [
    "Alert",
    "DEFAULT_CHANNELS",
    "available_channels",
    "default_keys",
    "enabled_keys",
    "get_channel",
    "send_to_enabled",
]
