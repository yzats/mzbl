import base64
import hmac
import hashlib
import json
from unittest.mock import MagicMock

from src.webhooks.hmac_verifier import verify_shopify_hmac
from src.webhooks.receiver import shopify_webhook_receiver


def test_verify_shopify_hmac_valid():
    secret = "my_secret_key"
    body = b'{"id": 12345, "title": "Test Product"}'
    
    valid_hmac = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    assert verify_shopify_hmac(body, valid_hmac, secret) is True


def test_verify_shopify_hmac_invalid():
    secret = "my_secret_key"
    body = b'{"id": 12345, "title": "Test Product"}'
    bad_hmac = "invalid_hmac_signature"

    assert verify_shopify_hmac(body, bad_hmac, secret) is False
    assert verify_shopify_hmac(body, "", secret) is False
    assert verify_shopify_hmac(b"", bad_hmac, secret) is False


def test_shopify_webhook_receiver_unauthorized(mocker):
    mocker.patch("src.webhooks.receiver.get_webhook_secret", return_value="secret123")

    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.headers = {
        "X-Shopify-Hmac-Sha256": "bad_signature",
        "X-Shopify-Topic": "products/update",
        "X-Shopify-Shop-Domain": "test.myshopify.com",
    }
    mock_request.get_data.return_value = b'{"id": 123}'

    response_body, status_code, headers = shopify_webhook_receiver(mock_request)
    assert status_code == 401
    assert "Unauthorized" in response_body


def test_shopify_webhook_receiver_duplicate_webhook_id(mocker):
    secret = "secret123"
    body = b'{"id": 987654321, "title": "Sample Shoe"}'
    valid_hmac = base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("utf-8")

    mocker.patch("src.webhooks.receiver.get_webhook_secret", return_value=secret)

    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.headers = {
        "X-Shopify-Webhook-Id": "unique-event-id-999",
        "X-Shopify-Hmac-Sha256": valid_hmac,
        "X-Shopify-Topic": "products/update",
        "X-Shopify-Shop-Domain": "test.myshopify.com",
    }
    mock_request.get_data.return_value = body
    mock_request.get_json.return_value = {"id": 987654321, "title": "Sample Shoe"}

    # First invocation -> 200 OK
    res1, code1, _ = shopify_webhook_receiver(mock_request)
    assert code1 == 200
    assert "success" in res1

    # Immediate second invocation with SAME Webhook ID -> 200 OK (Ignored as duplicate)
    res2, code2, _ = shopify_webhook_receiver(mock_request)
    assert code2 == 200
    assert "Duplicate webhook ID" in res2
