import base64
import hmac
import hashlib


def verify_shopify_hmac(body_bytes: bytes, hmac_header: str, secret: str) -> bool:
    """Verify incoming Shopify webhook HMAC-SHA256 signature.

    Args:
        body_bytes: Raw HTTP request body bytes.
        hmac_header: X-Shopify-Hmac-Sha256 header value from Shopify.
        secret: Shopify API secret key (or webhook secret key).

    Returns:
        bool: True if signature matches, False otherwise.
    """
    if not hmac_header or not secret or not body_bytes:
        return False

    secret_bytes = secret.strip().encode("utf-8")
    computed_hmac = base64.b64encode(
        hmac.new(
            secret_bytes,
            body_bytes,
            hashlib.sha256
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(computed_hmac.strip(), hmac_header.strip())
