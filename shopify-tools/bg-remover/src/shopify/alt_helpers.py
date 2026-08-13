def append_alt_tag(existing_alt: str | None, tag_to_add: str) -> str:
    """Appends a tag to alt text as comma-separated values, avoiding duplicates.

    Examples:
      - append_alt_tag(None, "hide") -> "hide"
      - append_alt_tag("", "hide") -> "hide"
      - append_alt_tag("Air Jordan 4", "hide") -> "Air Jordan 4, hide"
      - append_alt_tag("Air Jordan 4, hide", "hide") -> "Air Jordan 4, hide"
    """
    if not existing_alt:
        return tag_to_add.strip()

    tags = [t.strip() for t in existing_alt.split(",") if t.strip()]
    if tag_to_add.strip() not in tags:
        tags.append(tag_to_add.strip())

    return ", ".join(tags)


def has_alt_tag(existing_alt: str | None, tag_to_check: str) -> bool:
    """Checks if a tag exists in comma-separated alt text.

    Examples:
      - has_alt_tag("Air Jordan 4, hide", "hide") -> True
      - has_alt_tag("hide", "hide") -> True
      - has_alt_tag("Air Jordan 4", "hide") -> False
    """
    if not existing_alt:
        return False

    tags = [t.strip().lower() for t in existing_alt.split(",") if t.strip()]
    return tag_to_check.strip().lower() in tags
