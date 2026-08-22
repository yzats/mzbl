"""Cloud Monitoring custom metrics (gauges / counters). Fail open if GCP is unavailable."""

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CREDITS_METRIC = "custom.googleapis.com/bg_remover/rembg_credits"
PREPAID_CREDITS_METRIC = "custom.googleapis.com/bg_remover/rembg_prepaid_credits"
IMAGES_PROCESSED_METRIC = "custom.googleapis.com/bg_remover/images_processed"


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _write_int_point(metric_type: str, value: int) -> None:
    project_id = (os.environ.get("GCP_PROJECT_ID") or "").strip()
    if not project_id:
        return
    try:
        from google.cloud import monitoring_v3

        now = time.time()
        seconds = int(now)
        nanos = int((now - seconds) * 10**9)
        series = monitoring_v3.TimeSeries()
        series.metric.type = metric_type
        series.resource.type = "global"
        series.resource.labels["project_id"] = project_id
        interval = monitoring_v3.TimeInterval(
            {"end_time": {"seconds": seconds, "nanos": nanos}}
        )
        point = monitoring_v3.Point(
            {"interval": interval, "value": {"int64_value": int(value)}}
        )
        series.points = [point]
        client = monitoring_v3.MetricServiceClient()
        client.create_time_series(name=f"projects/{project_id}", time_series=[series])
    except Exception as e:
        logger.warning("Failed to write custom metric %s: %s", metric_type, e)


def write_rembg_credit_gauges(usage: Dict[str, Any]) -> None:
    """Write rembg credits and prepaidCredits gauges from membership-usage JSON."""
    credits = _as_int(usage.get("credits"))
    prepaid = _as_int(usage.get("prepaidCredits"))
    if credits is not None:
        _write_int_point(CREDITS_METRIC, credits)
    if prepaid is not None:
        _write_int_point(PREPAID_CREDITS_METRIC, prepaid)


def increment_images_processed(count: int) -> None:
    """Write a DELTA point for images successfully processed in this worker run."""
    if count <= 0:
        return
    _write_int_point(IMAGES_PROCESSED_METRIC, count)
