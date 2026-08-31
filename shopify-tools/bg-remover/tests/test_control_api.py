from unittest.mock import MagicMock

from src.control.api import CONTROL_SECRET_HEADER, bg_remover_control
from src.queue.memory_stores import InMemoryShopStore


def _request(method, path, *, secret="test-secret", json_body=None, shop_query=""):
    req = MagicMock()
    req.method = method
    req.path = path
    req.headers = {CONTROL_SECRET_HEADER: secret} if secret is not None else {}
    req.get_json.return_value = json_body or {}
    req.args = MagicMock()
    req.args.get.side_effect = lambda key, default="": shop_query if key == "shop" else default
    return req


def _invoke(mocker, store, req, secret="test-secret"):
    mocker.patch("src.control.api.get_shop_store", return_value=store)
    mocker.patch("src.control.api.get_control_secret", return_value=secret)
    body, status, headers = bg_remover_control(req)
    return body, status, headers


def test_control_unauthorized_missing_secret(mocker):
    store = InMemoryShopStore()
    req = _request("POST", "/v1/shops/register", secret="")
    _, status, _ = _invoke(mocker, store, req, secret="test-secret")
    assert status == 401


def test_control_unauthorized_wrong_secret(mocker):
    store = InMemoryShopStore()
    req = _request("POST", "/v1/shops/register", secret="nope")
    _, status, _ = _invoke(mocker, store, req, secret="test-secret")
    assert status == 401


def test_control_register_set_config_status_unregister(mocker):
    import json

    store = InMemoryShopStore()
    shop = "cool-shoes.myshopify.com"

    body, status, _ = _invoke(
        mocker,
        store,
        _request(
            "POST",
            "/v1/shops/register",
            json_body={"shop": shop, "accessToken": "shpat_offline", "scope": "write_products"},
        ),
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert store.get_shop(shop)["accessToken"] == "shpat_offline"

    body, status, _ = _invoke(
        mocker,
        store,
        _request(
            "PUT",
            "/v1/shops/config",
            json_body={
                "shop": shop,
                "autoEnabled": True,
                "fillMode": "hex",
                "fillHex": "#FFFFFF",
                "imagesScope": "featured",
                "forceReprocessDefault": False,
            },
        ),
    )
    assert status == 200
    record = store.get_shop(shop)
    assert record["autoEnabled"] is True
    assert record["fillMode"] == "hex"
    assert record["imagesScope"] == "featured"

    body, status, _ = _invoke(
        mocker,
        store,
        _request("GET", "/v1/shops/status", shop_query=shop),
    )
    assert status == 200
    status_json = json.loads(body)
    assert status_json["connected"] is True
    assert status_json["tokenOk"] is True
    assert status_json["placeholder"] is False
    assert status_json["credits"] is None

    body, status, _ = _invoke(
        mocker,
        store,
        _request("POST", "/v1/shops/unregister", json_body={"shop": shop}),
    )
    assert status == 200
    assert store.get_shop(shop) is None


def test_control_status_unknown_shop(mocker):
    import json

    store = InMemoryShopStore()
    body, status, _ = _invoke(
        mocker,
        store,
        _request("GET", "/v1/shops/status", shop_query="missing.myshopify.com"),
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["connected"] is False
    assert payload["tokenOk"] is False
    assert payload["placeholder"] is False


def test_control_rejects_non_myshopify_shop(mocker):
    import json

    store = InMemoryShopStore()
    body, status, _ = _invoke(
        mocker,
        store,
        _request(
            "POST",
            "/v1/shops/register",
            json_body={"shop": "evil.example.com", "accessToken": "x"},
        ),
    )
    assert status == 400
    assert json.loads(body)["ok"] is False
