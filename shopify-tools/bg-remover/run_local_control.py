import os
import sys
import subprocess
from pathlib import Path

BG_REMOVER_DIR = Path(__file__).resolve().parent
SHOPIFY_TOOLS_DIR = BG_REMOVER_DIR.parent

sys.path.insert(0, str(BG_REMOVER_DIR))
sys.path.insert(0, str(SHOPIFY_TOOLS_DIR))

try:
    import config
    control_secret = getattr(config, "GCP_CONTROL_SECRET", "")
    if control_secret:
        os.environ["GCP_CONTROL_SECRET"] = control_secret
except ImportError:
    pass


def main():
    print("Starting local control-plane server on http://localhost:8081...")
    print("   Target: bg_remover_control (src/control/api.py)")
    print("   Auth header: X-Bg-Control-Secret\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BG_REMOVER_DIR}:{SHOPIFY_TOOLS_DIR}:" + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable,
        "-m",
        "functions_framework",
        "--target=bg_remover_control",
        "--source=src/control/api.py",
        "--port=8081",
    ]

    try:
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
