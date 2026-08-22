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
import unicodedata
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
    r"""Lowercase a string and split it into comparable words.

    Accents are folded rather than stripped. `[^a-z0-9\s]` deleted them, which
    does not remove a letter — it *splits the word around it*: "ensueño" became
    the two tokens "ensue" and "o", so "Tomodachi Life: Una vida de ensueño"
    counted six query words instead of five and every ratio computed against it
    was too low. Folding also lets the two spellings shops actually use match
    each other ("ensueño" / "ensueno").
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", folded)
    return {word for word in cleaned.split() if word}


def title_match_ratio(query: str, title: str) -> float:
    """Share of the query's meaningful words that appear in the product title."""
    query_words = normalize_words(query) - IGNORED_QUERY_WORDS
    if not query_words:
        return 0.0
    return len(query_words & normalize_words(title)) / len(query_words)


def is_relevant(query: str, title: str) -> bool:
    return title_match_ratio(query, title) >= MIN_TITLE_MATCH_RATIO


# Float slack for comparing two ratios computed the same way — they are exact
# rationals in practice, but never compare floats for equality on principle.
RATIO_EPSILON = 1e-9


def best_relevance(query: str, titles) -> float:
    """The highest `title_match_ratio` any card on the page achieves."""
    return max((title_match_ratio(query, title) for title in titles), default=0.0)


def is_best_available_match(ratio: float, best_ratio: float) -> bool:
    """Whether a card matches the query's *name* as well as anything on the page.

    The relevance floor alone cannot separate a game from its own sequel, and a
    higher floor is not the answer. "Hollow Knight" scores 2/3 = 0.67 against a
    search for "Hollow Knight Silksong" — comfortably over the 0.6 floor — so
    once the platform filter removed every Silksong card, plain Hollow Knight
    was the only survivor and won. Raising the floor to reject it would also
    reject "Nintendo Tomodachi Life Switch", which is Amazon's genuine listing
    for "Tomodachi Life: Una vida de ensueño": both are strict subsets of the
    query, and nothing in either title says which one is a different product.

    The page itself does say. Silksong cards *were* there, on other platforms,
    matching the name perfectly — so a card matching it only partially is a
    different product, not a shortened name. Where no better-named card exists
    anywhere in the results, the partial match is the shop's own wording for
    the thing we asked for, and is accepted.

    So: choose the product by name first, across the whole page, and only then
    apply the platform filter — never the other way round.

    Ratios, not the `matched − extra` ranking score, because this decides
    *identity*. A legitimate "X Y Edición Especial" on the right platform loses
    the ranking score to a bare "X Y" on the wrong one, and must not be
    discarded for it.
    """
    return ratio >= best_ratio - RATIO_EPSILON


def is_used(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in USED_KEYWORDS)


def is_digital(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in DIGITAL_KEYWORDS)


# Listings that contain the product but are not the product: a two-game pack,
# or a console sold with the game in the box. They match every query word by
# construction — "Pack Hollow Knight + Silksong" and "Consola portátil Nintendo
# Switch 2 Mario Kart World 256 GB" both do — so relevance scoring cannot
# reject them and will happily rank a 82,90 € bundle above the 42,90 € game.
# Matched as whole words, so a title is not condemned for containing "pack"
# inside a longer word.
BUNDLE_KEYWORDS = ("pack", "bundle", "consola", "console", "combo")


def is_bundle(title: str) -> bool:
    return bool(BUNDLE_KEYWORDS) and any(
        _alias_present(keyword, title.lower()) for keyword in BUNDLE_KEYWORDS
    )


def ranking_score(query: str, title: str) -> int:
    """Rank two cards that both passed the filters: matched − extra words.

    Both sides drop `IGNORED_QUERY_WORDS` first. Without that, the extra-word
    penalty counts the platform the title advertises: "Hollow Knight Silksong
    Nintendo Switch 2 Edition" was charged four extra words for saying which
    console it is, and lost to "Pack Hollow Knight + Silksong", charged one.
    """
    query_words = normalize_words(query) - IGNORED_QUERY_WORDS
    title_words = normalize_words(title) - IGNORED_QUERY_WORDS
    return len(query_words & title_words) - len(title_words - query_words)


# How each internal platform name appears inside a shop's product title, for
# the shops that carry no platform facet or slug and must be filtered on the
# title alone (MediaMarkt, PCComponentes).
PLATFORM_TITLE_ALIASES = {
    "ps5":           ("ps5", "playstation 5"),
    "ps4":           ("ps4", "playstation 4"),
    "switch 2":      ("switch 2", "switch2", "nsw2", "nsw 2"),
    "ns2":           ("switch 2", "switch2", "nsw2", "nsw 2"),
    "switch":        ("switch", "nsw"),
    "ns":            ("switch", "nsw"),
    "pc":            ("pc",),
    "xbox series x": ("xbox series",),
}

# Platform names that are a prefix of a newer console's name. "Nintendo Switch
# 2" contains "switch", so a plain substring test hands every Switch 2 listing
# to a Switch search — the alias has to be rejected when the rival appears.
PLATFORM_EXCLUSIONS = {
    "switch": ("switch 2", "switch2", "nsw2", "nsw 2"),
    "ns":     ("switch 2", "switch2", "nsw2", "nsw 2"),
}


def _alias_present(alias: str, lowered: str) -> bool:
    """Whether `alias` appears in `lowered` as a whole token, not a substring.

    A plain `in` test cannot be used once short aliases like "nsw" and "pc" are
    in the table: "nsw" is inside "answer", and "nsw" is also the first three
    characters of "nsw2" — so a Switch 2 listing would answer a Switch search.
    The lookarounds reject a neighbouring letter or digit while still allowing
    punctuation, which is what a real title puts there ("Silksong - Switch 2",
    "...-switch-2-edicion-estandar", "PS5®").
    """
    return re.search(
        rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered
    ) is not None


def platform_matches_title(platform: str | None, title: str) -> bool:
    """True when the title advertises exactly the requested platform.

    Returns True when no platform was requested: an unfiltered search should
    not be narrowed to nothing.
    """
    if not platform:
        return True

    key = platform.strip().lower()
    lowered = title.lower()

    if any(_alias_present(rival, lowered) for rival in PLATFORM_EXCLUSIONS.get(key, ())):
        return False

    return any(
        _alias_present(alias, lowered)
        for alias in PLATFORM_TITLE_ALIASES.get(key, (key,))
    )


def mentions_any_platform(title: str) -> bool:
    """Whether the title names a console at all — any console, not ours.

    Amazon frequently sells a game under a title that names no platform
    ("Onimusha Way of the Sword"), because the console is a variant attribute
    rather than part of the name. Requiring the platform to appear outright
    therefore rejects the shop's real listing, and — since NOT_FOUND is
    terminal — stops the product being tracked there at all.

    So the rule is not "the title must name our platform" but "the title must
    not name a different one". This is what separates the two: a title that
    names nothing is platform-agnostic and eligible; a title that names a rival
    console is a different listing.
    """
    lowered = title.lower()
    return any(
        _alias_present(alias, lowered)
        for aliases in PLATFORM_TITLE_ALIASES.values()
        for alias in aliases
    )


def slug_as_text(href: str) -> str:
    """A URL turned into something `platform_matches_title` can read.

    Several shops put the platform in the product URL rather than in the card
    title ("/producto/hollow-knight-silksong-switch-2-edicion-estandar/103746"),
    and a URL slug is the more trustworthy of the two — it is generated, never
    copy-written. Splitting on the hyphens turns it into ordinary words, so
    "switch 2" is then a token pair the exclusion table can catch.
    """
    return re.sub(r"[^a-z0-9]+", " ", href.lower()).strip()
