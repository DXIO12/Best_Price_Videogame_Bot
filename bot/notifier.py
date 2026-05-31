import requests


def send_telegram_message(bot_token, chat_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            print("[Notifier]: Telegram notification sent successfully.")
        else:
            print(f"[Notifier]: Telegram error: {response.text}")

    except Exception as e:
        print(f"[Notifier]: Error sending Telegram notification: {e}")