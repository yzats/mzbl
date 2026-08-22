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
    is_product_queue_paused,
    pause_product_queue,
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
    try:
        import config
        return getattr(config, "REMBG_API_KEY", "") or ""
    except ImportError:
        return os.environ.get("REMBG_API_KEY", "")


def probe_rembg_and_resume() -> Dict[str, Any]:
    """GET /api/membership-usage. Resume the product queue when rembg is up and has credits."""
    usage_url = os.environ.get("REMBG_MEMBERSHIP_USAGE_URL", DEFAULT_MEMBERSHIP_USAGE_URL)
    remover = RembgHostedRemover(api_key=_rembg_key(), membership_usage_url=usage_url)
    try:
        usage = remover.check_account_ready()
    except (RembgUnavailableError, RetryableBackgroundRemoverError) as e:
        msg = f"{CIRCUIT_STILL_OPEN_LOG} rembg probe failed: {e}"
        print(msg, flush=True)
        logger.error(msg)
        pause_product_queue(str(e))
        return {"status": "open", "reason": str(e), "paused": is_product_queue_paused()}

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
