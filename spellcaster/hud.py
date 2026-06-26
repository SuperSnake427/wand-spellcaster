"""
On-screen drawing for the spell-casting station.

Pure rendering helpers split out of main.py: each takes the canvas plus the
state it needs and draws onto the canvas in place (or returns a fresh image for
the background builders).  Keeping these free of App state makes the main loop
in main.py easier to read and these helpers easy to test in isolation.
"""
import os

import cv2
import numpy as np

import config
import spellbook
from tracker import WandTracker

# (text, BGR colour, expiry timestamp) for the transient feedback banner.
Banner = tuple[str, tuple[int, int, int], float]


# -- backgrounds ------------------------------------------------------------
def starfield(w: int, h: int) -> np.ndarray:
    """Draw a dark blue-violet gradient sprinkled with stars.

    Parameters:
        - w: The image width in pixels.
        - h: The image height in pixels.

    Returns:
        - The generated starfield image.
    """
    bg = np.zeros((h, w, 3), np.uint8)
    # dark blue-violet vertical gradient (BGR)
    top, bottom = np.array([45, 12, 28]), np.array([12, 4, 10])
    for y in range(h):
        bg[y, :] = (top + (bottom - top) * (y / h)).astype(np.uint8)
    rng = np.random.default_rng(7)
    for _ in range(240):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        b = int(rng.integers(110, 256))
        cv2.circle(bg, (x, y), int(rng.integers(0, 2)), (b, b, b), -1)
    return bg


def load_background(path: str | None, size: tuple[int, int]) -> np.ndarray:
    """Load the presentation-mode backdrop.

    Parameters:
        - path: Path to a background image, or None/missing to use a starfield.
        - size: The (width, height) to resize the backdrop to.

    Returns:
        - The background image, or a procedurally-drawn starfield if the file
          is missing/unreadable.
    """
    if path and os.path.exists(path):
        img = cv2.imread(path)
        if img is not None:
            print(f"[hud] background image: {path}")
            return cv2.resize(img, size)
        print(f"[hud] couldn't read {path}; using starfield")
    return starfield(*size)


# -- swatch -----------------------------------------------------------------
def swatch_color(hsv_lower: np.ndarray,
                 hsv_upper: np.ndarray) -> tuple[int, int, int]:
    """Compute a representative BGR colour from an HSV gate for display.

    Parameters:
        - hsv_lower: The lower HSV gate bound.
        - hsv_upper: The upper HSV gate bound.

    Returns:
        - A BGR triple representing the middle of the gate.
    """
    h_mid = (int(hsv_lower[0]) + int(hsv_upper[0])) // 2
    s_mid = max(160, (int(hsv_lower[1]) + int(hsv_upper[1])) // 2)
    v_mid = max(180, (int(hsv_lower[2]) + int(hsv_upper[2])) // 2)
    swatch_hsv = np.uint8([[[h_mid, s_mid, v_mid]]])
    bgr = cv2.cvtColor(swatch_hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return tuple(int(x) for x in bgr)


def draw_swatch(canvas: np.ndarray,
                color: tuple[int, int, int] | None) -> None:
    """Draw a filled colour block showing the currently trained tip colour.

    Parameters:
        - canvas: The display canvas to draw on (modified in place).
        - color: The trained BGR colour, or None to draw nothing.
    """
    if not color:
        return
    h, w = canvas.shape[:2]
    sw = 90
    x0, x1 = w - sw - 14, w - 14
    y0, y1 = 14, 14 + sw
    cv2.rectangle(canvas, (x0, y0), (x1, y1), color, -1)
    cv2.rectangle(canvas, (x0, y0), (x1, y1), (255, 255, 255), 2)
    cv2.putText(canvas, "trained", (x0 + 4, y1 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)


# -- trail / banner ---------------------------------------------------------
def draw_trail(canvas: np.ndarray, points: list[tuple[float, float]],
               sx: float = 1.0, sy: float = 1.0,
               color: tuple[int, int, int] = (80, 180, 255)) -> None:
    """Draw a glowing wand trail polyline onto the canvas.

    Parameters:
        - canvas: The display canvas to draw on (modified in place).
        - points: The stroke points in frame coordinates.
        - sx: Horizontal frame→canvas scale (default 1.0).
        - sy: Vertical frame→canvas scale (default 1.0).
        - color: The BGR glow colour (default warm blue).
    """
    pts = np.array(points, np.float32)
    if sx != 1.0 or sy != 1.0:
        pts[:, 0] *= sx
        pts[:, 1] *= sy
    pts = pts.astype(np.int32)
    s = (sx + sy) / 2.0
    glow = max(2, int(round(9 * s)))
    core = max(1, int(round(2 * s)))
    cv2.polylines(canvas, [pts], False, color, glow, cv2.LINE_AA)       # glow
    cv2.polylines(canvas, [pts], False, (255, 255, 255), core, cv2.LINE_AA)  # core


def draw_banner(canvas: np.ndarray, banner: Banner | None, now: float) -> None:
    """Draw the transient spell-feedback banner if it hasn't expired.

    Parameters:
        - canvas: The display canvas to draw on (modified in place).
        - banner: The (text, colour, expiry) banner, or None.
        - now: The current timestamp in seconds.
    """
    if banner and now < banner[2]:
        text, color, _ = banner
        h = canvas.shape[0]
        fs = h / 480.0   # scale font with canvas height (high-res in present.)
        cv2.putText(canvas, text, (int(12 * fs), h - int(22 * fs)),
                    cv2.FONT_HERSHEY_DUPLEX, fs, color,
                    max(2, int(round(2 * fs))), cv2.LINE_AA)


# -- dev chrome / overlays --------------------------------------------------
def draw_chrome(canvas: np.ndarray, tracker: WandTracker, *,
                test_mode: bool, record_key: str | None, fps: float,
                show_help: bool) -> None:
    """Draw the dev-mode status line and (optionally) the help/spell list.

    Parameters:
        - canvas: The display canvas to draw on (modified in place).
        - tracker: The wand tracker, read for mode/threshold/motion state.
        - test_mode: Whether mouse-test mode is active.
        - record_key: The spell key armed for recording, or None.
        - fps: The current frames-per-second estimate.
        - show_help: Whether to also draw the help/spell list.
    """
    src = "TEST" if test_mode else tracker.mode.upper()
    mot = "on" if tracker.motion_gate else "off"
    if tracker.mode == "brightness":
        detail = f"thr:{tracker.threshold} crop:{tracker.border_crop} motion:{mot}"
    else:
        detail = f"Vmin:{int(tracker.hsv_lower[2])} crop:{tracker.border_crop} motion:{mot}"
    status = f"{src}  {detail}  fps:{fps:0.0f}"
    if record_key:
        status += f"  [REC -> {record_key}]"
    cv2.putText(canvas, status, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 255, 0), 2, cv2.LINE_AA)

    if show_help:
        lines = [f"{s['name']}: {s['hint']}" for s in spellbook.SPELLS]
        lines += ["", "q quit  m mask  b mode  l learn-colour  g motion",
                  "p sample  [ ] thr/Vmin  r rec  t test",
                  "space presentation  f fullscreen  h help"]
        y = 50
        for ln in lines:
            cv2.putText(canvas, ln, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (200, 200, 200), 1, cv2.LINE_AA)
            y += 20


def draw_calibration(canvas: np.ndarray, info: dict) -> None:
    """Draw the colour-training overlay band, text, and progress bar.

    Parameters:
        - canvas: The display canvas to draw on (modified in place).
        - info: The calibrator info dict (text/progress).
    """
    h, w = canvas.shape[:2]
    band = canvas.copy()
    cv2.rectangle(band, (0, h // 2 - 55), (w, h // 2 + 55), (40, 10, 40), -1)
    cv2.addWeighted(band, 0.6, canvas, 0.4, 0, canvas)

    text = info.get("text", "")
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 0.9, 2)
    cv2.putText(canvas, text, (max(10, (w - tw) // 2), h // 2),
                cv2.FONT_HERSHEY_DUPLEX, 0.9, (235, 235, 255), 2, cv2.LINE_AA)

    progress = info.get("progress")
    if progress is not None:
        x0, x1, y = w // 4, 3 * w // 4, h // 2 + 32
        cv2.rectangle(canvas, (x0, y), (x1, y + 12), (90, 90, 90), 1)
        fill = int((x1 - x0) * max(0.0, min(1.0, progress)))
        cv2.rectangle(canvas, (x0, y), (x0 + fill, y + 12), (120, 220, 255), -1)
    cv2.putText(canvas, "press 'l' to cancel", (max(10, (w - 180) // 2),
                h // 2 + 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (180, 180, 180), 1, cv2.LINE_AA)


def draw_reticle(canvas: np.ndarray, mouse_pos: tuple[int, int] | None,
                 tracker: WandTracker, frame: np.ndarray | None,
                 win_w: int, win_h: int) -> None:
    """Draw the targeting reticle for 'p' colour sampling.

    Outer circle = search radius: any tape inside this circle will be found
    even if the cursor isn't exactly on it.
    Inner crosshair = cursor centre.
    Green dot = where the last 'p' actually sampled.

    Parameters:
        - canvas: The display canvas to draw on (modified in place).
        - mouse_pos: The raw screen-space cursor position, or None.
        - tracker: The wand tracker, read for search radius + last sample loc.
        - frame: The current camera frame (for frame size), or None.
        - win_w: The window image width in screen pixels.
        - win_h: The window image height in screen pixels.
    """
    if mouse_pos is None:
        return
    mx_s, my_s = mouse_pos   # raw screen coords from OpenCV callback

    # Map screen → canvas so everything is drawn at the right canvas position
    cx = int(mx_s * config.DISPLAY_WIDTH / win_w)
    cy = int(my_s * config.DISPLAY_HEIGHT / win_h)

    # Search-radius circle in canvas pixels (SAMPLE_SEARCH_R is in frame pixels)
    frame_w = config.FRAME_WIDTH if frame is None else frame.shape[1]
    frame_h = config.FRAME_HEIGHT if frame is None else frame.shape[0]
    search_canvas = int(tracker.SAMPLE_SEARCH_R * config.DISPLAY_WIDTH / frame_w)

    cv2.circle(canvas, (cx, cy), search_canvas, (0, 220, 255), 1, cv2.LINE_AA)
    cv2.circle(canvas, (cx, cy), 5, (0, 220, 255), -1, cv2.LINE_AA)
    cv2.drawMarker(canvas, (cx, cy), (0, 220, 255),
                   cv2.MARKER_CROSS, 30, 1, cv2.LINE_AA)
    cv2.putText(canvas, "P to sample", (cx + search_canvas + 6, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 220, 255), 1, cv2.LINE_AA)

    # Green dot shows where the LAST sample actually landed (frame → canvas).
    loc = tracker.last_sample_loc
    if loc is not None:
        csx = config.DISPLAY_WIDTH / frame_w
        csy = config.DISPLAY_HEIGHT / frame_h
        lx, ly = int(loc[0] * csx), int(loc[1] * csy)
        cv2.circle(canvas, (lx, ly), 8, (0, 255, 80), -1, cv2.LINE_AA)
        cv2.circle(canvas, (lx, ly), 8, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, "sampled here", (lx + 12, ly + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 80), 1, cv2.LINE_AA)
