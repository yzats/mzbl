from src.shopify.metafields import (
    BG_SOURCE_KEY,
    BG_STATE_RESULT,
    BG_STATE_SOURCE,
    TAG_BG_SKIP,
    bg_source_metafield,
    bg_state_metafield,
    is_processed_bg_state,
    product_has_bg_skip,
)


def test_is_processed_bg_state():
    assert is_processed_bg_state("source") is True
    assert is_processed_bg_state("result") is True
    assert is_processed_bg_state("") is False
    assert is_processed_bg_state(None) is False
    assert is_processed_bg_state("  ") is False


def test_product_has_bg_skip():
    assert product_has_bg_skip(["bg_skip"]) is True
    assert product_has_bg_skip(["BG_SKIP", "summer"]) is True
    assert product_has_bg_skip(["other"]) is False
    assert product_has_bg_skip([]) is False
    assert product_has_bg_skip(None) is False
    assert TAG_BG_SKIP == "bg_skip"


def test_bg_state_metafield_omits_namespace():
    payload = bg_state_metafield("gid://shopify/MediaImage/1", BG_STATE_RESULT)
    assert "namespace" not in payload
    assert payload["key"] == "bg_state"
    assert payload["value"] == BG_STATE_RESULT
    assert payload["ownerId"] == "gid://shopify/MediaImage/1"
    assert BG_STATE_SOURCE == "source"


def test_bg_source_metafield_stores_original_gid():
    payload = bg_source_metafield(
        "gid://shopify/MediaImage/result",
        "gid://shopify/MediaImage/orig",
    )
    assert "namespace" not in payload
    assert payload["key"] == BG_SOURCE_KEY
    assert payload["value"] == "gid://shopify/MediaImage/orig"
    assert payload["ownerId"] == "gid://shopify/MediaImage/result"
    assert payload["type"] == "single_line_text_field"
