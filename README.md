# Harry Potter Wand Spell-Casting Station

Track a wand tip with a camera, recognise the gesture drawn in the air, and fire
off a themed effect — lights, a "fireplace" on an Apple TV, a blender, and spell
sounds. Built for a Raspberry Pi 5 + NoIR camera and the Universal interactive
(retroreflective-tip) wands — but it runs on a laptop too (USB webcam, or
mouse-test mode with no camera at all).

Entirely vibe coded (Claude) less than 24 hours before my daughter's 10 birthday... use entirely at your own risk! It was a blast at the party though! We had the PI -> Camera and a projector. The kids could see the spells on the wall and there was a place mat where they were to stand to cast their spells.

## Quick start

Requires **Python 3.10+**. The code lives in `src/spellcaster/`.

**Laptop / dev (uv):**

```bash
uv sync
uv run spellcaster
```

No camera? It starts in **mouse-test mode** — hold the left mouse button and draw
a spell shape to see recognition working immediately.

**Raspberry Pi 5** (Raspberry Pi OS Bookworm) — the camera and relays use the
system `picamera2`/`gpiozero` (apt packages, which an isolated uv venv can't see),
so run with the **system** Python and the package on the path:

```bash
sudo apt install -y python3-opencv python3-picamera2
PYTHONPATH=src python -m spellcaster.main
```

## Two ways to track the tip

Set `TRACK_MODE` in [config.py](src/spellcaster/config.py):

- **`"color"` (default)** — for a wand with an **active coloured LED** at the
  tip (e.g. the purple-light wand). This is the easiest and most reliable: the
  light is visible at *any* wand angle and works in a normally-lit room. Tune it
  in seconds: run the app, hover the mouse over the lit tip, and press **`p`** to
  auto-sample the colour. The console prints the exact `HSV_LOWER`/`HSV_UPPER`
  values to paste into `config.py` to make it permanent.
- **`"brightness"`** — for a **retroreflective** tip (the Universal wands), using
  the lighting trick below.

## The lighting trick (retroreflective / brightness mode)

The wand tip is a **retroreflector**: it bounces light straight back toward
wherever the light came from. Universal uses *infrared* only so the light is
invisible to guests. At home you don't care about that, so:

> **Put a bright white light right next to the camera lens, pointing the same
> way.** A small LED flashlight or clip light taped beside the camera is perfect.

When the wand points back at the camera, the tip lights up as the brightest dot
in the frame, and that's all the tracker needs. Dim the room a little and use a
dark backdrop and detection becomes rock-solid. (When an IR illuminator is
added, the NoIR camera uses it the exact same way — no code change, just better
because the light is invisible.)

## Using it

A live glowing trail follows the wand tip. Finish a shape, pause briefly, and it
matches the closest spell and triggers its effect.

Keys:

| key   | action |
|-------|--------|
| `m`   | show the detection mask — tune until **only** the tip is white |
| `p`   | (colour mode) hover over the lit tip and press to auto-sample its colour |
| `[` `]` | (brightness mode) lower / raise the brightness threshold |
| `l`   | (colour mode) learn the tip colour by light off/on difference |
| `g`   | toggle the motion gate |
| `b`   | toggle colour / brightness tracking mode |
| `r`   | record a sample: type the spell key in the console, then draw it once |
| `t`   | toggle mouse test mode |
| `c`   | clear the current trail |
| `h`   | toggle help / spell list |
| `space` | toggle **presentation mode** (themed background, hides all dev text) |
| `f`   | toggle fullscreen |
| `q`   | quit |

### Presentation mode (for the actual party)

Press **`space`** to flip into presentation mode: it swaps the camera view for a
themed backdrop and hides *all* the dev text — the green status line, the help
list, and the tracking circle — leaving just the glowing spell trail and the
spell-cast banner. Press **`f`** for fullscreen. To boot straight into it, set
`PRESENTATION_MODE = True` (and `FULLSCREEN = True`) in [config.py](src/spellcaster/config.py).

Drop a Harry Potter image named **`background.png`** in `src/spellcaster/` to
use as the backdrop. If there's no such file, a procedural starry-night background is
used automatically. Change the filename via `BACKGROUND_IMAGE` in
[config.py](src/spellcaster/config.py).

**Image size:** presentation is rendered at `DISPLAY_WIDTH x DISPLAY_HEIGHT`
(default **1920x1080**, 16:9 widescreen, set in [config.py](src/spellcaster/config.py)) for a
crisp fullscreen image, while the camera and tracking stay at the lower `FRAME_*`
resolution (default 640x360, also 16:9). Make `background.png` **16:9** (it's
scaled to fit; matching the ratio avoids stretching). Bump `DISPLAY_WIDTH/HEIGHT`
for an even sharper screen; it costs nothing in tracking performance. If you
change the display aspect ratio, change `FRAME_*` to match so the trail maps
without distortion.

### Train the tip colour (best fix for background bleed)

If the mask keeps catching the background (a purple shirt, a lamp), press **`l`**
and follow the on-screen steps:

1. **Light OFF** — it learns the background for a couple of seconds.
2. **Light ON** — wave the wand in big circles while it watches.

It keeps only the pixels that *changed and got brighter* between off and on —
i.e. just the LED — and learns a tight colour gate from those. A static shirt
doesn't change between the two phases, so it's excluded automatically. The
result is saved to `color_profile.json` and reloaded on every restart, so you
only do this once (re-run it if you change wands or the room lighting).

### Record real samples (recommended)

The built-in shapes work, but samples drawn with the **actual wand, camera, and
hand** match far better. Press `r`, type a spell key (e.g. `lumos`), draw it, and
it's saved to `templates.json` and used immediately. Record 3–5 samples per
spell for best results.

## The spells

Defined in [spellbook.py](src/spellcaster/spellbook.py) — edit names, hints, shapes, and which
effect each triggers. Current set: Lumos (circle), Descendo (swipe down),
Incendio (Z), Aguamenti (wave), Stupefy (checkmark), Confundus (W), Alohomora
(L), Expelliarmus (slash up), Reparo (star), Ascendio (caret), Herbivicus
(triangle), Serpensortia (S).

Tip: keep spell shapes **visually distinct**. The recogniser is tolerant of
size, position, and tilt, so two shapes that differ only by rotation can be
confused — use different *shapes* instead.

## Tuning

All knobs are in [config.py](src/spellcaster/config.py): `BRIGHTNESS_THRESHOLD` (detection),
the `GESTURE_*` timings (when a stroke starts/ends), and `MIN_SCORE` (how close
a match must be — lower it if a wobbly drawing isn't recognised).

## Hardware: the relay shield (Keyestudio RPi 4-channel)

Effect routing exists in [effects.py](src/spellcaster/effects.py). On the Raspberry Pi:

1. Seat the shield on the 40-pin header. Channel→GPIO is fixed by the shield and
   set in `RELAY_CH` in [config.py](src/spellcaster/config.py) (defaults `{1:4, 2:17, 3:27,
   4:26}` for the Keyestudio KS0212). **Verify** against your shield's silkscreen.
2. **Test the wiring first:** `PYTHONPATH=src python tests/relay_test.py 1` clicks
   channel 1 on for ~1.5s; drop the `1` to cycle all four. If a relay is on when it
   says off (or all click on at boot), set `RELAY_ACTIVE_HIGH = False` in
   config.py.
3. Set `USE_GPIO = True` in config.py and run the app.

gpiozero (used for the relays) ships with Raspberry Pi OS. On the Pi 5 it drives
the pins via lgpio automatically — no extra setup.

## First-run setup notes

- **Apple TV:** run `uv run python tests/pair_appletv.py` once to pair; it writes
  `appletv_credentials.json` (gitignored — keep it private).
- **Device IPs:** set your Kasa plug and Apple TV addresses in
  [config.py](src/spellcaster/config.py).
- **Calibration:** `templates.json` (recorded gestures) and `color_profile.json`
  (learned tip colour) are personal and gitignored. Copy the `.example` files or
  just let the app regenerate them (`r` to record gestures, `l`/`p` to learn the
  tip colour).

## How it fits together

```
camera.py        frames (Pi camera or webcam)
tracker.py       WandTracker    -> bright tip (x, y) per frame
                 GestureCapture -> stitches tips into one finished stroke
dollar.py        $1 recogniser  -> stroke -> (spell, score)
spellbook.py     the spell list + shapes + recorded templates
effects.py       spell -> hardware/sound effect
                 (kasa_device.py / appletv_device.py / async_device.py)
hud.py           on-screen drawing (trail, overlays, presentation backdrop)
main.py          ties it together + the on-screen UI / input loop
```

## Notes

- I also had a relay shield for the PI, didn't end up using it but had some effects in mind with it
- The AppleTV was a bit finicky and I didn't end up using it. It worked with the test scripts though.
- The wand tracking/color is very sensitive to ambient lighting. It helps to have the wand tip stand out from the background.
- If you get an error "OpenCV: not authorized to capture video (status 0), requesting... OpenCV: camera failed to properly initialize!" on a mac, run this: tccutil reset Camera com.apple.Terminal

## License

[MIT](LICENSE).
