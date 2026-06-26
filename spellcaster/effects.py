"""
Effect dispatcher — maps spell keys to hardware actions.

Hardware:
  Kasa plug 1  (KASA_PLUG_1_IP)  -- room light
  Kasa plug 2  (KASA_PLUG_2_IP)  -- blender
  Apple TV     (APPLETV_IP)      -- fireplace video

State tracking:
  _state holds the last *intentional* stable state (set by permanent spells).
  Transient effects (flash/pulse loops) use track=False so they don't clobber it.
  trigger() saves _state to _prev_state before every spell except Reparo,
  so Reparo can always restore the state from just before the last spell.

Sound:
  Each spell plays assets/<key>.wav via aplay.  Missing files fall back to a
  terminal bell.
"""
import os
import random
import subprocess
import threading
import time
from typing import Any

import config

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


class EffectController:
    """Plays spell sounds and drives the light/blender/Apple TV hardware.

    Parameters:
        - use_gpio: If True, initialise the gpiozero relay outputs (Raspberry
          Pi only). The Kasa plugs and Apple TV are always set up from config
          regardless (default False).
    """

    def __init__(self, use_gpio: bool = False) -> None:
        self._state      = {"kasa1": False, "kasa2": False, "appletv": False}
        self._prev_state = dict(self._state)
        self._devices: dict[str, Any] = {}
        self._kasa: dict[int, Any]    = {}
        self._appletv: Any            = None

        # -- GPIO relays (optional) ----------------------------------------
        if use_gpio:
            try:
                from gpiozero import OutputDevice
                ah = config.RELAY_ACTIVE_HIGH

                def relay(pin: int) -> "OutputDevice":
                    return OutputDevice(pin, active_high=ah, initial_value=False)

                self._devices["light"]       = relay(config.PIN_LIGHT)
                self._devices["fan"]         = relay(config.PIN_FAN)
                self._devices["act_extend"]  = relay(config.PIN_ACTUATOR_EXTEND)
                self._devices["act_retract"] = relay(config.PIN_ACTUATOR_RETRACT)
                print(f"[effects] relay GPIO ready (active_high={ah})")
            except Exception as exc:
                print(f"[effects] GPIO unavailable ({exc})")

        # -- Kasa smart plugs ----------------------------------------------
        from kasa_device import KasaDevice
        for num, ip_key, label in [
            (1, "KASA_PLUG_1_IP", "kasa1"),
            (2, "KASA_PLUG_2_IP", "kasa2"),
        ]:
            ip = getattr(config, ip_key, "").strip()
            if ip:
                self._kasa[num] = KasaDevice(ip, label)

        # -- Apple TV -------------------------------------------------------
        ip = getattr(config, "APPLETV_IP", "").strip()
        if ip:
            from appletv_device import AppleTVDevice
            self._appletv = AppleTVDevice(ip)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def trigger(self, spell: dict) -> None:
        """Play the spell's sound and run its hardware effect.

        Parameters:
            - spell: A spell dict with "name", "key", and "effect" entries.
              The effect name selects the matching ``_fx_<effect>`` handler.
        """
        effect = spell["effect"]
        print(f"  *  {spell['name']}  ->  {effect}")
        self._play_sound(spell["key"])
        if effect != "reparo":
            self._save_state()
        handler = getattr(self, f"_fx_{effect}", None)
        if handler:
            handler()
        else:
            print(f"[effects] no handler for '{effect}'")

    def cleanup(self) -> None:
        """Turn everything off and release all device connections."""
        for dev in self._devices.values():
            try:
                dev.off()
                dev.close()
            except Exception:
                pass
        for dev in self._kasa.values():
            try:
                dev.close()
            except Exception:
                pass
        if self._appletv is not None:
            try:
                self._appletv.close()
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Spell effects
    # -----------------------------------------------------------------------

    def _fx_lumos(self) -> None:
        """Light ON."""
        self._kasa_set(1, True)

    def _fx_descendo(self) -> None:
        """Light OFF."""
        self._kasa_set(1, False)

    def _fx_incendio(self) -> None:
        """Fireplace ON (wake Apple TV; resumes last content)."""
        self._appletv_do("on")

    def _fx_aguamenti(self) -> None:
        """Fireplace OFF (Apple TV to sleep)."""
        self._appletv_do("off")

    def _fx_stupefy(self) -> None:
        """Light flashes (1 s on / 2 s off) for 10 s + blender 2 s burst."""
        threading.Thread(target=self._run_stupefy, daemon=True).start()

    def _fx_confundus(self) -> None:
        """Light random pulsing for 15 s (min 2 s on per burst)."""
        threading.Thread(target=self._run_confundus, daemon=True).start()

    def _fx_alohomora(self) -> None:
        """Sound only — the WAV does the work."""

    def _fx_expelliarmus(self) -> None:
        """ALL OFF (both plugs and the Apple TV)."""
        self._kasa_set(1, False)
        self._kasa_set(2, False)
        self._appletv_do("off")

    def _fx_reparo(self) -> None:
        """Restore state from before the last permanent spell."""
        s = self._prev_state
        self._kasa_set(1, s.get("kasa1", False))
        self._kasa_set(2, s.get("kasa2", False))
        self._appletv_do("on" if s.get("appletv", False) else "off")

    def _fx_ascendio(self) -> None:
        """Light ON + fireplace ON."""
        self._kasa_set(1, True)
        self._appletv_do("on")

    def _fx_herbivicus(self) -> None:
        """Blender for 5 s."""
        threading.Thread(target=self._run_kasa2_pulse, args=(5.0,),
                         daemon=True).start()

    def _fx_serpensortia(self) -> None:
        """Light on/off every 0.5 s for 10 s."""
        threading.Thread(target=self._run_serpensortia, daemon=True).start()

    # -----------------------------------------------------------------------
    # Threaded timed-effect runners (track=False so _state is not clobbered)
    # -----------------------------------------------------------------------

    def _run_stupefy(self) -> None:
        """Flash the light for 10 s with a concurrent 2 s blender burst."""
        if 2 in self._kasa:
            threading.Thread(target=self._run_kasa2_pulse, args=(2.0,),
                             daemon=True).start()
        end = time.time() + 10.0
        while time.time() < end:
            self._kasa_set(1, True,  track=False)
            time.sleep(min(1.0, end - time.time()))
            self._kasa_set(1, False, track=False)
            time.sleep(min(2.0, max(0.0, end - time.time())))
        self._kasa_set(1, False, track=False)

    def _run_confundus(self) -> None:
        """Randomly pulse the light on/off for 15 s."""
        end = time.time() + 15.0
        while True:
            remaining = end - time.time()
            if remaining < 0.5:
                break
            on_dur = random.uniform(2.0, min(4.0, remaining))
            self._kasa_set(1, True,  track=False)
            time.sleep(on_dur)
            remaining = end - time.time()
            if remaining < 0.1:
                break
            off_dur = random.uniform(0.5, min(1.5, remaining))
            self._kasa_set(1, False, track=False)
            time.sleep(off_dur)
        self._kasa_set(1, False, track=False)

    def _run_kasa2_pulse(self, seconds: float) -> None:
        """Turn the blender (plug 2) on for a fixed duration, then off.

        Parameters:
            - seconds: How long to run the blender.
        """
        self._kasa_set(2, True,  track=False)
        time.sleep(seconds)
        self._kasa_set(2, False, track=False)

    def _run_serpensortia(self) -> None:
        """Toggle the light every 0.5 s for 10 s."""
        end = time.time() + 10.0
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                break
            self._kasa_set(1, True,  track=False)
            time.sleep(min(0.5, remaining))
            remaining = end - time.time()
            if remaining <= 0:
                break
            self._kasa_set(1, False, track=False)
            time.sleep(min(0.5, remaining))
        self._kasa_set(1, False, track=False)

    # -----------------------------------------------------------------------
    # Low-level helpers
    # -----------------------------------------------------------------------

    def _save_state(self) -> None:
        """Snapshot the current stable state so Reparo can restore it."""
        self._prev_state = dict(self._state)

    def _kasa_set(self, num: int, on: bool, track: bool = True) -> None:
        """Switch a Kasa plug, optionally recording the new stable state.

        Parameters:
            - num: Which plug (1 = light, 2 = blender).
            - on: True to turn on, False to turn off.
            - track: If True, record the change in ``_state``; transient
              effect loops pass False so they don't clobber it (default True).
        """
        dev = self._kasa.get(num)
        if dev is None:
            return
        dev.turn_on() if on else dev.turn_off()
        if track:
            self._state[f"kasa{num}"] = on

    def _appletv_do(self, action: str) -> None:
        """Power the Apple TV on or off and record the state.

        Parameters:
            - action: "on" to wake the Apple TV, anything else to sleep it.
        """
        if self._appletv is None:
            print("[effects] appletv not configured (set APPLETV_IP in config.py)")
            return
        if action == "on":
            self._appletv.turn_on()
            self._state["appletv"] = True
        else:
            self._appletv.turn_off()
            self._state["appletv"] = False

    def _play_sound(self, key: str) -> None:
        """Play assets/<key>.wav via aplay, falling back to a terminal bell.

        Parameters:
            - key: The spell key naming the WAV file to play.
        """
        if not getattr(config, "ENABLE_SOUND", True):
            return
        wav = os.path.join(_ASSETS, f"{key}.wav")
        if os.path.exists(wav):
            subprocess.Popen(["aplay", "-q", wav], stderr=subprocess.DEVNULL)
        else:
            print(f"[effects] no sound file: assets/{key}.wav")
            print("\a", end="", flush=True)
