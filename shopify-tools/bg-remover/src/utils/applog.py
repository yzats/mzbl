"""One Cloud Logging line per event with explicit severity (no print+logger doubles)."""

import json
import sys


def emit(severity: str, message: str) -> None:
    """Write a single JSON log line. Cloud Run maps `severity`; metrics match `message`."""
    sys.stdout.write(
        json.dumps({"severity": severity, "message": message}, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()


def debug(message: str) -> None:
    emit("DEBUG", message)


def info(message: str) -> None:
    emit("INFO", message)


def warning(message: str) -> None:
    emit("WARNING", message)


def error(message: str) -> None:
    emit("ERROR", message)
