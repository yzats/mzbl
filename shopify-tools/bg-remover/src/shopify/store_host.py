"""Allowlist Shopify Admin hosts so the access token is never sent off-platform."""

import re
from typing import Optional

_MYSHOPIFY_HOST = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com$"
)


def shopify_admin_host(value: str) -> Optional[str]:
    """Return a bare ``*.myshopify.com`` host, or None if the value is not allowed."""
    host = (value or "").strip().lower()
    if host.startswith("https://"):
        host = host[len("https://") :]
    elif host.startswith("http://"):
        host = host[len("http://") :]
    host = host.split("/")[0].split(":")[0]
    if not _MYSHOPIFY_HOST.fullmatch(host):
        return None
    return host


def resolve_shop_admin_host(payload_shop: str, configured: str) -> Optional[str]:
    """Use configured ``*.myshopify.com`` when set; otherwise the payload host if allowlisted."""
    configured_host = shopify_admin_host(configured)
    if configured_host:
        return configured_host
    return shopify_admin_host(payload_shop)
