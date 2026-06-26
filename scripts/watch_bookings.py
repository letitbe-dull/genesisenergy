"""Standalone Power Shout bookings watcher.

Polls the live Genesis bookings endpoint on an interval and prints each result
with timestamps, flagging any change from the previous poll. Use it to observe
how/when a mid-hour or retroactive booking actually appears in the API, before
we encode those assumptions into the integration and its tests.

This reuses the integration's own GenesisEnergyApi (so we test the real login +
endpoint), loaded by file path. It runs OUTSIDE Home Assistant, so:
  - exceptions.py degrades its HomeAssistantError base when HA isn't installed.
  - the one third-party runtime dep, aiohttp, must be present. Install it with:
        python -m pip install -r requirements-dev.txt

Run (PowerShell), from the repo root:
    $env:GENESIS_EMAIL='you@example.com'; $env:GENESIS_PASSWORD='...'
    python scripts/watch_bookings.py            # 60s interval
    python scripts/watch_bookings.py 30         # 30s interval

Stop with Ctrl+C. Creds are read from env vars only — nothing is hardcoded.
"""

import asyncio
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "genesisenergy"


def _load_api():
    """Load api.py by file path, registering a synthetic parent package so its
    `from .exceptions import ...` resolves without running the HA package __init__."""
    pkg = types.ModuleType("ge")
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules["ge"] = pkg

    def load(name):
        spec = importlib.util.spec_from_file_location(f"ge.{name}", PKG_DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"ge.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    load("exceptions")
    return load("api")


def _stamp():
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()
    return f"{now_local:%H:%M:%S} local  /  {now_utc:%H:%M:%S}Z"


async def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    email = os.environ.get("GENESIS_EMAIL")
    password = os.environ.get("GENESIS_PASSWORD")
    if not email or not password:
        print("Set GENESIS_EMAIL and GENESIS_PASSWORD env vars first.")
        return

    try:
        api_mod = _load_api()
    except ModuleNotFoundError as e:
        if e.name == "aiohttp":
            print("Missing dependency 'aiohttp'. Install it with:\n"
                  "    python -m pip install -r requirements-dev.txt")
            return
        raise

    api = api_mod.GenesisEnergyApi(email, password)
    print(f"Polling bookings every {interval}s. Ctrl+C to stop.\n")
    last = None
    try:
        while True:
            try:
                await api.async_login()
                data = await api.get_powershout_bookings()
                blob = json.dumps(data, sort_keys=True)
                changed = blob != last
                marker = "  <-- CHANGED" if (changed and last is not None) else ""
                print(f"[{_stamp()}]{marker}")
                if changed:
                    print(json.dumps(data, indent=2))
                    print()
                    last = blob
            except Exception as e:  # keep the watcher alive across transient errors
                print(f"[{_stamp()}]  ERROR: {type(e).__name__}: {e}")
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
