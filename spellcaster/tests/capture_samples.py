"""
Capture reference frames for tuning the wand tracker.

Usage:
    python tests/capture_samples.py

Step 1: Hold the wand OUT of frame -- captures 3 background frames.
Step 2: Move the wand IN -- captures 3 frames of the lit wand tip.

Saves:
    bg_0.png, bg_1.png, bg_2.png      -- background (no wand)
    wand_0.png, wand_1.png, wand_2.png -- wand in frame

Also prints the HSV stats (min/max/mean) for the brightest region in each
wand frame so you can see what colour range to target in config.py.
"""

import os
import sys
import time

import cv2
import numpy as np

# Allow flat imports (camera, config) when run from the tests/ subfolder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from camera import Camera

N = 3           # frames to capture per phase
BRIGHTEST_PCT = 2  # analyse the top-N% pixels by brightness


def hsv_stats(frame: np.ndarray
              ) -> tuple[tuple[int, int, int], np.ndarray]:
    """
    Compute median HSV of the brightest region of a frame.

    Parameters:
        - frame: A BGR frame.

    Returns:
        - A ((h_med, s_med, v_med), hsv_image) pair where the medians come from
          the top BRIGHTEST_PCT% brightest pixels.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    thresh = np.percentile(v, 100 - BRIGHTEST_PCT)
    mask = v >= thresh
    pixels = hsv[mask]  # shape (N, 3)
    return (int(np.median(pixels[:, 0])),
            int(np.median(pixels[:, 1])),
            int(np.median(pixels[:, 2]))), hsv


def annotate(frame: np.ndarray, label: str,
             stats: tuple[int, int, int] | None = None) -> np.ndarray:
    """
    Draw a label (and optional HSV stats) onto a copy of a frame.

    Parameters:
        - frame: The BGR frame to annotate.
        - label: The caption to draw.
        - stats: Optional (h, s, v) medians to also print (default None).

    Returns:
        - The annotated frame copy.
    """
    out = frame.copy()
    cv2.putText(out, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (0, 255, 0), 2, cv2.LINE_AA)
    if stats:
        h, s, v = stats
        cv2.putText(out, f"H={h} S={s} V={v} (top {BRIGHTEST_PCT}% bright)",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 255, 255), 2, cv2.LINE_AA)
    return out


cam = Camera(
    width=config.FRAME_WIDTH,
    height=config.FRAME_HEIGHT,
    fps=config.TARGET_FPS,
    prefer_picamera=config.PREFER_PICAMERA,
    swap_rb=config.SWAP_RB,
)

print(f"Camera backend: {cam.backend}")

# --- Phase 1: background frames (no wand) -----------------------------------
print("\nPhase 1: keep the wand OUT of frame.")
print("Press ENTER when ready, then stay still...")
input()

bg_frames = []
for i in range(N):
    for _ in range(5):          # discard a few to let AGC settle
        cam.read()
    frame = cam.read()
    if frame is None:
        continue
    bg_frames.append(frame)
    path = f"bg_{i}.png"
    cv2.imwrite(path, annotate(frame, f"background {i}"))
    print(f"  saved {path}")
    time.sleep(0.1)

# --- Phase 2: wand frames ---------------------------------------------------
print("\nPhase 2: bring the LIT wand tip into the centre of the frame.")
print("Press ENTER when ready...")
input()

wand_frames = []
for i in range(N):
    for _ in range(5):
        cam.read()
    frame = cam.read()
    if frame is None:
        continue
    stats, _ = hsv_stats(frame)
    wand_frames.append((frame, stats))
    path = f"wand_{i}.png"
    cv2.imwrite(path, annotate(frame, f"wand {i}", stats))
    h, s, v = stats
    print(f"  saved {path}  -- H={h} S={s} V={v}")
    time.sleep(0.1)

cam.close()

# --- Summary ----------------------------------------------------------------
print("\n--- HSV summary (top-2% brightest pixels in each wand frame) ---")
for i, (_, (h, s, v)) in enumerate(wand_frames):
    print(f"  wand_{i}: H={h:3d}  S={s:3d}  V={v:3d}")

hs = [s[0] for _, s in wand_frames]
ss = [s[1] for _, s in wand_frames]
vs = [s[2] for _, s in wand_frames]
print("\nSuggested HSV gate (with ±15 H padding, loose S/V):")
print(f"  HSV_LOWER = ({max(0, min(hs)-15)}, {max(20, min(ss)-40)}, {max(50, min(vs)-60)})")
print(f"  HSV_UPPER = ({min(179, max(hs)+15)}, 255, 255)")
print("\nDone. Open the .png files to inspect the captured frames.")
