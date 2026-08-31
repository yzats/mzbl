import argparse
import sys
from pathlib import Path

# Cloud Functions gen2 resolves --entry-point names from this module.
from src.webhooks.receiver import shopify_webhook_receiver  # noqa: F401
from src.queue.worker import bg_remover_worker  # noqa: F401
from src.queue.circuit_probe import rembg_circuit_probe  # noqa: F401
from src.control.api import bg_remover_control  # noqa: F401

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import config
    REMBG_API_URL = getattr(config, "REMBG_API_URL", "https://www.rembg.com/api/remove")
    REMBG_API_KEY = getattr(config, "REMBG_API_KEY", "")
    DEFAULT_TIMEOUT = getattr(config, "REMBG_TIMEOUT", 30)
except ImportError:
    REMBG_API_URL = "https://www.rembg.com/api/remove"
    REMBG_API_KEY = ""
    DEFAULT_TIMEOUT = 30

from src.removers import (
    BaseBackgroundRemover,
    BackgroundRemoverError,
    RembgHostedRemover,
)


def main():
    parser = argparse.ArgumentParser(
        description="CLI utility to test background removal using rembg API."
    )
    parser.add_argument(
        "--input", "-i", required=True, type=str, help="Path to input image file"
    )
    parser.add_argument(
        "--output", "-o", required=True, type=str, help="Path for output file"
    )
    parser.add_argument(
        "--api-key",
        default=REMBG_API_KEY,
        help="rembg API key (default from config.py)",
    )
    parser.add_argument(
        "--api-url",
        default=REMBG_API_URL,
        help=f"rembg API URL (default: {REMBG_API_URL})",
    )
    parser.add_argument(
        "--timeout",
        default=DEFAULT_TIMEOUT,
        type=int,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file does not exist at {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading input image: {input_path}")
    image_bytes = input_path.read_bytes()

    remover = RembgHostedRemover(
        api_key=args.api_key,
        api_url=args.api_url,
        timeout=args.timeout,
    )

    try:
        print(f"Sending image ({len(image_bytes)} bytes) to rembg API at {args.api_url} (transparent PNG)...")
        processed_bytes = remover.remove_background(image_bytes)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(processed_bytes)

        print(f"Success! Saved background-removed image ({len(processed_bytes)} bytes) to {output_path}")

    except BackgroundRemoverError as e:
        print(f"Error during background removal: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
