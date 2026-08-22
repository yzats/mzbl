"""HTTP probe: rembg membership-usage, then resume Cloud Tasks if credits remain."""

import json
import logging
import os
import sys
from typing import Any, Dict, Tuple

import functions_framework
from flask import Request

from src.queue.queue_control import (
    CIRCUIT_STILL_OPEN_LOG,
    emit_circuit_log,
    is_product_queue_paused,
    resume_product_queue,
)
from src.removers import (
    RembgHostedRemover,
    RembgUnavailableError,
    RetryableBackgroundRemoverError,
)
from src.removers.rembg_http import DEFAULT_MEMBERSHIP_USAGE_URL

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


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


def probe_rembg_and_resume() -> Dict[str, Any]:
    """GET /api/membership-usage. Resume the product queue when rembg is up and has credits."""
    usage_url = os.environ.get("REMBG_MEMBERSHIP_USAGE_URL", DEFAULT_MEMBERSHIP_USAGE_URL)
    remover = RembgHostedRemover(api_key=_rembg_key(), membership_usage_url=usage_url)
    try:
        usage = remover.check_account_ready()
    except (RembgUnavailableError, RetryableBackgroundRemoverError) as e:
        paused = is_product_queue_paused()
        if paused:
            emit_circuit_log(f"{CIRCUIT_STILL_OPEN_LOG} rembg probe failed: {e}")
        else:
            logger.warning("Rembg probe failed while queue is not paused: %s", e)
        return {"status": "open", "reason": str(e), "paused": paused}

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
