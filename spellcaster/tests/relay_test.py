#!/usr/bin/env python3
"""
Relay wiring / polarity test -- run on the Raspberry Pi.

    python3 tests/relay_test.py        # cycle all 4 channels
    python3 tests/relay_test.py 1      # just channel 1 (the Lumos light)

Each tested channel turns ON for ~1.5s (you'll hear the relay click and, on the
Keyestudio shield, its LED light), then OFF.

If a relay is ON when this says OFF -- or every relay clicks ON the moment the
script starts -- your board is the opposite polarity: set
RELAY_ACTIVE_HIGH = False in config.py and run again.  Pins come from RELAY_CH in
config.py; edit there if a channel doesn't match your shield's silkscreen.
"""
import os
import sys
import time

# Allow flat imports (config, ...) when run from the tests/ subfolder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from gpiozero import OutputDevice


def main() -> None:
    """Cycle the requested relay channel(s) ON then OFF for wiring checks."""
    active_high = config.RELAY_ACTIVE_HIGH
    channels = config.RELAY_CH
    which = [int(sys.argv[1])] if len(sys.argv) > 1 else sorted(channels)

    print(f"active_high={active_high}; testing channel(s) {which}")
    print("(Ctrl-C to stop; all channels are forced OFF on exit)\n")

    devices = {c: OutputDevice(channels[c], active_high=active_high,
                               initial_value=False) for c in which}
    try:
        for c in which:
            gpio = channels[c]
            print(f"  channel {c}  (GPIO{gpio})  -> ON")
            devices[c].on()
            time.sleep(5)
            devices[c].off()
            print(f"  channel {c}  (GPIO{gpio})  -> OFF")
            time.sleep(0.5)
        print("\ndone.")
    finally:
        for d in devices.values():
            d.off()
            d.close()


if __name__ == "__main__":
    main()
