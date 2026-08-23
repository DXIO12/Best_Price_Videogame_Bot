"""The contract every notification channel implements.

A channel is one module in this package, the same way a shop is one module in
``shops/``. Nothing outside the registry imports a channel directly; the bot
asks ``send_to_enabled()`` and never learns which channels exist.

Each channel module exposes:

    KEY                 str          stable id — settings, config.json, i18n keys
    CREDENTIAL_FIELDS   tuple[str]   what the Settings dialog draws for it
    SECRET_FIELDS       tuple[str]   subset of the above shown masked
    is_available()      -> bool      can this machine use the channel at all
    load_credentials()  -> dict      whatever ``send`` needs, from the DB / env
    is_configured(c)    -> bool      are those credentials complete
    send(c, alert)      -> bool      True only if it actually went out

``send`` returning a bool is load-bearing: the caller writes it into
``ProductShop.last_notified``, and a failed send that reports success starts the
repeat-notification cooldown, swallowing the alert for the whole window.

The alert is passed **structured, not pre-rendered**. Telegram wants one flat
message, a desktop toast wants a short title plus a body, an email wants a
``Subject`` — composing the string before the split would force every channel to
take it apart again.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    """One price hit, in the form every channel renders from."""

    product: str
    shop: str
    price: float
    target: float
    url: str
