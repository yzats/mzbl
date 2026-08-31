"""HTTP probe: rembg membership-usage, then a /rmbg canary before resume."""

import json
import os
from io import BytesIO
from typing import Any, Dict, Tuple

import functions_framework
from flask import Request
from PIL import Image

from src.utils import applog

from src.queue.queue_control import (
    CIRCUIT_STILL_OPEN_LOG,
    canary_is_due,
    emit_circuit_log,
    is_product_queue_paused,
    record_canary_failure,
    reset_canary_backoff,
    resume_product_queue,
)
from src.queue.custom_metrics import write_circuit_open_gauge, write_rembg_credit_gauges
from src.removers import (
    BackgroundRemoverError,
    RembgHostedRemover,
    membership_has_credits,
)
from src.removers.rembg_http import DEFAULT_MEMBERSHIP_USAGE_URL

CANARY_EDGE_PX = 32


def _rembg_key() -> str:
    """Prefer Secret Manager / env (production), then local config.py."""
    env_key = (os.environ.get("REMBG_API_KEY") or "").strip()
    if env_key:
        return env_key
    try:
        import config
        return str(getattr(config, "REMBG_API_KEY", "") or "").strip()
    except ImportError:
        return ""


def _canary_png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (CANARY_EDGE_PX, CANARY_EDGE_PX), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _open_result(
    reason: str,
    paused: Any,
    usage: Dict[str, Any],
) -> Dict[str, Any]:
    write_circuit_open_gauge(bool(paused))
    if paused:
        emit_circuit_log(f"{CIRCUIT_STILL_OPEN_LOG} rembg probe failed: {reason}")
    else:
        applog.warning(f"Rembg probe failed while queue is not paused: {reason}")
    return {
        "status": "open",
        "reason": reason,
        "paused": paused,
        "credits": usage.get("credits"),
        "prepaidCredits": usage.get("prepaidCredits"),
    }


def probe_rembg_and_resume() -> Dict[str, Any]:
    """GET membership-usage; if paused and credits remain, canary /rmbg before resume."""
    usage_url = os.environ.get("REMBG_MEMBERSHIP_USAGE_URL", DEFAULT_MEMBERSHIP_USAGE_URL)
    remover = RembgHostedRemover(api_key=_rembg_key(), membership_usage_url=usage_url)
    try:
        usage = remover.get_membership_usage()
    except BackgroundRemoverError as e:
        paused = is_product_queue_paused()
        write_circuit_open_gauge(bool(paused))
        if paused:
            emit_circuit_log(f"{CIRCUIT_STILL_OPEN_LOG} rembg probe failed: {e}")
        else:
            applog.warning(f"Rembg probe failed while queue is not paused: {e}")
        return {"status": "open", "reason": str(e), "paused": paused}

    write_rembg_credit_gauges(usage)
    if not membership_has_credits(usage):
        reset_canary_backoff()
        reason = (
            "Rembg account has no usable credits "
            f"(credits={usage.get('credits')}, prepaidCredits={usage.get('prepaidCredits')})"
        )
        paused = is_product_queue_paused()
        return _open_result(reason, paused, usage)

    paused = is_product_queue_paused()
    if paused is True:
        if not canary_is_due():
            return _open_result("Rembg /rmbg canary hold", paused, usage)
        try:
            canary = RembgHostedRemover(
                api_key=_rembg_key(),
                membership_usage_url=usage_url,
                max_retries=0,
            )
            canary.remove_background(_canary_png_bytes())
        except BackgroundRemoverError as e:
            hold = record_canary_failure()
            return _open_result(
                f"Rembg /rmbg canary failed (next in {hold}s): {e}",
                paused,
                usage,
            )

    reset_canary_backoff()
    resumed = resume_product_queue()
    return {
        "status": "closed",
        "resumed": resumed,
        "paused": False,
        "credits": usage.get("credits"),
        "prepaidCredits": usage.get("prepaidCredits"),
    }


@functions_framework.http
def rembg_circuit_probe(request: Request) -> Tuple[str, int, Dict[str, str]]:
    if request.method not in ("POST", "GET"):
        return json.dumps({"error": "Method not allowed"}), 405, {"Content-Type": "application/json"}

    result = probe_rembg_and_resume()
    code = 200 if result.get("status") == "closed" else 503
    return json.dumps(result), code, {"Content-Type": "application/json"}
