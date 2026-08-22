"""
resolution.py
=============
Shared vocabulary for what a URL resolver found — and, when it found nothing,
*why*.

Resolvers used to return `str | None`, which collapses three very different
answers into one. "The shop does not sell this product", "the shop only sells
it second-hand" and "the search page never loaded" all became `None`, so
resolve_urls_service could do nothing but put every one of them on the same
escalating retry ladder. Worse, a resolver with no way to say "nothing here"
tends to return the closest thing it saw instead: a search for Ninja Gaiden
Ragebound resolved to Minecraft on game.es and to Naruto x Boruto on
PCComponentes, and both wrong URLs were saved and scraped from then on.

The retry policy hangs off the distinction:

  * SEARCH_FAILED is *our* problem — a stale selector, a page that did not
    render, a search box that did not answer. It keeps the retry ladder.
  * NOT_FOUND and ONLY_USED are the shop's answer. The search worked, the
    results rendered, and the product is not on sale there. Retrying just
    scrapes six more times for the same answer, so those rows are terminal.

When a resolver cannot tell the two apart, it must report SEARCH_FAILED: a
needless retry costs one browser run, while a wrong terminal verdict silently
stops tracking a product the shop really does sell.
"""

import re
from dataclasses import dataclass
from enum import Enum


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"

    # Search ran, results rendered, none of them is the product.
    NOT_FOUND = "not_found"

    # Search ran and the product is there, but only as second-hand /
    # refurbished stock. Kept apart from NOT_FOUND because the answer to the
    # user is different: the product exists, just not in the condition wanted.
    ONLY_USED = "only_used"

    # The search itself broke. Nothing was learned about the product.
    SEARCH_FAILED = "search_failed"


# Statuses that represent a definitive answer from the shop, so the retry timer
# must stop re-asking. The "Update URLs" button still re-runs these rows — it
# only skips rows that already hold a URL — so the user keeps a manual retry.
TERMINAL_STATUSES = frozenset({
    ResolutionStatus.NOT_FOUND,
    ResolutionStatus.ONLY_USED,
})


@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    url: str | None = None


def resolved(url: str) -> ResolutionResult:
    return ResolutionResult(ResolutionStatus.RESOLVED, url)


def not_found() -> ResolutionResult:
    return ResolutionResult(ResolutionStatus.NOT_FOUND)


def only_used() -> ResolutionResult:
    return ResolutionResult(ResolutionStatus.ONLY_USED)


def search_failed() -> ResolutionResult:
    return ResolutionResult(ResolutionStatus.SEARCH_FAILED)


def normalize(value) -> ResolutionResult:
    """Accept either a ResolutionResult or a legacy `str | None` return.

    Resolvers are being migrated one at a time, so the service layer has to
    handle both shapes. A legacy `None` becomes SEARCH_FAILED, which is exactly
    the behaviour those resolvers have today: every failure retries.
    """
    if isinstance(value, ResolutionResult):
        return value
    if value:
        return resolved(value)
    return search_failed()


# ─────────────────────────────────────────────
# Relevance helpers
# ─────────────────────────────────────────────

# Words that carry no meaning when comparing a query with a product title:
# platform names (every resolver filters those separately, by URL slug or by an
# on-site facet) and filler that shop titles add or drop at random.
IGNORED_QUERY_WORDS = {
    "ps5", "ps4", "ps3", "ps2", "switch", "switch2", "nsw", "nsw2", "xbox", "series", "one", "x",
    "s", "pc", "2", "de", "the", "of", "y", "and", "edition", "edicion",
}

# Share of the meaningful query words that must appear in a title before the
# card is accepted. Without a floor, "the only candidate left" wins even when
# it shares a single word with the query — which is precisely how a search for
# "Ninja Gaiden Ragebound Switch" resolved to "Minecraft Nintendo Switch
# Edition": every real word missed, and only "switch" matched.
MIN_TITLE_MATCH_RATIO = 0.6

USED_KEYWORDS = ("segunda mano", "segunda-mano", "seminuevo", "usado", "reacondicionado")

DIGITAL_KEYWORDS = ("prepago", "prepagos", "digital", "descarga")


def normalize_words(text: str) -> set[str]:
    """Lowercase a string and split it into comparable words."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return {word for word in cleaned.split() if word}


def title_match_ratio(query: str, title: str) -> float:
    """Share of the query's meaningful words that appear in the product title."""
    query_words = normalize_words(query) - IGNORED_QUERY_WORDS
    if not query_words:
        return 0.0
    return len(query_words & normalize_words(title)) / len(query_words)


def is_relevant(query: str, title: str) -> bool:
    return title_match_ratio(query, title) >= MIN_TITLE_MATCH_RATIO


def is_used(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in USED_KEYWORDS)


def is_digital(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in DIGITAL_KEYWORDS)


# How each internal platform name appears inside a shop's product title, for
# the shops that carry no platform facet or slug and must be filtered on the
# title alone (MediaMarkt, PCComponentes).
PLATFORM_TITLE_ALIASES = {
    "ps5":           ("ps5", "playstation 5"),
    "ps4":           ("ps4", "playstation 4"),
    "switch 2":      ("switch 2",),
    "ns2":           ("switch 2",),
    "switch":        ("switch",),
    "ns":            ("switch",),
    "pc":            ("pc",),
    "xbox series x": ("xbox series",),
}

# Platform names that are a prefix of a newer console's name. "Nintendo Switch
# 2" contains "switch", so a plain substring test hands every Switch 2 listing
# to a Switch search — the alias has to be rejected when the rival appears.
PLATFORM_EXCLUSIONS = {
    "switch": ("switch 2",),
    "ns":     ("switch 2",),
}


def platform_matches_title(platform: str | None, title: str) -> bool:
    """True when the title advertises exactly the requested platform.

    Returns True when no platform was requested: an unfiltered search should
    not be narrowed to nothing.
    """
    if not platform:
        return True

    key = platform.strip().lower()
    lowered = title.lower()

    if any(rival in lowered for rival in PLATFORM_EXCLUSIONS.get(key, ())):
        return False

    return any(alias in lowered for alias in PLATFORM_TITLE_ALIASES.get(key, (key,)))
