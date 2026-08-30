"""The contract every notification channel implements.

A channel is one module in this package, the same way a shop is one module in
``shops/``. Nothing outside the registry imports a channel directly; the bot
asks ``send_to_enabled()`` and never learns which channels exist.

Each channel module exposes:

    KEY                 str          stable id — settings, config.json, i18n keys
    DELIVERY_SCOPE      str          SCOPE_ALL (default), SCOPE_BEST or SCOPE_DIGEST
    CREDENTIAL_FIELDS   tuple[str]   what the Settings dialog draws for it
    SECRET_FIELDS       tuple[str]   subset of the above shown masked
    is_available()      -> bool      can this machine use the channel at all
    load_credentials()  -> dict      whatever ``send`` needs, from the DB / env
    load_stored(s)      -> dict      the same, from that Setting row only
    store(s, values)    -> None      write them back onto a Setting row
    is_configured(c)    -> bool      are those credentials complete
    send(c, alert)      -> bool      True only if it actually went out

``DELIVERY_SCOPE`` is how much of one product's hits the channel wants: every
shop that beat the target, only the cheapest, or all of them gathered into one
message. It belongs to the channel rather than to the caller because it follows
from the medium — a chat log keeps eight messages for you to scroll, eight
desktop popups have to be sat through, and eight emails for one price drop is
what a filter gets written for. Omit it and the channel gets everything.

A channel declaring ``SCOPE_DIGEST`` implements one extra entry point::

    send_digest(c, alerts) -> bool   one message carrying every alert

``alerts`` arrives sorted cheapest first, and the answer is **all or nothing**:
a digest that failed to send told nobody about any of its shops, so a False
leaves every one of those rows free to alert again on a later pass. Such a
channel should still expose ``send`` — a digest of one — so that any caller
holding a single alert does not have to know which scope it is talking to.

A channel with nothing to configure leaves ``CREDENTIAL_FIELDS`` empty and
``load_stored`` / ``store`` as no-ops; the Settings dialog then draws it as a
checkbox with no fields under it.

``load_stored`` exists next to ``load_credentials`` because the Settings dialog
must show only what it can also save. A value that really comes from a ``.env``
would appear editable, and the first Save would copy it into the database.

The i18n keys a channel needs follow from its KEY, so adding one does not touch
the dialog: ``settings.channel_<KEY>``, ``settings.tooltip_channel_<KEY>``,
``settings.label_<KEY>_<field>``, ``settings.placeholder_<KEY>_<field>``,
``settings.tooltip_<KEY>_<field>``, ``settings.btn_test_<KEY>`` and
``settings.<KEY>_test_{message,missing,sending,ok,failed}``.

``send`` returning a bool is load-bearing: the caller writes it into
``ProductShop.last_notified``, and a failed send that reports success starts the
repeat-notification cooldown, swallowing the alert for the whole window.

The alert is passed **structured, not pre-rendered**. Telegram wants one flat
message, a desktop toast wants a short title plus a body, an email wants a
``Subject`` — composing the string before the split would force every channel to
take it apart again.
"""

from dataclasses import dataclass

# Values for a channel's DELIVERY_SCOPE.
SCOPE_ALL = "all"
SCOPE_BEST = "best"
# Every hit, but in a single message rather than one each. Only worth having
# for a medium where the message itself is the unit of interruption.
SCOPE_DIGEST = "digest"


@dataclass(frozen=True)
class Alert:
    """One price hit, in the form every channel renders from."""

    product: str
    shop: str
    price: float
    target: float
    url: str

    @property
    def price_text(self) -> str:
        """Two decimals, for channels with one line to say it in. A raw float
        renders as "42.9€", which reads like a price that was cut off."""
        return f"{self.price:.2f}"

    @property
    def target_text(self) -> str:
        return f"{self.target:.2f}"
