"""
The spellbook: the array of spells, their gesture shapes, and what they do.

Each spell has:
  key     -- internal id, also the recogniser label and WAV filename (assets/<key>.wav)
  name    -- display name
  hint    -- how to draw it (shown on screen)
  effect  -- key the EffectController dispatches on (maps to _fx_<effect>)
  shape   -- default example stroke, used until you record your own

Recording your own samples (press 'r' in the app) is strongly recommended —
templates drawn with the real wand + camera match motion far better than
these idealised shapes.  Recorded samples are merged in from templates.json.
"""
import json
import math
import os

from .dollar import Recognizer, Stroke

# ---------------------------------------------------------------------------
# Default shape generators
# ---------------------------------------------------------------------------

def _circle(r: float = 100, n: int = 40) -> Stroke:
    """
    A full circle of radius r drawn with n+1 points.

    Parameters:
        - r: The circle radius (default 100).
        - n: The number of segments (default 40).

    Returns:
        - The circle stroke.
    """
    return [(r * math.sin(2 * math.pi * i / n),
             -r * math.cos(2 * math.pi * i / n)) for i in range(n + 1)]


def _zee() -> Stroke:
    """A capital "Z" stroke (Incendio)."""
    return [(-100, -60), (100, -60), (-100, 60), (100, 60)]


def _caret() -> Stroke:
    """An upward caret "^" stroke (Ascendio)."""
    return [(-100, 60), (0, -70), (100, 60)]


def _checkmark() -> Stroke:
    """A checkmark stroke (Stupefy)."""
    return [(-100, 0), (-30, 60), (100, -80)]


def _triangle() -> Stroke:
    """A closed triangle stroke (Herbivicus)."""
    return [(0, -90), (90, 70), (-90, 70), (0, -90)]


def _pentagram(r: float = 100) -> Stroke:
    """
    A five-pointed star drawn in one stroke (Reparo).

    Parameters:
        - r: The circumscribed radius (default 100).

    Returns:
        - The pentagram stroke.
    """
    base = [(r * math.cos(math.pi / 2 + 2 * math.pi * i / 5),
             -r * math.sin(math.pi / 2 + 2 * math.pi * i / 5)) for i in range(5)]
    order = [0, 2, 4, 1, 3, 0]
    return [base[i] for i in order]


def _down_stroke(n: int = 21) -> Stroke:
    """
    A straight vertical swipe downward (Descendo).

    Parameters:
        - n: The number of points (default 21).

    Returns:
        - The downward stroke.
    """
    return [(0, -100 + 10 * i) for i in range(n)]


def _wave(n: int = 21) -> Stroke:
    """
    A horizontal sine wave of one full period (Aguamenti).

    Parameters:
        - n: The number of points (default 21).

    Returns:
        - The wave stroke.
    """
    return [(-100 + 10 * i, 40 * math.sin(math.pi * i / 10)) for i in range(n)]


def _w_shape() -> Stroke:
    """A chaotic multi-peak "W" with four direction changes (Confundus)."""
    return [(-100, -60), (-50, 60), (0, -60), (50, 60), (100, -60)]


def _l_shape() -> Stroke:
    """An "L" like turning a key: down then right (Alohomora)."""
    return [(-40, -80), (-40, 60), (80, 60)]


def _slash_up() -> Stroke:
    """A diagonal sweep from bottom-left to top-right (Expelliarmus)."""
    return [(-90, 80), (0, 0), (90, -80)]


def _s_curve(n: int = 21) -> Stroke:
    """
    A sinusoidal "S" from top to bottom -- a snake (Serpensortia).

    Parameters:
        - n: The number of points (default 21).

    Returns:
        - The S-curve stroke.
    """
    return [(70 * math.sin(math.pi * i / 10), -100 + 10 * i) for i in range(n)]


def _spiral(turns: float = 2.5, n: int = 48) -> Stroke:
    """
    An outward spiral from the centre (Revelio).

    Parameters:
        - turns: How many full turns the spiral makes (default 2.5).
        - n: The number of points (default 48).

    Returns:
        - The spiral stroke.
    """
    out: Stroke = []
    for i in range(n):
        frac = i / (n - 1)
        ang = turns * 2 * math.pi * frac
        r = 100 * frac
        out.append((r * math.cos(ang), -r * math.sin(ang)))
    return out


# ---------------------------------------------------------------------------
# The spellbook
# ---------------------------------------------------------------------------
# Effect names map to EffectController._fx_<name>.
# Sound files are loaded from assets/<key>.wav automatically.
#
#   lumos / descendo          ->  Kasa plug 1 (light)         KASA_PLUG_1_IP
#   incendio / aguamenti      ->  Apple TV on/off              APPLETV_IP
#   ascendio                  ->  light ON + Apple TV ON
#   expelliarmus              ->  ALL OFF
#   reparo                    ->  restore state from before last spell
#   stupefy                   ->  light flash 10s + blender 2s
#   confundus                 ->  light random pulse 15s
#   herbivicus                ->  blender 5s                   KASA_PLUG_2_IP
#   serpensortia              ->  light on/off 0.5s for 10s
#   alohomora                 ->  sound only
#   revelio                   ->  sound only

SPELLS: list[dict] = [
    {"key": "lumos",        "name": "Lumos",        "hint": "draw a circle",
     "effect": "lumos",        "shape": _circle()},
    {"key": "descendo",     "name": "Descendo",     "hint": "swipe down ↓",
     "effect": "descendo",     "shape": _down_stroke()},
    {"key": "incendio",     "name": "Incendio",     "hint": "draw a Z",
     "effect": "incendio",     "shape": _zee()},
    {"key": "aguamenti",    "name": "Aguamenti",    "hint": "draw a wave ~",
     "effect": "aguamenti",    "shape": _wave()},
    {"key": "stupefy",      "name": "Stupefy",      "hint": "draw a check ✓",
     "effect": "stupefy",      "shape": _checkmark()},
    {"key": "confundus",    "name": "Confundus",    "hint": "draw a W",
     "effect": "confundus",    "shape": _w_shape()},
    {"key": "alohomora",    "name": "Alohomora",    "hint": "draw an L",
     "effect": "alohomora",    "shape": _l_shape()},
    {"key": "expelliarmus", "name": "Expelliarmus", "hint": "slash up ↗",
     "effect": "expelliarmus", "shape": _slash_up()},
    {"key": "reparo",       "name": "Reparo",       "hint": "draw a star ✦",
     "effect": "reparo",       "shape": _pentagram()},
    {"key": "ascendio",     "name": "Ascendio",     "hint": "flick up ^",
     "effect": "ascendio",     "shape": _caret()},
    {"key": "herbivicus",   "name": "Herbivicus",   "hint": "draw a triangle",
     "effect": "herbivicus",   "shape": _triangle()},
    {"key": "serpensortia", "name": "Serpensortia", "hint": "draw an S",
     "effect": "serpensortia", "shape": _s_curve()},
    {"key": "revelio",      "name": "Revelio",      "hint": "draw a spiral",
     "effect": "revelio",      "shape": _spiral()},
]

_BY_KEY = {s["key"]: s for s in SPELLS}


def get(key: str) -> dict | None:
    """
    Look up a spell by its key.

    Parameters:
        - key: The spell key to look up.

    Returns:
        - The matching spell dict, or None if no spell has that key.
    """
    return _BY_KEY.get(key)


def load_templates(recognizer: Recognizer, templates_file: str) -> dict:
    """
    Populate the recogniser with default shapes + any recorded samples.

    Parameters:
        - recognizer: The recogniser to add templates to.
        - templates_file: Path to the JSON file of recorded samples; missing
          or unreadable files are ignored.

    Returns:
        - The recorded-samples dict that was loaded (empty if none).
    """
    for spell in SPELLS:
        recognizer.add_template(spell["key"], spell["shape"])

    recorded: dict = {}
    if os.path.exists(templates_file):
        try:
            with open(templates_file, encoding="utf-8") as fh:
                recorded = json.load(fh)
        except Exception as exc:
            print(f"[spellbook] couldn't read {templates_file}: {exc}")

    count = 0
    for key, samples in recorded.items():
        for stroke in samples:
            recognizer.add_template(key, [tuple(p) for p in stroke])
            count += 1
    if count:
        print(f"[spellbook] loaded {count} recorded sample(s) for "
              f"{len(recorded)} spell(s)")
    return recorded


def save_sample(templates_file: str, recorded: dict, key: str,
                stroke: Stroke) -> None:
    """
    Append one recorded stroke for a spell and persist to disk.

    Parameters:
        - templates_file: Path to the JSON file to write.
        - recorded: The in-memory recorded-samples dict to update.
        - key: The spell key the stroke belongs to.
        - stroke: The recorded stroke as an ordered list of points.
    """
    recorded.setdefault(key, []).append([[float(x), float(y)] for x, y in stroke])
    with open(templates_file, "w", encoding="utf-8") as fh:
        json.dump(recorded, fh)
    print(f"[spellbook] saved a '{key}' sample -> {templates_file} "
          f"({len(recorded[key])} total)")
