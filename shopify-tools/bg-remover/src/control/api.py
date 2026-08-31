"""Autopilot BgRemover control-plane HTTP API (register / setConfig / status / entitlement / unregister)."""

import hmac
import json
import os
from typing import Any, Dict, Optional, Tuple

import functions_framework
from flask import Request

from src.queue.shop_registry import get_shop_store
from src.shopify.store_host import shopify_admin_host
from src.utils import applog

CONTROL_SECRET_HEADER = "X-Bg-Control-Secret"

_JSON = {"Content-Type": "application/json"}


def get_control_secret() -> str:
    """Prefer env / Secret Manager, then local config.py."""
    env_secret = os.environ.get("GCP_CONTROL_SECRET", "").strip()
    if env_secret:
        return env_secret
    try:
        import config as shopify_tools_config
    except ImportError:
        return ""
    return str(getattr(shopify_tools_config, "GCP_CONTROL_SECRET", "") or "").strip()


def _json(body: Dict[str, Any], status: int) -> Tuple[str, int, Dict[str, str]]:
    return json.dumps(body), status, _JSON


def _normalize_path(path: str) -> str:
    path = (path or "").split("?")[0]
    if len(path) > 1:
        path = path.rstrip("/")
    for prefix in ("/bg_remover_control", "/bg-remover-control"):
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            path = path[len(prefix):]
    return path or "/"


def _require_shop(payload: Dict[str, Any], query_shop: str = "") -> Optional[str]:
    raw = str(payload.get("shop") or query_shop or "")
    return shopify_admin_host(raw)


def _empty_status(*, connected: bool, token_ok: bool) -> Dict[str, Any]:
    return {
        "connected": connected,
        "tokenOk": token_ok,
        "lastEventAt": None,
        "processed7d": None,
        "processedTotal": None,
        "queued": None,
        "failed": None,
        "skipped": None,
        "plan": None,
        "credits": None,
        "placeholder": False,
    }


def _handle_register(payload: Dict[str, Any]) -> Tuple[str, int, Dict[str, str]]:
    shop = _require_shop(payload)
    token = str(payload.get("accessToken") or "").strip()
    if not shop or not token:
        return _json({"ok": False, "error": "shop and accessToken are required"}, 400)
    get_shop_store().upsert_shop(
        shop,
        {
            "accessToken": token,
            "scope": payload.get("scope"),
            "status": "connected",
        },
    )
    applog.info(f"[CONTROL REGISTER] shop={shop}")
    return _json({"ok": True}, 200)


def _handle_unregister(payload: Dict[str, Any]) -> Tuple[str, int, Dict[str, str]]:
    shop = _require_shop(payload)
    if not shop:
        return _json({"ok": False, "error": "shop is required"}, 400)
    get_shop_store().delete_shop(shop)
    applog.info(f"[CONTROL UNREGISTER] shop={shop}")
    return _json({"ok": True}, 200)


def _handle_set_config(payload: Dict[str, Any]) -> Tuple[str, int, Dict[str, str]]:
    shop = _require_shop(payload)
    if not shop:
        return _json({"ok": False, "error": "shop is required"}, 400)
    fill_mode = payload.get("fillMode") or "transparent"
    if fill_mode not in ("transparent", "hex"):
        return _json({"ok": False, "error": "fillMode must be transparent or hex"}, 400)
    images_scope = payload.get("imagesScope") or "all"
    if images_scope not in ("all", "featured"):
        return _json({"ok": False, "error": "imagesScope must be all or featured"}, 400)
    get_shop_store().upsert_shop(
        shop,
        {
            "autoEnabled": bool(payload.get("autoEnabled", False)),
            "fillMode": fill_mode,
            "fillHex": payload.get("fillHex"),
            "imagesScope": images_scope,
            "forceReprocessDefault": bool(payload.get("forceReprocessDefault", False)),
        },
    )
    applog.info(f"[CONTROL SET_CONFIG] shop={shop}")
    return _json({"ok": True}, 200)


def _handle_status(shop_raw: str) -> Tuple[str, int, Dict[str, str]]:
    shop = shopify_admin_host(shop_raw)
    if not shop:
        return _json({"ok": False, "error": "shop is required"}, 400)
    record = get_shop_store().get_shop(shop)
    if not record:
        return _json(_empty_status(connected=False, token_ok=False), 200)
    token_ok = bool(str(record.get("accessToken") or "").strip())
    connected = record.get("status") == "connected" or token_ok
    body = _empty_status(connected=bool(connected), token_ok=token_ok)
    plan_handle = record.get("planHandle")
    credits_included = record.get("creditsIncluded")
    if plan_handle or credits_included is not None:
        body["plan"] = {
            "name": plan_handle or "",
            "creditsIncluded": int(credits_included or 0),
        }
    return _json(body, 200)


def _handle_entitlement(payload: Dict[str, Any]) -> Tuple[str, int, Dict[str, str]]:
    shop = _require_shop(payload)
    if not shop:
        return _json({"ok": False, "error": "shop is required"}, 400)
    get_shop_store().upsert_shop(
        shop,
        {
            "planHandle": payload.get("planHandle"),
            "creditsIncluded": payload.get("creditsIncluded"),
            "periodStart": payload.get("periodStart"),
            "periodEnd": payload.get("periodEnd"),
        },
    )
    applog.info(f"[CONTROL ENTITLEMENT] shop={shop}")
    return _json({"ok": True}, 200)


@functions_framework.http
def bg_remover_control(request: Request) -> Tuple[Any, int, Dict[str, str]]:
    """HTTP control-plane for Autopilot BgRemover (not Shopify HMAC)."""
    secret = get_control_secret()
    provided = request.headers.get(CONTROL_SECRET_HEADER, "") or ""
    if not secret or not hmac.compare_digest(provided, secret):
        applog.warning("[401 UNAUTHORIZED] control-plane secret missing or invalid")
        return _json({"error": "Unauthorized"}, 401)

    path = _normalize_path(request.path)
    method = (request.method or "GET").upper()

    payload: Dict[str, Any] = {}
    if method in ("POST", "PUT", "PATCH"):
        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:
            payload = {}

    if method == "POST" and path == "/v1/shops/register":
        return _handle_register(payload)
    if method == "POST" and path == "/v1/shops/unregister":
        return _handle_unregister(payload)
    if method == "PUT" and path == "/v1/shops/config":
        return _handle_set_config(payload)
    if method == "GET" and path == "/v1/shops/status":
        return _handle_status(str(request.args.get("shop") or ""))
    if method == "POST" and path == "/v1/shops/entitlement":
        return _handle_entitlement(payload)

    return _json({"error": "Not found"}, 404)
