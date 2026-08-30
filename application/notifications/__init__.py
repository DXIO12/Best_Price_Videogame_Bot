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
from application.notifications import desktop, email, telegram
from application.notifications.channel import Alert, SCOPE_ALL, SCOPE_BEST, SCOPE_DIGEST

log = get_logger("notifications")


# Order is display order in the Settings tab: the ones that reach you anywhere
# first, then the one that only reaches this machine.
_CHANNELS = (telegram, email, desktop)

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


def _usable_channels() -> list:
    """Enabled channels this machine can actually send through, already
    reported on. Everything skipped here is a configuration problem, so it is
    logged once per pass rather than swallowed."""
    usable = []

    for key in enabled_keys():
        channel = get_channel(key)
        if channel is None:
            continue

        if not channel.is_available():
            log.warning(f"Notification channel '{key}' is not available on this system.")
            continue

        if not channel.is_configured(channel.load_credentials()):
            log.error(f"Notification channel '{key}' is enabled but not configured.")
            continue

        usable.append(channel)

    return usable


def send_alerts(alerts: list[Alert], force_best_only: bool = False) -> list[bool]:
    """Deliver one product's hits, each channel getting as much as it wants.

    ``alerts`` is every shop of a single product that beat the target and is
    due a notification. A channel declaring ``SCOPE_BEST`` receives only the
    cheapest of them, ``SCOPE_DIGEST`` receives all of them in one message, and
    the rest receive all of them one at a time. ``force_best_only`` is the
    global *Notify only best price* setting, which narrows **every** channel —
    a digest included, which then carries a single line.

    Returns one flag per alert: True when at least one channel accepted it.
    That is what the caller writes into ``last_notified`` — one working channel
    means the person was told, and re-alerting because a second channel is
    misconfigured would spam the one that works. An alert no channel wanted
    (the shops that are not the cheapest, when only a best-only channel is on)
    is False, so its row stays un-notified and is free to alert later.
    """
    if not alerts:
        return []

    channels = _usable_channels()
    if not channels:
        log.warning("No notification channel is enabled — alert not sent.")
        return [False] * len(alerts)

    best_index = min(range(len(alerts)), key=lambda index: alerts[index].price)
    delivered = [False] * len(alerts)

    for channel in channels:
        scope = getattr(channel, "DELIVERY_SCOPE", SCOPE_ALL)
        if force_best_only or scope == SCOPE_BEST:
            indices = [best_index]
        else:
            indices = range(len(alerts))

        credentials = channel.load_credentials()

        if scope == SCOPE_DIGEST:
            # One message for the lot, cheapest first — and one answer for the
            # lot with it: a digest that did not go out told nobody about any
            # of these shops, so none of them may be stamped as notified.
            batch = sorted((alerts[index] for index in indices),
                           key=lambda alert: alert.price)
            try:
                if channel.send_digest(credentials, batch):
                    for index in indices:
                        delivered[index] = True
            except Exception as error:
                log.error(f"Notification channel '{channel.KEY}' raised: {error}")
            continue

        for index in indices:
            try:
                if channel.send(credentials, alerts[index]):
                    delivered[index] = True
            except Exception as error:
                # One broken channel must not take down the pass, nor stop the
                # channels after it in the list.
                log.error(f"Notification channel '{channel.KEY}' raised: {error}")

    return delivered


def send_to_enabled(alert: Alert) -> bool:
    """One alert, every enabled channel. The single-hit case of
    :func:`send_alerts`, kept because most callers have exactly one."""
    return send_alerts([alert])[0]


__all__ = [
    "Alert",
    "DEFAULT_CHANNELS",
    "SCOPE_ALL",
    "SCOPE_BEST",
    "SCOPE_DIGEST",
    "available_channels",
    "default_keys",
    "enabled_keys",
    "get_channel",
    "send_alerts",
    "send_to_enabled",
]
