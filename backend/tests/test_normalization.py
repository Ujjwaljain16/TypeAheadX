import string

import pytest
from hypothesis import given, settings, strategies as st

from app.services.normalization import (
    EmptyText, escape_like, normalize_text, suggestion_cache_key, validate_text,
)

text_st = st.text(max_size=120)


@given(text_st)
def test_normalize_is_idempotent(s):
    once = normalize_text(s)
    assert normalize_text(once) == once


@given(text_st)
def test_normalized_has_no_edge_or_double_whitespace(s):
    n = normalize_text(s)
    assert n == n.strip()
    assert "  " not in n
    assert not any(ch in n for ch in "\t\n\r\x0b\x0c")


@given(text_st)
def test_read_and_write_paths_agree(s):
    """A row written under normalize(s) must be found by a read of the same raw input."""
    if not normalize_text(s):
        return
    assert normalize_text(s) == normalize_text("  " + s + "\t ")


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_empty_is_distinguished(raw):
    with pytest.raises(EmptyText):
        validate_text(raw, 64)


def test_rejects_oversize_nul_surrogate_and_controls():
    with pytest.raises(ValueError, match="too long"):
        validate_text("x" * 65, 64)
    for bad in ["a\x00b", "a\x01b", "\x7f", "ab\ud800"]:
        with pytest.raises(ValueError):
            validate_text(bad, 64)


def test_accepts_unicode_and_punctuation():
    assert validate_text("  Café  LATTE ", 64) == "café latte"
    assert validate_text(r"100% off_sale\x", 64) == r"100% off_sale\x"
    assert validate_text("日本語　検索", 64) == "日本語 検索"      # ideographic space collapses
    # NFC: decomposed and composed forms are the same key
    assert normalize_text("é") == normalize_text("é")


def test_boundary_length_exact():
    assert validate_text("x" * 64, 64) == "x" * 64


def test_cache_key_shape_is_stable():
    # The key format is part of the contract between read path, invalidation and /cache/debug.
    assert suggestion_cache_key("iph") == "suggestion:iph"


@given(st.text(alphabet=string.ascii_letters + "%_\\ ", max_size=12))
@settings(max_examples=200)
def test_escape_like_roundtrip_python_model(p):
    """Model check: unescaping the escaped prefix yields the prefix (no metachar survives unescaped)."""
    esc = escape_like(p)
    out, i = [], 0
    while i < len(esc):
        if esc[i] == "\\":
            out.append(esc[i + 1]); i += 2
        else:
            assert esc[i] not in "%_"
            out.append(esc[i]); i += 1
    assert "".join(out) == p
