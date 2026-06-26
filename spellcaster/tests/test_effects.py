"""
Interactive effect test — cycles through every spell so you can verify
sounds and hardware actions without running the full wand app.

Usage:
    python tests/test_effects.py           # step through all spells one by one
    python tests/test_effects.py lumos     # test a single spell by name
    python tests/test_effects.py --auto    # run all with a 4-second pause between each
"""
import os
import sys
import time

# Allow flat imports (config, effects, ...) when run from the tests/ subfolder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from effects import EffectController
from spellbook import SPELLS
from spellbook import get as get_spell


def print_banner(spell: dict, index: int, total: int) -> None:
    """
    Print a header describing the spell about to be tested.

    Parameters:
        - spell: The spell dict being tested.
        - index: The 1-based position in the test run.
        - total: The total number of spells in the run.
    """
    print()
    print(f"  [{index}/{total}]  {spell['name']}  ({spell['key']})")
    print(f"         effect : {spell['effect']}")
    print(f"         hint   : {spell['hint']}")


def run_spell(effects: EffectController, spell: dict) -> None:
    """
    Trigger one spell's sound and hardware effect.

    Parameters:
        - effects: The effect controller to dispatch through.
        - spell: The spell dict to trigger.
    """
    effects.trigger(spell)


def main() -> None:
    """Parse args and step (or auto-cycle) through the requested spells."""
    args = sys.argv[1:]
    auto  = "--auto"  in args
    args  = [a for a in args if a != "--auto"]

    print("Initialising hardware…")
    effects = EffectController(use_gpio=config.USE_GPIO)
    print("Ready.\n")

    # Build the list to test
    if args:
        spells = []
        for key in args:
            s = get_spell(key)
            if s:
                spells.append(s)
            else:
                print(f"Unknown spell: {key!r}  (valid: "
                      f"{', '.join(s['key'] for s in SPELLS)})")
        if not spells:
            effects.cleanup()
            return
    else:
        spells = list(SPELLS)

    total = len(spells)
    for i, spell in enumerate(spells, 1):
        print_banner(spell, i, total)
        run_spell(effects, spell)

        if auto:
            print("         (auto — waiting 4 s)")
            time.sleep(4)
        else:
            try:
                input("         Press Enter for next (Ctrl-C to quit)… ")
            except (KeyboardInterrupt, EOFError):
                print("\nStopping.")
                break

    print("\nAll done — cleaning up.")
    effects.cleanup()


if __name__ == "__main__":
    main()
