"""
Debug the tracker live: captures frames, runs the full tracker pipeline,
and saves annotated images showing every blob the tracker considers.

Usage:
    python tests/debug_tracker.py

Hold the wand in frame when prompted. Saves:
    debug_bg.png      -- background frame (no wand)
    debug_wand_N.png  -- annotated wand frames showing blobs + chosen tip
    debug_mask_N.png  -- the raw binary mask after all morphology
"""

import os
import sys
import time
import cv2
import numpy as np

# Allow flat imports (camera, tracker, config) when run from the tests/ subfolder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from camera import Camera
from tracker import WandTracker
import config

N = 3

cam = Camera(
    width=config.FRAME_WIDTH,
    height=config.FRAME_HEIGHT,
    fps=config.TARGET_FPS,
    prefer_picamera=config.PREFER_PICAMERA,
    swap_rb=config.SWAP_RB,
)
print(f"Camera: {cam.backend}")

tracker = WandTracker(
    mode=config.TRACK_MODE,
    threshold=config.BRIGHTNESS_THRESHOLD,
    blur=config.BLUR_KERNEL,
    min_area=config.MIN_BLOB_AREA,
    max_area=config.MAX_BLOB_AREA,
    hsv_lower=config.HSV_LOWER,
    hsv_upper=config.HSV_UPPER,
    motion_gate=config.TRACK_MOTION_GATE,
)

print(f"\nHSV gate: lower={tuple(tracker.hsv_lower)}  upper={tuple(tracker.hsv_upper)}")
print(f"Motion gate: {tracker.motion_gate}")
print(f"Blob area: {tracker.min_area}..{tracker.max_area}")


def drain(n: int = 8) -> None:
    """Discard a few frames so the next read is fresh.

    Parameters:
        - n: The number of frames to read and throw away (default 8).
    """
    for _ in range(n):
        cam.read()


def annotate_blobs(frame: np.ndarray, mask: np.ndarray,
                   chosen_tip: tuple[float, float] | None,
                   label: str) -> np.ndarray:
    """Draw every blob on the frame and highlight the chosen one.

    Parameters:
        - frame: The BGR frame to annotate.
        - mask: The binary mask the blobs come from.
        - chosen_tip: The tip the tracker selected, or None.
        - label: A caption drawn in the top-left corner.

    Returns:
        - A copy of the frame with blobs, scores, and the chosen tip drawn.
    """
    out = frame.copy()

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    sums = np.bincount(labels.ravel(),
                       weights=v.ravel().astype(np.float64), minlength=n)

    for lbl in range(1, n):
        area = int(stats[lbl, cv2.CC_STAT_AREA])
        cx, cy = centroids[lbl]
        total = sums[lbl]
        mean_v = total / area if area else 0
        in_range = tracker.min_area <= area <= tracker.max_area
        color = (0, 255, 0) if in_range else (60, 60, 60)
        cv2.circle(out, (int(cx), int(cy)), 8, color, 2)
        cv2.putText(out, f"a={area} t={total:.0f} m={mean_v:.0f}",
                    (int(cx) + 10, int(cy)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)

    if chosen_tip:
        cv2.circle(out, (int(chosen_tip[0]), int(chosen_tip[1])), 14, (0, 0, 255), 3)
        cv2.putText(out, "CHOSEN", (int(chosen_tip[0]) + 16, int(chosen_tip[1]) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)

    cv2.putText(out, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (200, 200, 0), 2, cv2.LINE_AA)
    return out


# --- Phase 1: warm up motion gate with background frames -------------------
print("\nPhase 1: keep the wand OUT of frame.")
print("Press ENTER, then stay still for ~3 s to warm up the motion gate...")
input()

bg_frame = None
for i in range(200):          # feed MOG2 ~3 s worth at 60 fps
    f = cam.read()
    if f is not None:
        tracker.find_tip(f)   # feeds MOG2 without using the result
        bg_frame = f
    time.sleep(0.016)
print("  background learned.")
if bg_frame is not None:
    cv2.imwrite("debug_bg.png", bg_frame)
    print("  saved debug_bg.png")

# --- Phase 2: wand frames --------------------------------------------------
print("\nPhase 2: bring the LIT wand tip into frame.")
print("Press ENTER when ready...")
input()

for i in range(N):
    drain()
    frame = cam.read()
    tip = tracker.find_tip(frame)
    mask = tracker.last_mask

    print(f"\n  Frame {i}: tip={tip}")
    if mask is not None:
        n, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        v = hsv[:, :, 2]
        sums = np.bincount(cv2.connectedComponents(mask, 8)[1].ravel(),
                           weights=v.ravel().astype(np.float64), minlength=n)
        for lbl in range(1, n):
            area = int(stats[lbl, cv2.CC_STAT_AREA])
            cx, cy = centroids[lbl]
            total = sums[lbl] if lbl < len(sums) else 0
            tag = " <-- CHOSEN" if (tip and abs(cx - tip[0]) < 2 and abs(cy - tip[1]) < 2) else ""
            ok = tracker.min_area <= area <= tracker.max_area
            print(f"    blob {lbl}: area={area:4d}  total={total:8.0f}  "
                  f"mean={total/area if area else 0:5.1f}  "
                  f"center=({cx:.0f},{cy:.0f})  "
                  f"{'OK' if ok else 'SKIP'}{tag}")

        ann = annotate_blobs(frame, mask, tip, f"wand {i}")
        cv2.imwrite(f"debug_wand_{i}.png", ann)
        cv2.imwrite(f"debug_mask_{i}.png", mask)
        print(f"  saved debug_wand_{i}.png  debug_mask_{i}.png")
    time.sleep(0.1)

cam.close()
print("\nDone. Open debug_wand_*.png to see all blobs and the chosen tip.")
