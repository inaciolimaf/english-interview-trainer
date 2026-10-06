"""Block until a URL answers 2xx (used by `make dev` so the API starts after the model server)."""

import sys
import time

import httpx

url = sys.argv[1]
timeout_s = float(sys.argv[2]) if len(sys.argv) > 2 else 180
deadline = time.monotonic() + timeout_s
while time.monotonic() < deadline:
    try:
        if httpx.get(url, timeout=2).is_success:
            sys.exit(0)
    except httpx.HTTPError:
        pass
    time.sleep(1)
print(f"timed out waiting for {url}", file=sys.stderr)
sys.exit(1)
