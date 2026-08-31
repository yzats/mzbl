import pytest
from unittest.mock import MagicMock
import requests

from src.shopify.client import (
    ShopifyGraphQLClient,
    ShopifyAPIError,
    RetryableShopifyError,
    NonRetryableShopifyError,
)


def test_get_unprocessed_images_success(mocker):
    mock_data = {
        "data": {
            "product": {
                "id": "gid://shopify/Product/12345",
                "title": "Test Sneakers",
                "media": {
                    "nodes": [
                        {
                            "id": "gid://shopify/MediaImage/67890",
                            "mediaContentType": "IMAGE",
                            "status": "READY",
                            "image": {
                                "id": "gid://shopify/Image/11111",
                                "url": "https://cdn.shopify.com/s/files/1/test.jpg",
                                "altText": "Test Image",
                                "width": 1000,
                            },
                        }
                    ]
                },
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data

    mocker.patch("requests.post", return_value=mock_resp)

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com",
        access_token="shpat_test123456",
    )

    images = client.get_unprocessed_images("12345")
    assert len(images) == 1
    image_info = images[0]

    assert image_info["media_id"] == "gid://shopify/MediaImage/67890"
    assert image_info["url"] == "https://cdn.shopify.com/s/files/1/test.jpg"
    assert image_info["product_title"] == "Test Sneakers"
    assert image_info["alt_text"] == "Test Image"
    assert image_info["bg_state"] == ""


def _product_media_payload(nodes, tags=None):
    return {
        "data": {
            "product": {
                "id": "gid://shopify/Product/12345",
                "title": "Test Sneakers",
                "tags": tags or [],
                "media": {"nodes": nodes},
            }
        }
    }


def test_get_unprocessed_images_skips_bg_state_source_and_result(mocker):
    mock_data = _product_media_payload(
        [
            {
                "id": "gid://shopify/MediaImage/1",
                "mediaContentType": "IMAGE",
                "alt": "Air Jordan 4",
                "bgState": {"value": "source"},
                "image": {
                    "id": "gid://shopify/Image/1",
                    "url": "https://cdn.shopify.com/s/files/1/orig.jpg",
                    "altText": "Air Jordan 4",
                    "width": 1000,
                },
            },
            {
                "id": "gid://shopify/MediaImage/2",
                "mediaContentType": "IMAGE",
                "alt": "Air Jordan 4",
                "bgState": {"value": "result"},
                "image": {
                    "id": "gid://shopify/Image/2",
                    "url": "https://cdn.shopify.com/s/files/1/out.webp",
                    "altText": "Air Jordan 4",
                    "width": 1000,
                },
            },
            {
                "id": "gid://shopify/MediaImage/3",
                "mediaContentType": "IMAGE",
                "alt": "Side view",
                "bgState": None,
                "image": {
                    "id": "gid://shopify/Image/3",
                    "url": "https://cdn.shopify.com/s/files/1/side.jpg",
                    "altText": "Side view",
                    "width": 800,
                },
            },
        ]
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mocker.patch("requests.post", return_value=mock_resp)

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )
    images = client.get_unprocessed_images("12345")
    assert len(images) == 1
    assert images[0]["media_id"] == "gid://shopify/MediaImage/3"
    assert images[0]["alt_text"] == "Side view"


def test_get_unprocessed_images_skips_product_with_bg_skip(mocker):
    mock_data = _product_media_payload(
        [
            {
                "id": "gid://shopify/MediaImage/1",
                "mediaContentType": "IMAGE",
                "alt": "Air Jordan 4",
                "image": {
                    "id": "gid://shopify/Image/1",
                    "url": "https://cdn.shopify.com/s/files/1/orig.jpg",
                    "altText": "Air Jordan 4",
                    "width": 1000,
                },
            }
        ],
        tags=["bg_skip", "summer"],
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mocker.patch("requests.post", return_value=mock_resp)

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )
    assert client.get_unprocessed_images("12345") == []


def test_get_unprocessed_images_featured_scope(mocker):
    mock_data = _product_media_payload(
        [
            {
                "id": "gid://shopify/MediaImage/1",
                "mediaContentType": "IMAGE",
                "alt": "First",
                "image": {
                    "id": "gid://shopify/Image/1",
                    "url": "https://cdn.shopify.com/s/files/1/a.jpg",
                    "altText": "First",
                    "width": 100,
                },
            },
            {
                "id": "gid://shopify/MediaImage/2",
                "mediaContentType": "IMAGE",
                "alt": "Second",
                "image": {
                    "id": "gid://shopify/Image/2",
                    "url": "https://cdn.shopify.com/s/files/1/b.jpg",
                    "altText": "Second",
                    "width": 100,
                },
            },
        ]
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mocker.patch("requests.post", return_value=mock_resp)

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )
    images = client.get_unprocessed_images("12345", images_scope="featured")
    assert len(images) == 1
    assert images[0]["media_id"] == "gid://shopify/MediaImage/1"


def test_get_unprocessed_images_not_found(mocker):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"product": None}}

    mocker.patch("requests.post", return_value=mock_resp)

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )

    with pytest.raises(NonRetryableShopifyError, match="Product not found"):
        client.get_unprocessed_images("invalid_id")


def test_download_image_bytes_success(mocker):
    fake_bytes = b"fake_jpeg_binary_data"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = fake_bytes

    mocker.patch("requests.get", return_value=mock_resp)

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )

    result = client.download_image_bytes("https://cdn.shopify.com/s/files/1/test.jpg")
    assert result == fake_bytes
    requests.get.assert_called_once_with(
        "https://cdn.shopify.com/s/files/1/test.jpg", timeout=30
    )


def test_download_image_bytes_retryable_error(mocker):
    mocker.patch("time.sleep")
    mock_500 = MagicMock(status_code=500, text="Internal Error")
    mock_200 = MagicMock(status_code=200, content=b"success_data")

    mocker.patch("requests.get", side_effect=[mock_500, mock_200])

    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )

    result = client.download_image_bytes("https://cdn.shopify.com/s/files/1/test.jpg")
    assert result == b"success_data"
    assert requests.get.call_count == 2


def test_staged_upload_and_create_media(mocker):
    client = ShopifyGraphQLClient(
        store_url="test-store.myshopify.com", access_token="shpat_test"
    )

    # Mock stagedUploadsCreate response data
    mock_staged_data = {
        "stagedUploadsCreate": {
            "stagedTargets": [
                {
                    "url": "https://upload.shopify.com/upload",
                    "resourceUrl": "https://cdn.shopify.com/staged/123.png",
                    "parameters": [{"name": "key", "value": "tmp/123.png"}],
                }
            ],
            "userErrors": [],
        }
    }

    # Mock productCreateMedia response data
    mock_media_data = {
        "productCreateMedia": {
            "media": [{"id": "gid://shopify/MediaImage/999", "status": "READY"}],
            "mediaUserErrors": [],
        }
    }

    mocker.patch.object(client, "_execute_query", side_effect=[mock_staged_data, mock_media_data])

    target = client.create_staged_upload("test.png")
    assert target["url"] == "https://upload.shopify.com/upload"

    media = client.create_product_media("gid://shopify/Product/123", target["resourceUrl"])
    assert media["id"] == "gid://shopify/MediaImage/999"
