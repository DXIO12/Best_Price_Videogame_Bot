"""Internationalization package. See ``translator`` for the how and why."""

from language_selector.translator import (
    DEFAULT_LANGUAGE,
    available_languages,
    get_language,
    init_language,
    set_language,
    tr,
)

__all__ = [
    "DEFAULT_LANGUAGE",
    "available_languages",
    "get_language",
    "init_language",
    "set_language",
    "tr",
]
