import os

import requests

from application.config.logger import get_logger

log = get_logger("notifier")


def get_telegram_credentials() -> tuple[str | None, str | None]:
    """Resolve the Telegram bot token and chat id. First non-empty pair wins:

        Setting.telegram_* in the database  →  TELEGRAM_* in the environment

    The database comes first because that is what the Settings dialog writes,
    and it is the only channel a packaged build has — someone running a
    distributed copy has no source tree to drop a ``.env`` into. The
    environment stays as a fallback so an existing developer checkout, and any
    headless/CI setup that exports the variables, keeps working untouched.

    Returns ``(None, None)`` when neither is configured; the caller reports it.
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
                    return token, chat_id
        finally:
            db.close()
    except Exception:
        # The table may not exist yet on a very first run. Fall through.
        pass

    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    return (token or None), (chat_id or None)


def send_telegram_message(bot_token, chat_id, message):
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