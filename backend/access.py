"""Print a local-only observer sign-in link; never expose it in client bundles."""
import os
from backend.settings import load_keys

if __name__ == "__main__":
    keys = load_keys(os.environ.get("STANDOUT_DATA_DIR", ".local"))
    port = os.environ.get("STANDOUT_WEB_PORT", "5173")
    print(f"http://127.0.0.1:{port}/#access={keys['observer']}")
