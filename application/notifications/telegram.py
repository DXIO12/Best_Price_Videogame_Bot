"""Telegram channel — the Bot API's ``sendMessage``.

Moved here from ``bot/notifier.py`` unchanged in behaviour: same credential
resolution order, same message text, same token redaction.
"""

import os

import requests

from application.config.logger import get_logger
from application.language_selector import tr
from application.notifications.channel import Alert

log = get_logger("notifications.telegram")


KEY = "telegram"

CREDENTIAL_FIELDS = ("bot_token", "chat_id")

SECRET_FIELDS = ("bot_token",)


def is_available() -> bool:
    """Telegram needs nothing from the machine beyond an internet connection,
    and whether that exists is only knowable by trying."""
    return True


def load_credentials() -> dict:
    """Resolve the bot token and chat id. First non-empty pair wins:

        Setting.telegram_* in the database  →  TELEGRAM_* in the environment

    The database comes first because that is what the Settings dialog writes,
    and it is the only channel a packaged build has — someone running a
    distributed copy has no source tree to drop a ``.env`` into. The
    environment stays as a fallback so an existing developer checkout, and any
    headless/CI setup that exports the variables, keeps working untouched.

    Returns empty strings when neither is configured; the caller reports it.
    """
    try:
        from application.database.db import SessionLocal
        from application.database.models import Setting

        db = SessionLocal()
        try:
            setting = db.query(Setting).first()
            if setting is not None:
                token = (setting.telegram_bot_token or "").strip()
                chat_id = (setting.telegram_chat_id or "").strip()
                if token and chat_id:
                    return {"bot_token": token, "chat_id": chat_id}
        finally:
            db.close()
    except Exception:
        # The table may not exist yet on a very first run. Fall through.
        pass

    return {
        "bot_token": (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
        "chat_id": (os.getenv("TELEGRAM_CHAT_ID") or "").strip(),
    }


def is_configured(credentials: dict) -> bool:
    return bool(credentials.get("bot_token")) and bool(credentials.get("chat_id"))


def render(alert: Alert) -> str:
    """The alert as Telegram receives it.

    Follows the selected language: this is the one piece of bot output a person
    reads. Console logs stay English on purpose.
    """
    return tr(
        "notify.price_alert",
        product=alert.product,
        shop=alert.shop,
        price=alert.price,
        target=alert.target,
        url=alert.url,
    )


def send(credentials: dict, alert: Alert) -> bool:
    return send_message(
        credentials.get("bot_token"),
        credentials.get("chat_id"),
        render(alert),
    )


def send_message(bot_token, chat_id, message) -> bool:
    """Post one message. Kept as a separate entry point from ``send`` because
    the Settings dialog's *Test* button sends with the credentials **typed**
    into the fields rather than the ones stored — the only way to confirm a
    masked token before accepting it."""
    if not bot_token or not chat_id:
        log.error(
            "No Telegram credentials configured — notification not sent. "
            "Set them in Settings → Application."
        )
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            log.info("Telegram notification sent successfully.")
            return True

        safe = response.text.replace(bot_token, "***")
        log.error(f"Telegram error: {safe}")
        return False

    except Exception as e:
        safe = str(e).replace(bot_token, "***")
        log.error(f"Error sending Telegram notification: {safe}")
        return False
