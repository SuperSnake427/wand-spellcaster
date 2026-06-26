"""
Shared base for hardware wrappers driven from the synchronous main loop.

Both the Kasa plug and Apple TV controllers talk to a network device over an
asyncio library.  Each owns one event loop running on a daemon thread, so the
main loop can fire actions off without blocking, while a blocking connect during
``__init__`` guarantees a known device state before the app proceeds.

Subclasses implement :meth:`_connect` (and set ``self.available``) plus an
optional :meth:`_teardown`, and call ``super().__init__(...)``.  They then use
:meth:`_submit` to fire-and-forget a coroutine on the device's loop.
"""
import asyncio
import threading
from collections.abc import Coroutine
from typing import Any


class AsyncDeviceThread:
    """Owns a private asyncio event loop on a daemon thread.

    Parameters:
        - name: Label used for the thread name and log messages.
        - connect_timeout: Seconds to wait for the initial connect
          (default 6.0).
        - unavailable_hint: Extra text shown when a submit is dropped because
          the device never connected (default "").
    """

    #: Log prefix, e.g. "kasa" -> "[kasa] ...". Override in subclasses.
    _tag = "device"

    def __init__(self, name: str, connect_timeout: float = 6.0,
                 unavailable_hint: str = "") -> None:
        self.name = name
        self.available = False
        self._unavailable_hint = unavailable_hint
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True,
            name=f"{self._tag}-{name}")
        self._thread.start()

        # Block until connected (or timed out) so the device is in a known
        # state before the rest of the app starts.
        try:
            asyncio.run_coroutine_threadsafe(
                self._connect(), self._loop).result(timeout=connect_timeout)
        except Exception as exc:
            print(f"[{self._tag}] {self.name}: init failed ({exc})")

    # -- hooks for subclasses ----------------------------------------------
    async def _connect(self) -> None:
        """Connect to the device and set ``self.available`` on success."""
        raise NotImplementedError

    async def _teardown(self) -> None:
        """Best-effort cleanup run (blocking) before the loop stops."""

    # -- shared lifecycle ---------------------------------------------------
    def _submit(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule a coroutine on the device loop if it is available.

        Parameters:
            - coro: The coroutine to run. It is closed and skipped with a
              warning when the device never connected.
        """
        if not self.available:
            hint = f" ({self._unavailable_hint})" if self._unavailable_hint else ""
            print(f"[{self._tag}] {self.name}: not available{hint}")
            coro.close()
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def close(self) -> None:
        """Run the subclass teardown, then stop the event loop."""
        try:
            asyncio.run_coroutine_threadsafe(
                self._teardown(), self._loop).result(timeout=3.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
