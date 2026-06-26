# Harry Potter Wand Spell-Casting Station

Track a wand tip with a camera, recognise the gesture drawn in the air, and fire
off a themed effect — lights, a "fireplace" on an Apple TV, a blender, and spell
sounds. Built for a Raspberry Pi 5 + NoIR camera, but it also runs on a laptop
(USB webcam, or mouse-test mode with no camera at all).

Entirely vibe coded (Claude) less than 24 hours before my daughter's 10 birthday... use entirely at your own risk! It was a blast at the party though! We had the PI -> Camera and a projector. The kids could see the spells on the wall and there was a place mat where they were to stand to cast their spells.

## Quick start

```bash
cd spellcaster
pip install -r requirements.txt
python main.py
```

No camera? It starts in **mouse-test mode** — draw spells with the mouse.

The full guide (tracking modes, the lighting trick, gesture recording, hardware
wiring, and Apple TV / Kasa setup) lives in **[spellcaster/README.md](spellcaster/README.md)**.

## Layout

| Path | What it is |
|------|------------|
| [spellcaster/](spellcaster/) | The application package (run `main.py`). |
| [spellcaster/tests/](spellcaster/tests/) | Manual diagnostic & setup scripts (hardware tests, calibration capture, Apple TV pairing). |
| [spellcaster/assets/](spellcaster/assets/) | Spell sound effects (`<spell>.wav`). |

## First-run setup notes

- **Apple TV:** run `python tests/pair_appletv.py` once to pair; it writes
  `appletv_credentials.json` (gitignored — keep it private).
- **Device IPs:** set your Kasa plug and Apple TV addresses in
  [spellcaster/config.py](spellcaster/config.py).
- **Calibration:** `templates.json` (recorded gestures) and `color_profile.json`
  (learned tip colour) are personal and gitignored. Copy the `.example` files or
  just let the app regenerate them — press `r` to record gestures and `l`/`p` to
  learn the tip colour in the app.

## Notes

- I also had a relay shield for the PI, didn't end up using it but had some effects in mind with it
- The AppleTV was a bit finicky and I didn't end up using it. It worked with the test scripts though.
- The wand tracking/color is very sensitive to ambient lighting. It helps to have the wand tip stand out from the background.

## License

[MIT](LICENSE).
