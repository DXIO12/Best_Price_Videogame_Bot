"""Email channel — one SMTP message per product, listing every shop that hit.

The third trade-off, and the reason it is worth having next to the other two:
Telegram reaches you anywhere but lives in a chat you have to open, the desktop
toast is in front of you but gone in four seconds, and an email waits in the one
inbox you already check — and is still there tomorrow.

**A digest, not one message per shop.** This is the only channel whose scope is
``SCOPE_DIGEST``: eight emails about one price drop is what an inbox filter gets
written for, while eight Telegram messages are just a list you scroll. So the
whole product arrives in a single mail, cheapest first, and the delivery answer
covers all of it at once — see ``send_digest``.

**Two of the four fields answer themselves.** An address already says who its
provider is, so ``smtp_host`` is looked up from its domain and ``smtp_port``
falls back to 587: for a Gmail, Outlook, Yahoo, iCloud, GMX, AOL or Zoho account
the only things to type are the address and the password. Both fields stay
visible and typed always wins, because someone on a company server has to be
able to say so — and a domain that is *not* in the table is reported as
unconfigured rather than guessed at, since a wrong host fails at send time,
which is worse than being asked.

The password cannot go the same way. It is not about the destination — that is
the same address — but about the app claiming to *be* you as sender, and no
provider relays mail as an account without proof it is yours.

**No new dependency.** ``smtplib``, ``ssl`` and ``email`` are standard library,
which is the whole reason this channel costs one file. Nothing was added to
``requirements.txt`` or to the packaging scripts.

Naming: this module is ``email.py`` because a channel's filename is its ``KEY``,
the way ``telegram.py`` and ``desktop.py`` are. It does not shadow the standard
library's ``email`` package — imports are absolute in Python 3, so the line
below reaches the stdlib and this module lives at ``application.notifications.email``.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

from dotenv import load_dotenv

from application.config.logger import get_logger
from application.language_selector import tr
from application.notifications.channel import Alert, SCOPE_DIGEST

log = get_logger("notifications.email")


KEY = "email"

# Every shop that beat the target, gathered into one message.
DELIVERY_SCOPE = SCOPE_DIGEST

CREDENTIAL_FIELDS = ("smtp_host", "smtp_port", "smtp_user", "smtp_password")

SECRET_FIELDS = ("smtp_password",)

# Where each credential lives on the ``Setting`` row. Same name on both sides
# here, unlike Telegram's, but spelled out for the same reason: the channel owns
# its columns and the Settings dialog never has to know one.
SETTING_COLUMNS = {
    "smtp_host": "smtp_host",
    "smtp_port": "smtp_port",
    "smtp_user": "smtp_user",
    "smtp_password": "smtp_password",
}

# Submission port. Left blank in the dialog this is what is used, because it is
# what every mail provider has offered for submission since RFC 6409.
DEFAULT_PORT = 587

# Implicit TLS from the first byte — the connection is wrapped before the SMTP
# greeting rather than upgraded mid-session. Every other port goes through
# STARTTLS instead.
SSL_PORT = 465

# The outgoing server of the common providers, keyed on the domain of the
# address. This exists so the one field nobody outside IT can answer — "SMTP
# server" — can be left empty by almost everybody: the address already says who
# the provider is, so asking again is asking the same question twice.
#
# Every entry was verified answering on port 587 (2026-08-30). A domain that is
# not here is not guessed at; the field stays required for it, because a wrong
# host fails at send time, which is far worse than asking.
_KNOWN_HOSTS = {
    "gmail.com": "smtp.gmail.com",
    "googlemail.com": "smtp.gmail.com",
    "outlook.com": "smtp-mail.outlook.com",
    "outlook.es": "smtp-mail.outlook.com",
    "hotmail.com": "smtp-mail.outlook.com",
    "hotmail.es": "smtp-mail.outlook.com",
    "live.com": "smtp-mail.outlook.com",
    "live.es": "smtp-mail.outlook.com",
    "msn.com": "smtp-mail.outlook.com",
    "yahoo.com": "smtp.mail.yahoo.com",
    "yahoo.es": "smtp.mail.yahoo.com",
    "icloud.com": "smtp.mail.me.com",
    "me.com": "smtp.mail.me.com",
    "mac.com": "smtp.mail.me.com",
    "gmx.com": "mail.gmx.com",
    "gmx.es": "mail.gmx.com",
    "gmx.net": "mail.gmx.com",
    "aol.com": "smtp.aol.com",
    "zoho.com": "smtp.zoho.com",
}

# Connect, TLS handshake, login and send, all inside this. Longer than
# Telegram's 10 s: an SMTP conversation is several round trips, and a slow relay
# must not be reported as a failure. Short enough that a black-holed host cannot
# stall a scraping pass for minutes.
_TIMEOUT = 20


def is_available() -> bool:
    """``smtplib`` ships with Python, so the only thing that could be missing is
    a route to the server — and that is knowable only by trying. Same answer,
    and the same reason, as the Telegram channel's."""
    return True


def load_credentials() -> dict:
    """Resolve the SMTP settings. The database first, the environment second.

    The database comes first because it is what the Settings dialog writes, and
    a packaged build has no source tree to drop a ``.env`` into. The environment
    stays as a fallback so a developer checkout — or a headless/CI setup that
    exports the variables — keeps working with nothing stored.

    All five come from whichever source has a **complete** set, never field by
    field: half from each would authenticate one server's credentials against
    another. Same rule as the Telegram channel, which takes its pair from the
    database only when both halves are there.
    """
    try:
        from application.database.db import SessionLocal
        from application.database.models import Setting

        db = SessionLocal()
        try:
            setting = db.query(Setting).first()
            if setting is not None:
                stored = load_stored(setting)
                if is_configured(stored):
                    return stored
        finally:
            db.close()
    except Exception:
        # The columns may not exist yet on a database from before this channel.
        pass

    # Loaded here rather than trusting the process to have done it: ``bot.py``
    # calls load_dotenv() at import and the GUI never did, which is how the same
    # installation once looked configured to the headless bot and unconfigured
    # to the Settings dialog. Idempotent, and it does not override exported
    # variables.
    load_dotenv()

    return {
        field: (os.getenv(field.upper()) or "").strip()
        for field in CREDENTIAL_FIELDS
    }


def is_configured(credentials: dict) -> bool:
    """An account, a password, a port that is either absent or real, and a
    server that is either typed or deducible from the address.

    The host and the port are both allowed to be blank, and mean different
    kinds of blank: the port always falls back to 587, while the host only
    resolves for a provider in :data:`_KNOWN_HOSTS`. An unknown domain with the
    field empty is genuinely not configured, and the Settings dialog refuses to
    save it — better than discovering it at the first price drop.
    """
    required = ("smtp_user", "smtp_password")
    if not all((credentials.get(field) or "").strip() for field in required):
        return False
    return bool(_host(credentials)) and _port(credentials) is not None


def recipient(credentials: dict) -> str:
    """Who the alert goes to: the account itself.

    There is no separate field for it. The account is already the only address
    the message can claim as its sender — a provider rejects a From it did not
    issue — so asking for the destination as well would be asking the same
    address twice for the normal case, which is telling yourself. Sending
    somewhere else would mean one more field and one more thing to get wrong.
    """
    return (credentials.get("smtp_user") or "").strip()


def load_stored(setting) -> dict:
    """The settings as stored on this ``Setting`` row — no environment fallback.

    What the dialog shows must be what the dialog can save; a value that really
    lives in a ``.env`` would look editable, and the first Save would copy it
    into the database."""
    return {
        field: (getattr(setting, column, None) or "") if setting else ""
        for field, column in SETTING_COLUMNS.items()
    }


def store(setting, values: dict) -> None:
    """Write them back onto a ``Setting`` row. Empty means NULL, so clearing a
    field falls back to the environment again rather than storing an empty
    string that would shadow it."""
    for field, column in SETTING_COLUMNS.items():
        setattr(setting, column, (values.get(field) or "").strip() or None)


def _host(credentials: dict) -> str:
    """The outgoing server: what was typed, or the provider's, from the address.

    Typed always wins — someone on a company server, or one of the providers
    not in the table, has to be able to say so, and their answer must not be
    second-guessed. Empty means "work it out", and an address whose domain is
    unknown yields "", which :func:`is_configured` reports as unconfigured
    rather than sending at a hostname nobody checked.
    """
    typed = (credentials.get("smtp_host") or "").strip()
    if typed:
        return typed

    address = (credentials.get("smtp_user") or "").strip()
    _, _, domain = address.partition("@")
    return _KNOWN_HOSTS.get(domain.strip().lower(), "")


def _port(credentials: dict) -> int | None:
    """The port to connect on: what was typed, or 587. ``None`` means what was
    typed is not a port at all, which is the one thing ``is_configured`` rejects
    beyond an empty field."""
    raw = (credentials.get("smtp_port") or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def render(alerts: list[Alert]) -> tuple[str, str]:
    """The digest as (subject, body), plain text.

    ``alerts`` arrives cheapest first. The subject carries the cheapest price
    because that is the whole message for anyone reading a notification list on
    a phone; the body is where the other shops are.

    Plain text rather than HTML: mail clients turn a bare URL into a link on
    their own, so the only thing HTML would add is a second copy of every string
    to keep in step across both catalogs.
    """
    best = alerts[0]

    subject = tr(
        "notify.email_subject",
        product=best.product,
        price=best.price_text,
        shop=best.shop,
    )

    # One shop is not a ranking, so it is not numbered: "1." in a list of one
    # is noise, and only one shop beating the target is the common case.
    if len(alerts) == 1:
        intro = tr(
            "notify.email_intro_one",
            product=best.product,
            target=best.target_text,
        )
        lines = [
            tr(
                "notify.email_line_single",
                shop=best.shop,
                price=best.price_text,
                url=best.url,
            )
        ]
    else:
        intro = tr(
            "notify.email_intro_many",
            count=len(alerts),
            product=best.product,
            target=best.target_text,
        )
        lines = [
            tr(
                "notify.email_line",
                index=index,
                shop=alert.shop,
                price=alert.price_text,
                url=alert.url,
            )
            for index, alert in enumerate(alerts, start=1)
        ]

    body = "\n\n".join([intro, "\n".join(lines), tr("notify.email_footer")])
    return subject, body


def send_digest(credentials: dict, alerts: list[Alert]) -> bool:
    """Every hit of one product, in one message.

    One answer for all of them, which is what ``SCOPE_DIGEST`` means: a mail
    that did not go out told nobody about any of these shops, so a False here
    leaves every one of their rows free to alert again on the next pass.
    """
    if not alerts:
        return False
    subject, body = render(alerts)
    return _send(credentials, subject, body)


def send(credentials: dict, alert: Alert) -> bool:
    """The single-alert contract every channel has — a digest of one. Kept so a
    caller holding one alert does not have to know this channel's scope."""
    return send_digest(credentials, [alert])


def send_test(credentials: dict) -> bool:
    """A real email, with the credentials **typed** into the Settings dialog
    rather than the stored ones. Confirming a masked password before accepting
    it is the whole point, so this must not read the database."""
    return _send(
        credentials,
        tr(f"settings.{KEY}_test_subject"),
        tr(f"settings.{KEY}_test_message"),
    )


def _send(credentials: dict, subject: str, body: str) -> bool:
    """Deliver one message. False on every failure, having logged why.

    TLS is decided by the port rather than by a checkbox: 465 is implicit TLS,
    everything else is STARTTLS. That keeps the channel to five plain text
    fields, which is all the Settings dialog can draw — and it is the convention
    every provider's setup page already states.

    There is deliberately no plaintext fallback. ``starttls()`` raises when the
    server does not offer it, and that is the wanted outcome: failing to send is
    recoverable, handing an account password to an unencrypted socket is not.
    """
    user = (credentials.get("smtp_user") or "").strip()
    password = credentials.get("smtp_password") or ""
    to = recipient(credentials)
    host = _host(credentials)
    port = _port(credentials)

    if not user or not password:
        log.error(
            "No email credentials configured — notification not sent. "
            "Set them in Settings → Notifications."
        )
        return False

    if not host:
        log.error(
            f"No SMTP server for '{user}' — that provider is not one of the "
            "known ones, so its outgoing server has to be filled in by hand "
            "in Settings → Notifications."
        )
        return False

    if port is None:
        log.error(
            f"Invalid SMTP port '{credentials.get('smtp_port')}' — "
            "notification not sent."
        )
        return False

    message = EmailMessage()
    message["Subject"] = subject
    # The authenticated account is both ends of this: providers reject a From
    # they did not issue, and the alert is for the person who owns the account.
    message["From"] = user
    message["To"] = to
    # set_content picks the charset and the transfer encoding, so accents and
    # the € sign survive without any of it being spelled out here.
    message.set_content(body)

    context = ssl.create_default_context()

    try:
        if port == SSL_PORT:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=_TIMEOUT) as server:
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=_TIMEOUT) as server:
                server.ehlo()
                server.starttls(context=context)
                # A second EHLO after the upgrade: the server's capabilities,
                # AUTH among them, are only trustworthy once the session is
                # encrypted, and some servers advertise a different set.
                server.ehlo()
                server.login(user, password)
                server.send_message(message)

    except smtplib.SMTPNotSupportedError:
        log.error(
            f"{host}:{port} does not offer STARTTLS — refusing to send the "
            "password unencrypted. Try port 465, or a provider that supports it."
        )
        return False

    except smtplib.SMTPAuthenticationError:
        # Never logged with the server's own text: some echo the attempted
        # credentials back in the response.
        log.error(
            f"{host}:{port} rejected the login for '{user}'. If this is Gmail "
            "or Outlook, the password has to be an app password, not the "
            "account one."
        )
        return False

    except Exception as error:
        log.error(f"Error sending email notification: {_redact(str(error), password)}")
        return False

    log.info(f"Email notification sent to {to}.")
    return True


def _redact(text: str, password: str) -> str:
    """Keep the password out of the log, the way the Telegram channel keeps the
    bot token out of it. Guarded on a non-empty password: replacing "" would
    splice the mask between every character of the message."""
    return text.replace(password, "***") if password else text
