"""
Non-blocking wrapper for TP-Link Kasa smart plugs (EP10, etc.).

Uses python-kasa (asyncio-based) on the shared per-device event loop thread
from :class:`async_device.AsyncDeviceThread`, so every plug operation is
fire-and-forget from the synchronous main loop.  The device is turned OFF
during connect (blocking up to CONNECT_TIMEOUT seconds) so startup guarantees a
known-off state even before the camera opens.
"""
import asyncio
from typing import Any

from .async_device import AsyncDeviceThread

CONNECT_TIMEOUT = 6.0   # seconds to wait for initial connect + turn-off


class KasaDevice(AsyncDeviceThread):
    """
    Controls one Kasa smart plug asynchronously.

    Parameters:
        - ip: The plug's IP address on the local network.
        - name: A human-readable label used in log messages (default "plug").
    """

    _tag = "kasa"

    def __init__(self, ip: str, name: str = "plug") -> None:
        self.ip = ip
        self._plug: Any = None
        super().__init__(name=name, connect_timeout=CONNECT_TIMEOUT,
                         unavailable_hint="check IP / network")

    # -- public non-blocking API --------------------------------------------

    def turn_on(self) -> None:
        """Turn the plug on (fire-and-forget)."""
        self._submit(self._async_on())

    def turn_off(self) -> None:
        """Turn the plug off (fire-and-forget)."""
        self._submit(self._async_off())

    def toggle(self) -> None:
        """Toggle current state (reads state first, then flips it)."""
        self._submit(self._async_toggle())

    def pulse(self, seconds: float) -> None:
        """
        Turn on for a fixed duration then off -- non-blocking.

        Parameters:
            - seconds: How long to stay on before turning off.
        """
        self._submit(self._async_pulse(seconds))

    # -- async implementations ----------------------------------------------

    async def _connect(self) -> None:
        """Connect to the plug and force it OFF, setting ``available``."""
        try:
            from kasa import SmartPlug
        except ImportError:
            print("[kasa] python-kasa is not installed — "
                  "run: pip install python-kasa")
            return
        try:
            self._plug = SmartPlug(self.ip)
            await self._plug.update()
            await self._plug.turn_off()
            self.available = True
            print(f"[kasa] {self.name} @ {self.ip}: connected, turned OFF")
        except Exception as exc:
            print(f"[kasa] {self.name} @ {self.ip}: {exc}")

    async def _teardown(self) -> None:
        """Turn the plug off on shutdown if it is connected."""
        if self.available:
            await self._async_off()

    async def _async_on(self) -> None:
        """Coroutine that turns the plug on."""
        try:
            await self._plug.turn_on()
        except Exception as exc:
            print(f"[kasa] {self.name} on: {exc}")

    async def _async_off(self) -> None:
        """Coroutine that turns the plug off."""
        try:
            await self._plug.turn_off()
        except Exception as exc:
            print(f"[kasa] {self.name} off: {exc}")

    async def _async_toggle(self) -> None:
        """Coroutine that reads the current state and flips it."""
        try:
            await self._plug.update()
            if self._plug.is_on:
                await self._plug.turn_off()
            else:
                await self._plug.turn_on()
        except Exception as exc:
            print(f"[kasa] {self.name} toggle: {exc}")

    async def _async_pulse(self, seconds: float) -> None:
        """
        Coroutine that turns on, waits, then turns off.

        Parameters:
            - seconds: How long to stay on before turning off.
        """
        try:
            await self._plug.turn_on()
            await asyncio.sleep(seconds)
            await self._plug.turn_off()
        except Exception as exc:
            print(f"[kasa] {self.name} pulse: {exc}")
