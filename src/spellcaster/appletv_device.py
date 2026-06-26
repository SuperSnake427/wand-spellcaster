"""
Non-blocking wrapper for Apple TV control via pyatv (Companion protocol).

Runs on the shared per-device event loop thread from
:class:`async_device.AsyncDeviceThread`, so all operations are fire-and-forget
from the synchronous main loop.

Before first use, run:
    python tests/pair_appletv.py
which pairs via the Apple TV on-screen PIN and saves credentials to
appletv_credentials.json.  After that this class loads them automatically.
"""
import asyncio
import inspect
import ipaddress
import json
import os
from typing import Any

from .async_device import AsyncDeviceThread

CONNECT_TIMEOUT = 15.0   # Apple TV can be slow coming out of standby
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "appletv_credentials.json")
CACHED_STATE_FILE = os.path.expanduser("~/.pyatv.conf")


class AppleTVDevice(AsyncDeviceThread):
    """
    Controls one Apple TV via pyatv Companion protocol.

    Parameters:
        - ip: The Apple TV's IP address on the local network.
        - credentials_file: Path to the JSON file holding the paired Companion
          credentials (default CREDENTIALS_FILE in the package root).
    """

    _tag = "appletv"

    def __init__(self, ip: str,
                 credentials_file: str = CREDENTIALS_FILE) -> None:
        self.ip = ip
        self._atv: Any = None
        self._conf: Any = None
        self._creds = self._load_credentials(credentials_file)
        super().__init__(
            name=ip, connect_timeout=CONNECT_TIMEOUT,
            unavailable_hint="check IP and run tests/pair_appletv.py")

    # -- public non-blocking API --------------------------------------------

    def turn_on(self) -> None:
        """Wake / turn on the Apple TV."""
        self._submit(self._async_power(on=True))

    def turn_off(self) -> None:
        """Put the Apple TV to sleep."""
        self._submit(self._async_power(on=False))

    def menu(self) -> None:
        """Send the Menu button (useful to dismiss screen saver)."""
        self._submit(self._async_remote("menu"))

    def play_pause(self) -> None:
        """Toggle playback."""
        self._submit(self._async_remote("play_pause"))

    # -- async implementations ----------------------------------------------

    async def _connect(self) -> None:
        """
        Scan for the Apple TV, inject credentials, and connect.

        Falls back to cached AirPlay settings if Companion discovery or
        connection fails. Sets ``available`` to True on success.
        """
        try:
            import pyatv
            from pyatv.const import Protocol
        except ImportError:
            print("[appletv] pyatv not installed — "
                  "run: pip install pyatv --break-system-packages")
            return

        loop = asyncio.get_running_loop()
        try:
            devs = await pyatv.scan(loop, hosts=[self.ip], timeout=10)
            if devs:
                self._conf = devs[0]

                # Inject stored credentials
                companion_creds = self._creds.get("Companion") or self._creds.get("companion")
                if companion_creds:
                    svc = self._conf.get_service(Protocol.Companion)
                    if svc:
                        svc.credentials = companion_creds
                else:
                    print(f"[appletv] {self.ip}: no credentials — "
                          "run tests/pair_appletv.py first")

                self._atv = await pyatv.connect(self._conf, loop,
                                                protocol=Protocol.Companion)
                self.available = True
                print(f"[appletv] {self.ip}: connected ({self._conf.name}, Companion)")
                return

            if not devs:
                print(f"[appletv] {self.ip}: device not found on network")
        except Exception as exc:
            print(f"[appletv] {self.ip}: {exc}")

        await self._connect_airplay_fallback(loop)

    async def _teardown(self) -> None:
        """Close the pyatv connection on shutdown."""
        try:
            if self._atv:
                self._atv.close()
        except Exception:
            pass

    async def _connect_airplay_fallback(
            self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Try cached AirPlay settings when live discovery/Companion fails.

        Parameters:
            - loop: The running event loop to connect on.
        """
        try:
            import pyatv
            from pyatv.conf import AirPlayService, AppleTV
            from pyatv.const import Protocol
        except ImportError:
            return

        cached = self._load_airplay_cache()
        if not cached:
            return

        try:
            conf = AppleTV(ipaddress.IPv4Address(self.ip), "Apple TV")
            conf.add_service(
                AirPlayService(cached["identifier"], credentials=cached["credentials"])
            )
            self._atv = await pyatv.connect(conf, loop, protocol=Protocol.AirPlay)
            self._conf = conf
            self.available = True
            print(f"[appletv] {self.ip}: connected (AirPlay)")
        except Exception as exc:
            print(f"[appletv] {self.ip}: AirPlay fallback failed ({exc})")

    async def _async_power(self, on: bool) -> None:
        """
        Coroutine that powers the Apple TV on or off.

        Parameters:
            - on: True to wake/turn on, False to put to sleep.
        """
        try:
            if on:
                await self._maybe_await(self._atv.power.turn_on())
            else:
                await self._maybe_await(self._atv.power.turn_off())
        except Exception as exc:
            action = "on" if on else "off"
            print(f"[appletv] power {action}: {exc}")

    async def _async_remote(self, button: str) -> None:
        """
        Coroutine that presses a remote-control button.

        Parameters:
            - button: The remote_control method name to invoke (e.g. "menu").
        """
        try:
            rc = self._atv.remote_control
            await self._maybe_await(getattr(rc, button)())
        except Exception as exc:
            print(f"[appletv] remote {button}: {exc}")

    async def _maybe_await(self, value: Any) -> Any:
        """
        Await ``value`` if it is awaitable, otherwise return it as-is.

        Parameters:
            - value: A result that may or may not be a coroutine/awaitable.

        Returns:
            - The resolved value.
        """
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _load_credentials(path: str) -> dict:
        """
        Load paired credentials from a JSON file.

        Parameters:
            - path: Path to the credentials file.

        Returns:
            - The parsed credentials dict, or an empty dict if the file is
              missing or unreadable.
        """
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception as exc:
                print(f"[appletv] couldn't read credentials ({exc})")
        return {}

    @staticmethod
    def _load_airplay_cache() -> dict | None:
        """
        Read cached AirPlay identifier/credentials from ~/.pyatv.conf.

        Returns:
            - A dict with "identifier" and "credentials" for the first device
              that has AirPlay settings, or None if none is found.
        """
        if not os.path.exists(CACHED_STATE_FILE):
            return None

        try:
            with open(CACHED_STATE_FILE) as f:
                data = json.load(f)
        except Exception:
            return None

        for device in data.get("devices", []):
            airplay = device.get("protocols", {}).get("airplay")
            if not airplay:
                continue
            identifier = airplay.get("identifier")
            credentials = airplay.get("credentials")
            if identifier and credentials:
                return {"identifier": identifier, "credentials": credentials}

        return None
