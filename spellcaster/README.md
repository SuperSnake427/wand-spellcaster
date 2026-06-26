# Wand Spell-Casting Station

Track a wand tip with a camera, recognise the shape drawn in the air, and fire
off a spell effect. Built for a Raspberry Pi 5 + NoIR camera and the Universal
interactive (retroreflective-tip) wands — but it runs on a laptop too.

## Two ways to track the tip

Set `TRACK_MODE` in [config.py](config.py):

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
dark backdrop behind your daughter and detection becomes rock-solid. (When your
IR illuminator arrives, the NoIR camera will use it the exact same way — no code
change, just better because the light is invisible.)

## Install & run

On the **Raspberry Pi 5** (Raspberry Pi OS Bookworm — picamera2 is preinstalled):

```bash
sudo apt install -y python3-opencv python3-picamera2
python spellcaster/main.py
```

On a **laptop** (to test the recognition tonight, before the Pi):

```bash
pip install opencv-python numpy
python spellcaster/main.py
```

With no camera attached it starts in **mouse test mode** — hold the left mouse
button and draw a spell shape to see recognition working immediately.

## Using it

A live glowing trail follows the wand tip. Finish a shape, pause briefly, and it
matches the closest spell and triggers its effect (a beep for now).

Keys:

| key   | action |
|-------|--------|
| `m`   | show the detection mask — tune until **only** the tip is white |
| `p`   | (colour mode) hover over the lit tip and press to auto-sample its colour |
| `[` `]` | (brightness mode) lower / raise the brightness threshold |
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
`PRESENTATION_MODE = True` (and `FULLSCREEN = True`) in [config.py](config.py).

Drop a Harry Potter image named **`background.png`** in this folder to use as the
backdrop. If there's no such file, a procedural starry-night background is used
automatically. Change the filename via `BACKGROUND_IMAGE` in [config.py](config.py).

**Image size:** presentation is rendered at `DISPLAY_WIDTH × DISPLAY_HEIGHT`
(default **1920×1080**, 16:9 widescreen, set in [config.py](config.py)) for a
crisp fullscreen image, while the camera and tracking stay at the lower `FRAME_*`
resolution (default 640×360, also 16:9). Make `background.png` **16:9** (it's
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
your daughter's hand** match far better. Press `r`, type a spell key (e.g.
`lumos`), draw it, and it's saved to `templates.json` and used immediately.
Record 3–5 samples per spell for best results.

## The spells

Defined in [spellbook.py](spellbook.py) — edit names, hints, shapes, and which
effect each triggers. Current set: Lumos (circle), Nox (square), Wingardium
Leviosa (up-flick ^), Locomotor (checkmark), Incendio (zig-zag Z), Aguamenti
(v), Reducto (triangle), Expecto Patronum (star).

Tip: keep spell shapes **visually distinct**. The recogniser is tolerant of
size, position, and tilt, so two shapes that differ only by rotation (a
horizontal vs. vertical line) can be confused — use different *shapes* instead.

## Tuning

All knobs are in [config.py](config.py): `BRIGHTNESS_THRESHOLD` (detection),
the `GESTURE_*` timings (when a stroke starts/ends), and `MIN_SCORE` (how close
a match must be — lower it if a wobbly drawing isn't recognised).

## Hardware: the relay shield (Keyestudio RPi 4-channel)

Effect routing already exists in [effects.py](effects.py); the methods are
stubbed so nothing breaks off-Pi. **Lumos turns relay channel 1 ON** (and Nox
turns it OFF) — only when the spell is recognised (score ≥ `MIN_SCORE`).

On the Raspberry Pi:

1. Seat the shield on the 40-pin header. Channel→GPIO is fixed by the shield and
   set in `RELAY_CH` in [config.py](config.py) (defaults `{1:4, 2:17, 3:27,
   4:26}` for the Keyestudio KS0212). **Verify** against your shield's silkscreen.
2. **Test the wiring first:** `python3 tests/relay_test.py 1` clicks channel 1 on for
   ~1.5s. `python3 tests/relay_test.py` cycles all four. If a relay is on when it says
   off (or all click on at boot), set `RELAY_ACTIVE_HIGH = False` in config.py.
3. Set `USE_GPIO = True` in config.py and run the app. Cast Lumos (draw a circle)
   → channel 1 energises. Wire your light to that channel's NO/COM terminals.

`PIN_LIGHT`/`PIN_FAN`/`PIN_ACTUATOR_EXTEND`/`PIN_ACTUATOR_RETRACT` map the four
effects to channels 1–4. Each spell's `effect` key in `spellbook.py` maps to a
`_fx_<effect>` method, so adding an effect is just a method + a spell pointing at
it. Tune fan/actuator on-times in the `_fx_*` methods.

gpiozero (used for the relays) ships with Raspberry Pi OS. On the Pi 5 it drives
the pins via lgpio automatically — no extra setup.

## How it fits together

```
camera.py    frames (Pi camera or webcam)
tracker.py   WandTracker  -> bright tip (x, y) per frame
             GestureCapture -> stitches tips into one finished stroke
dollar.py    $1 recogniser -> stroke -> (spell, score)
spellbook.py the spell list + shapes + recorded templates
effects.py   spell -> hardware/sound effect
main.py      ties it together + the on-screen UI
```
