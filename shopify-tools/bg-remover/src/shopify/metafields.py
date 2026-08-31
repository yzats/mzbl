"""App-owned MediaImage `$app.bg_state` / `$app.bg_source` and product tag `bg_skip`."""

BG_STATE_KEY = "bg_state"
BG_STATE_SOURCE = "source"
BG_STATE_RESULT = "result"
BG_SOURCE_KEY = "bg_source"
BG_METAFIELD_TYPE = "single_line_text_field"
TAG_BG_SKIP = "bg_skip"


def normalize_bg_state(value: str | None) -> str:
    """Return stripped bg_state, or empty if unset."""
    return (value or "").strip()


def is_processed_bg_state(value: str | None) -> bool:
    """True when Layer 4 should skip this media (`source` or `result`)."""
    state = normalize_bg_state(value)
    return state in (BG_STATE_SOURCE, BG_STATE_RESULT)


def product_has_bg_skip(tags: list | None) -> bool:
    """True if the product has the `bg_skip` tag (case-insensitive)."""
    if not tags:
        return False
    needle = TAG_BG_SKIP.lower()
    return any(str(tag).strip().lower() == needle for tag in tags)


def _app_text_metafield(owner_id: str, key: str, value: str) -> dict:
    """Build a metafieldsSet input (namespace defaults to `$app`)."""
    return {
        "ownerId": owner_id,
        "key": key,
        "type": BG_METAFIELD_TYPE,
        "value": value,
    }


def bg_state_metafield(owner_id: str, value: str) -> dict:
    """Build a metafieldsSet input for `$app.bg_state`."""
    return _app_text_metafield(owner_id, BG_STATE_KEY, value)


def bg_source_metafield(owner_id: str, source_media_id: str) -> dict:
    """Build a metafieldsSet input for `$app.bg_source` (original MediaImage GID)."""
    return _app_text_metafield(owner_id, BG_SOURCE_KEY, source_media_id)
