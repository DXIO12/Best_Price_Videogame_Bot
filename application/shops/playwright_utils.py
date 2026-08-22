import threading
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

from application.config.runtime_config import resolve_headless


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/122.0 Safari/537.36"
)


class BrowserManager:
    def __init__(self, headless=False, user_agent=None, browser_name="chromium"):
        self.headless = headless
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.browser_name = browser_name
        self.p_context = None
        self.p = None
        self.browser = None

    def start(self):
        if self.p is None:
            # Resolve headless from the current debug_mode at first launch, so
            # the DB/settings value is honoured when scraping actually begins.
            self.headless = resolve_headless()
            self.p_context = sync_playwright()
            self.p = self.p_context.__enter__()

            launch_kwargs = {"headless": self.headless}
            if self.browser_name == "chromium":
                # Use the full Chromium binary (new headless mode) instead of
                # the lightweight "headless shell" that Playwright launches by
                # default for headless=True. Some shops (e.g. El Corte Inglés)
                # only render the price in the full browser, so with debug mode
                # OFF the shell returned no price at all.
                launch_kwargs["channel"] = "chromium"

            self.browser = getattr(self.p, self.browser_name).launch(**launch_kwargs)

    def stop(self):
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self.p_context is not None:
            try:
                self.p_context.__exit__(None, None, None)
            except Exception:
                pass
            self.p_context = None
            self.p = None

    @contextmanager
    def new_page(self, url, timeout=30000, wait_until="commit"):
        self.start()
        context = self.browser.new_context(user_agent=self.user_agent)
        page = context.new_page()
        page.goto(url, timeout=timeout, wait_until=wait_until)

        try:
            yield page
        finally:
            try:
                context.close()
            except Exception:
                pass


# Playwright's sync API binds its driver to the thread that creates it: a
# BrowserManager — and every Browser/Page underneath it — may only be used from
# that same thread. Module-level singletons would therefore break as soon as two
# scraping threads shared them, so each thread gets its own pair instead.
_thread_state = threading.local()


def _managers() -> dict:
    """Return this thread's BrowserManager pair, creating it on first use.

    Headless is still resolved lazily inside BrowserManager.start(), so every
    thread honours the current debug_mode when it actually launches a browser."""
    managers = getattr(_thread_state, "managers", None)
    if managers is None:
        managers = {
            "chromium": BrowserManager(browser_name="chromium"),
            "firefox": BrowserManager(browser_name="firefox"),
        }
        _thread_state.managers = managers
    return managers


@contextmanager
def chromium_page(url, timeout=30000, wait_until="commit"):
    manager = _managers()["chromium"]
    with manager.new_page(url, timeout=timeout, wait_until=wait_until) as page:
        yield page


@contextmanager
def firefox_page(url, timeout=30000, wait_until="commit"):
    manager = _managers()["firefox"]
    with manager.new_page(url, timeout=timeout, wait_until=wait_until) as page:
        yield page


def stop_browser():
    """Close the browsers owned by the calling thread.

    Must be called from the thread that opened them — a Playwright driver cannot
    be shut down from another thread. Threads that never scraped are a no-op, so
    it is always safe to call. Each parallel scraping worker calls this before
    it exits; the main thread calls it at the end of a price check."""
    managers = getattr(_thread_state, "managers", None)
    if managers is None:
        return

    for manager in managers.values():
        manager.stop()
