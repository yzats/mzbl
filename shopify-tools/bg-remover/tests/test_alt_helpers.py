import pytest
from src.shopify.alt_helpers import append_alt_tag, has_alt_tag


def test_append_alt_tag():
    assert append_alt_tag(None, "hide") == "hide"
    assert append_alt_tag("", "hide") == "hide"
    assert append_alt_tag("Air Jordan 4", "hide") == "Air Jordan 4, hide"
    assert append_alt_tag("Air Jordan 4, hide", "hide") == "Air Jordan 4, hide"
    assert append_alt_tag("sneakers, blue", "hide") == "sneakers, blue, hide"


def test_has_alt_tag():
    assert has_alt_tag("Air Jordan 4, hide", "hide") is True
    assert has_alt_tag("HIDE", "hide") is True
    assert has_alt_tag("hide, bg-removed", "bg-removed") is True
    assert has_alt_tag("Air Jordan 4", "hide") is False
    assert has_alt_tag(None, "hide") is False
    assert has_alt_tag("", "hide") is False
