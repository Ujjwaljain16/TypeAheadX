"""Single source of truth for query/prefix normalization and validation.

The read path (``/suggest``), the write path (``/search``), cache-key
construction and cache invalidation must all agree on how text is normalized,
otherwise rows written by one path are unreachable from the other.
"""
from __future__ import annotations

import unicodedata


class EmptyText(ValueError):
    """Input is empty / whitespace-only after normalization."""


def normalize_text(raw: str) -> str:
    """NFC-normalize, lower-case, trim and collapse internal whitespace."""
    return " ".join(unicodedata.normalize("NFC", raw).strip().lower().split())


def validate_text(raw: str, max_length: int, *, what: str = "q") -> str:
    """Normalize ``raw`` and reject anything that cannot be stored or matched safely.

    Raises ``ValueError`` (message is safe to return to clients) for:
    empty/whitespace-only input, over-long input, control characters
    (PostgreSQL ``text`` cannot hold NUL) and lone surrogates (not UTF-8 encodable).
    """
    text = normalize_text(raw)
    if not text:
        raise EmptyText(f"{what} is required")
    if len(text) > max_length:
        raise ValueError(f"{what} is too long")
    for ch in text:
        if unicodedata.category(ch) == "Cc":
            raise ValueError(f"{what} contains control characters")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{what} contains invalid characters") from None
    return text


def suggestion_cache_key(normalized_prefix: str) -> str:
    """Cache key for a *normalized* prefix. Used by reads, invalidation and debug tooling."""
    return f"suggestion:{normalized_prefix}"


def escape_like(prefix: str) -> str:
    """Escape LIKE metacharacters so user input is matched literally (use with ESCAPE '\\')."""
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
