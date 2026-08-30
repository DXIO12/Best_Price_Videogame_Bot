"""Desktop channel — the notification the operating system itself draws.

Local and ephemeral, the opposite trade-off to Telegram: it only reaches you if
you are at the machine, and it costs nothing to set up. Both at once is the
normal case, which is why the Settings tab uses checkboxes.

**It has to work in two processes.** Started from the GUI, the pass runs on a
``QThreadPool`` worker; started from ``launcher/start_bot.*`` there is no Qt at
all. A ``QSystemTrayIcon`` exists only in the first, so this channel talks to
the OS instead — one code path, the same behaviour either way, and no Qt object
touched from a worker thread.

**No link in the message, deliberately.** Cinnamon's notification daemon reports
``actions`` but not ``body-hyperlinks``, so a URL in the body is unclickable
text that swallows the popup; and a real action button implies ``--wait``, which
means keeping a child process alive per alert. On Windows a toast button needs a
registered AppUserModelID *and* a COM activator. The URL stays where it is
already clickable: Telegram and the product table.
"""

import os
import shutil
import subprocess
import sys

from application.config.logger import get_logger
from application.config.runtime_config import base_dir
from application.language_selector import tr
from application.notifications.channel import Alert, SCOPE_BEST

log = get_logger("notifications.desktop")


KEY = "desktop"

# Only the cheapest shop. A popup per shop means five or six of them queued at
# four seconds each, in front of whatever you were doing — and the second
# cheapest is not what you were going to buy anyway.
DELIVERY_SCOPE = SCOPE_BEST

# Nothing to configure: the OS is either able to show a notification or it is
# not. The Settings tab draws this channel as a bare checkbox.
CREDENTIAL_FIELDS = ()

SECRET_FIELDS = ()

# How long the subprocess may take before we give up on it. Generous: these are
# local calls that normally return in milliseconds, and a hung one must not
# stall a scraping pass.
_TIMEOUT = 15

# PowerShell's own AppUserModelID. A toast must be shown by a registered
# application, and Price Bot is not one — so the alert reads as coming from
# "Windows PowerShell" until install_launcher.ps1 registers an AUMID of its own.
_POWERSHELL_AUMID = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
)


def is_available() -> bool:
    """Whether this machine can show a desktop notification at all.

    Checked rather than assumed: over SSH, or on a server, there is no
    notification daemon and the send would fail every cycle. The Settings tab
    shows an unavailable channel as such instead of offering it.
    """
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False
        return shutil.which("notify-send") is not None

    if sys.platform == "win32":
        return _powershell() is not None

    # macOS would need osascript and has never been tested here.
    return False


def load_credentials() -> dict:
    return {}


def load_stored(setting) -> dict:
    return {}


def store(setting, values: dict) -> None:
    return None


def is_configured(credentials: dict) -> bool:
    """Always true. There is nothing to fill in, so an enabled desktop channel
    can never be the "switched on but not configured" case the Settings dialog
    refuses to save."""
    return True


def render(alert: Alert) -> tuple[str, str]:
    """The alert as (title, body).

    Two parts rather than one blob: a toast draws the title in bold on its own
    line, and a body that repeats it wastes the four seconds it is on screen.
    """
    return (
        tr("notify.desktop_title"),
        tr(
            "notify.desktop_body",
            product=alert.product,
            shop=alert.shop,
            price=alert.price_text,
            target=alert.target_text,
        ),
    )


def send(credentials: dict, alert: Alert) -> bool:
    title, body = render(alert)
    return _show(title, body)


def send_test(credentials: dict) -> bool:
    return _show(tr("notify.desktop_title"), tr("settings.desktop_test_message"))


# ---------------------------------------------------------------------------
# Platform back ends
# ---------------------------------------------------------------------------

def _icon_path() -> str | None:
    icon = base_dir() / "assets" / "price-bot.png"
    return str(icon) if icon.is_file() else None


def _show(title: str, body: str) -> bool:
    if sys.platform.startswith("linux"):
        return _show_linux(title, body)
    if sys.platform == "win32":
        return _show_windows(title, body)
    log.warning(f"No desktop notification back end for platform '{sys.platform}'.")
    return False


def _show_linux(title: str, body: str) -> bool:
    """libnotify, through the `notify-send` binary.

    No `--expire-time`: the desktop decides how long its own notifications
    stay up (Cinnamon reads `notification-duration` from its own settings and
    ignores the hint), and pretending otherwise would only be a lie in the code.
    Urgency stays `normal` so the popup fades and lands in the notification
    tray, rather than `critical`, which never expires — a price drop is not a
    dead battery.
    """
    command = ["notify-send", "--app-name=Price Bot", "--urgency=normal"]
    icon = _icon_path()
    if icon:
        command += ["--icon", icon]
    # `--` so a product name starting with a dash is not read as an option.
    command += ["--", title, body]

    return _run(command)


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$title = [System.Security.SecurityElement]::Escape($env:PRICE_BOT_TOAST_TITLE)
$body  = [System.Security.SecurityElement]::Escape($env:PRICE_BOT_TOAST_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:PRICE_BOT_TOAST_AUMID).Show($toast)
"""


def _show_windows(title: str, body: str) -> bool:
    """A native Win10/11 toast, via the WinRT API PowerShell can reach.

    Nothing to install — no BurntToast, no `win11toast`; the API ships with
    Windows. The text travels in the environment rather than inside the script,
    so no product name can ever be interpreted as PowerShell syntax, and the XML
    is escaped on the other side.
    """
    shell = _powershell()
    if shell is None:
        log.warning("PowerShell not found — cannot show a desktop notification.")
        return False

    environment = dict(os.environ)
    environment["PRICE_BOT_TOAST_TITLE"] = title
    environment["PRICE_BOT_TOAST_BODY"] = body
    environment["PRICE_BOT_TOAST_AUMID"] = _POWERSHELL_AUMID

    command = [
        shell,
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle", "Hidden",
        "-Command", _TOAST_SCRIPT,
    ]
    # CREATE_NO_WINDOW: without it a console flashes on every single alert.
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return _run(command, env=environment, creationflags=creation_flags)


def _run(command: list[str], **kwargs) -> bool:
    try:
        result = subprocess.run(
            command,
            timeout=_TIMEOUT,
            capture_output=True,
            text=True,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        log.error(f"Desktop notification timed out after {_TIMEOUT}s.")
        return False
    except Exception as error:  # noqa: BLE001 - a missing binary must not kill the pass
        log.error(f"Desktop notification failed: {error}")
        return False

    if result.returncode == 0:
        log.info("Desktop notification shown.")
        return True

    detail = (result.stderr or result.stdout or "").strip().splitlines()
    log.error(f"Desktop notification failed (exit {result.returncode}): "
              f"{detail[0] if detail else 'no output'}")
    return False
