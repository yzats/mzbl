import os
import sys
import subprocess
from pathlib import Path

# Ensure root directories are in sys.path
BG_REMOVER_DIR = Path(__file__).resolve().parent
SHOPIFY_TOOLS_DIR = BG_REMOVER_DIR.parent

sys.path.insert(0, str(BG_REMOVER_DIR))
sys.path.insert(0, str(SHOPIFY_TOOLS_DIR))

try:
    import config
    webhook_secret = getattr(config, "SHOPIFY_WEBHOOK_SECRET", "") or getattr(config, "SHOPIFY_CLIENT_SECRET", "")
    if webhook_secret:
        os.environ["SHOPIFY_WEBHOOK_SECRET"] = webhook_secret
        os.environ["SHOPIFY_CLIENT_SECRET"] = webhook_secret
except ImportError:
    pass

def main():
    print("🚀 Starting local Functions Framework server on http://localhost:8080...")
    print("   Target: shopify_webhook_receiver (src/webhooks/receiver.py)\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BG_REMOVER_DIR}:{SHOPIFY_TOOLS_DIR}:" + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable,
        "-m",
        "functions_framework",
        "--target=shopify_webhook_receiver",
        "--source=src/webhooks/receiver.py",
        "--port=8080",
    ]

    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n👋 Server stopped.")

if __name__ == "__main__":
    main()
