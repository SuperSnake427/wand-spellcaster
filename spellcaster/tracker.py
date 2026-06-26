"""
Wand-tip tracking and gesture segmentation.

WandTracker      -- finds the bright wand tip in a single frame.
GestureCapture   -- stitches a stream of tip positions into one completed
                    "spell" stroke, deciding when a gesture starts and ends.
"""
import math

import cv2
import numpy as np

# A wand-tip location in frame coordinates and a stroke of such points.
Point = tuple[float, float]
Stroke = list[Point]


class WandTracker:
    """Finds the wand tip in a frame, by colour (active LED) or brightness.

    Parameters:
        - mode: "color" to gate on the lit LED's HSV, or "brightness" to
          threshold a grayscale image (default "color").
        - threshold: Brightness threshold 0-255 for "brightness" mode
          (default 210).
        - blur: Gaussian blur kernel size; forced odd, 0 disables (default 5).
        - min_area: Smallest accepted blob area in pixels (default 1).
        - max_area: Largest accepted blob area in pixels (default 6000).
        - min_aspect: Minimum short/long side ratio to reject elongated smears
          (default 0.0).
        - hsv_lower: Lower HSV gate bound for "color" mode.
        - hsv_upper: Upper HSV gate bound for "color" mode.
        - motion_gate: AND the mask with moving pixels to drop static
          background (default True).
        - border_crop: Pixels to blank around the frame edge (default 0).
    """

    def __init__(self, mode: str = "color", threshold: int = 210,
                 blur: int = 5, min_area: int = 1, max_area: int = 6000,
                 min_aspect: float = 0.0,
                 hsv_lower: tuple[int, int, int] = (120, 50, 110),
                 hsv_upper: tuple[int, int, int] = (165, 255, 255),
                 motion_gate: bool = True, border_crop: int = 0) -> None:
        self.mode = mode
        self.threshold = threshold
        self.blur = blur
        self.min_area = min_area
        self.max_area = max_area
        self.min_aspect = min_aspect
        self.hsv_lower = np.array(hsv_lower, np.uint8)
        self.hsv_upper = np.array(hsv_upper, np.uint8)
        self.border_crop = border_crop
        self.last_mask = None
        self.last_sample_loc = None   # frame-coords (x,y) where 'p' actually sampled
        self.motion_gate = motion_gate
        self._bgsub = self._make_bgsub() if motion_gate else None

    @staticmethod
    def _make_bgsub() -> "cv2.BackgroundSubtractorMOG2":
        """Create the MOG2 background subtractor used by the motion gate.

        History is ~200 frames so a still wand is re-absorbed within a couple
        of seconds; shadow detection is off for a clean binary foreground.

        Returns:
            - A configured MOG2 background subtractor.
        """
        return cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=25, detectShadows=False)

    def toggle_motion(self) -> bool:
        """Flip the motion gate on/off, creating the subtractor if needed.

        Returns:
            - The new motion-gate state.
        """
        self.motion_gate = not self.motion_gate
        if self.motion_gate and self._bgsub is None:
            self._bgsub = self._make_bgsub()
        return self.motion_gate

    def find_tip(self, frame: np.ndarray) -> Point | None:
        """Locate the wand tip in a frame using the configured mode.

        Parameters:
            - frame: A BGR frame.

        Returns:
            - The (x, y) tip position, or None if no tip is found.
        """
        if self.mode == "color":
            return self._find_color(frame)
        return self._find_bright(frame)

    # -- colour (active LED) -----------------------------------------------
    def _find_color(self, frame: np.ndarray) -> Point | None:
        """Find the tip by HSV-gating the lit LED.

        Parameters:
            - frame: A BGR frame.

        Returns:
            - The (x, y) tip position, or None if no blob qualifies.
        """
        blurred = frame
        if self.blur:
            k = self.blur | 1
            blurred = cv2.GaussianBlur(frame, (k, k), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.hsv_lower, self.hsv_upper)

        mask = self._apply_motion(mask, frame)

        # OPEN removes scattered speckle noise; CLOSE then merges the white-hot
        # LED core + coloured halo into one solid blob.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        if self.border_crop:
            c = self.border_crop
            mask[:c, :] = 0; mask[-c:, :] = 0
            mask[:, :c] = 0; mask[:, -c:] = 0
        self.last_mask = mask
        return self._best_blob(mask, hsv[:, :, 2])

    # Radius (frame pixels) to search around the cursor when 'p' is pressed.
    SAMPLE_SEARCH_R = 12   # frame-px; ~36 display-px at 3× scale — aim within this

    def sample_hsv(self, frame: np.ndarray, x: float, y: float,
                   h_pad: int = 10) -> tuple[int, int, int]:
        """Sample the lit tip colour near (x, y) and set the HSV gate.

        The tape is typically only 2-5 pixels wide at operating distance.
        Rather than sampling a fixed patch at the cursor (which is mostly
        background if the aim is even slightly off), this:
          1. Searches SAMPLE_SEARCH_R pixels in every direction for the
             pixel that is both bright AND saturated — the lit tape.
          2. Samples a tiny patch around that peak, not the cursor center.
          3. Stores the actual sample location in self.last_sample_loc so
             the UI can show where it really landed (use this to verify aim).

        Parameters:
            - frame: A BGR frame.
            - x: Cursor x in frame coordinates to search around.
            - y: Cursor y in frame coordinates to search around.
            - h_pad: Hue half-width applied around the sampled hue when
              building the gate (default 10).

        Returns:
            - The sampled median (h, s, v) at the peak location.
        """
        height, width = frame.shape[:2]
        cx = int(max(0, min(width  - 1, x)))
        cy = int(max(0, min(height - 1, y)))
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Search window around the cursor.
        r = self.SAMPLE_SEARCH_R
        x0, x1 = max(0, cx - r), min(width,  cx + r + 1)
        y0, y1 = max(0, cy - r), min(height, cy + r + 1)
        roi     = hsv[y0:y1, x0:x1]
        bgr_roi = frame[y0:y1, x0:x1].astype(np.float32)

        v_map = roi[:, :, 2].astype(np.float32)
        s_map = roi[:, :, 1].astype(np.float32)

        # Primary: green-channel dominance in BGR.
        # Green fluorescent tape: G >> R, B  →  positive lead.
        # UV-lit pink/magenta background: R+B >> G  →  negative lead, clamped to 0.
        # This specifically rejects UV room background regardless of brightness.
        g_lead = bgr_roi[:, :, 1] - 0.5 * (bgr_roi[:, :, 0] + bgr_roi[:, :, 2])
        score = np.clip(g_lead, 0, None) * v_map

        if score.max() < 5:          # nothing greener than background → V×S
            score = v_map * (s_map / 255.0)
        if score.max() < 1:          # nothing saturated → pure brightness
            score = v_map

        ry, rx = np.unravel_index(int(np.argmax(score)), score.shape)
        px, py = x0 + rx, y0 + ry   # peak in frame coords
        self.last_sample_loc = (px, py)
        b_win, g_win, r_win = (int(bgr_roi[ry, rx, i]) for i in range(3))
        print(f"[sample] peak @ ({px},{py})  BGR=({b_win},{g_win},{r_win})"
              f"  g_lead={g_win - 0.5*(b_win+r_win):.0f}"
              f"  score={score[ry,rx]:.0f}")

        # Sample a 5×5 patch around the peak.
        p = 2
        px0, px1 = max(0, px - p), min(width,  px + p + 1)
        py0, py1 = max(0, py - p), min(height, py + p + 1)
        region = hsv[py0:py1, px0:px1].reshape(-1, 3)

        h = int(np.median(region[:, 0]))
        s = int(np.median(region[:, 1]))
        v = int(np.median(region[:, 2]))

        if s <= 50:
            # Near-white / blown-out: gate on low-S + high-V.
            self.hsv_lower = np.array([0,   0, max(180, v - 40)], np.uint8)
            self.hsv_upper = np.array([179, 60, 255],              np.uint8)
        else:
            coloured = region[region[:, 1] >= 25]
            src = coloured if len(coloured) else region
            h = int(np.median(src[:, 0]))
            self.hsv_lower = np.array(
                [max(0, h - h_pad), max(35, s - 50), max(70, v - 60)], np.uint8)
            self.hsv_upper = np.array([min(179, h + h_pad), 255, 255], np.uint8)
        return h, s, v

    # -- brightness (retroreflective / IR emitter) -------------------------
    def _find_bright(self, frame: np.ndarray) -> Point | None:
        """Find the tip by thresholding a grayscale image for bright blobs.

        Parameters:
            - frame: A BGR frame.

        Returns:
            - The (x, y) tip position, or None if nothing bright qualifies.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.blur:
            k = self.blur | 1
            gray = cv2.GaussianBlur(gray, (k, k), 0)
        _, mask = cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY)
        mask = self._apply_motion(mask, frame)
        if self.border_crop:
            c = self.border_crop
            mask[:c, :] = 0; mask[-c:, :] = 0
            mask[:, :c] = 0; mask[:, -c:] = 0
        self.last_mask = mask
        tip = self._best_blob(mask, gray)
        if tip is not None:
            return tip
        # Fallback: a single very bright pixel.  Skip it when the motion gate is
        # on, so we don't latch onto a static bright spot (a lamp, a window).
        if not self.motion_gate:
            _, max_val, _, max_loc = cv2.minMaxLoc(gray)
            if max_val >= self.threshold:
                return (float(max_loc[0]), float(max_loc[1]))
        return None

    # -- motion gate (shared) ----------------------------------------------
    def _apply_motion(self, mask: np.ndarray, frame: np.ndarray) -> np.ndarray:
        """AND a mask with 'what moved this frame' so static background drops out.

        MOG2 must be fed once per frame to keep learning; find_tip dispatches to
        exactly one of the find_* methods, so this is called once per frame.

        Parameters:
            - mask: The candidate binary mask to gate.
            - frame: The current BGR frame fed to the background subtractor.

        Returns:
            - The mask ANDed with the moving foreground, or unchanged if the
              motion gate is off.
        """
        if not (self.motion_gate and self._bgsub is not None):
            return mask
        fg = self._bgsub.apply(frame)
        _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
        fg = cv2.dilate(fg, np.ones((7, 7), np.uint8))  # cover the glow edges
        return cv2.bitwise_and(mask, fg)

    # -- shared -------------------------------------------------------------
    def _best_blob(self, mask: np.ndarray, value: np.ndarray) -> Point | None:
        """Pick the blob most likely to be the wand tip: bright and within size.

        Among same-colour candidates (a shirt the same purple as the tip), the
        LED is an EMITTER, so its pixels are brighter -- we select the blob with
        the highest mean brightness, which beats a dim reflective shirt even when
        both pass the colour + motion gates.  An over-large blob (a whole shirt)
        is rejected by the size cap.

        Parameters:
            - mask: The binary candidate mask.
            - value: A single-channel brightness image (HSV V channel or
              grayscale) the same size as ``mask``.

        Returns:
            - The (x, y) centroid of the brightest qualifying blob, or None.
        """
        n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        if n <= 1:                       # only background
            return None
        sums = np.bincount(labels.ravel(),
                           weights=value.ravel().astype(np.float64), minlength=n)
        best, best_score = None, -1.0
        for lbl in range(1, n):          # label 0 is background
            area = int(stats[lbl, cv2.CC_STAT_AREA])
            if area < self.min_area or area > self.max_area:
                continue
            # Reject elongated smears (wall reflections, light streaks).
            # The tape tip is roughly circular; min_aspect filters blobs where
            # one dimension is >> the other (e.g. a thin reflection).
            bw = int(stats[lbl, cv2.CC_STAT_WIDTH])
            bh = int(stats[lbl, cv2.CC_STAT_HEIGHT])
            long_side = max(bw, bh, 1)
            if (min(bw, bh) / long_side) < self.min_aspect:
                continue
            # Score by mean brightness: the wand tip (emitter at ~255) is the
            # brightest blob even when small; any same-size false positive is
            # dimmer.  The tight size + aspect gate already excludes most FPs.
            score = sums[lbl] / area
            if score > best_score:
                best_score, best = score, centroids[lbl]
        if best is None:
            return None
        return (float(best[0]), float(best[1]))


class GestureCapture:
    """Turns a per-frame stream of tip positions into completed strokes.

    Parameters:
        - end_pause: Seconds the wand may be still/absent before the stroke
          ends (default 0.45).
        - min_points: Minimum points for a stroke to count (default 12).
        - min_path: Minimum total path length in pixels (default 70).
        - min_step: Minimum movement in pixels to record a new point
          (default 4).
        - max_duration: Hard cap on stroke length in seconds (default 6.0).
    """

    def __init__(self, end_pause: float = 0.45, min_points: int = 12,
                 min_path: float = 70, min_step: float = 4,
                 max_duration: float = 6.0) -> None:
        self.end_pause = end_pause
        self.min_points = min_points
        self.min_path = min_path
        self.min_step = min_step
        self.max_duration = max_duration
        self.points: Stroke = []
        self.active = False
        self.start_time = 0.0
        self.last_seen = 0.0
        self.last_move = 0.0

    @staticmethod
    def _dist(a: Point, b: Point) -> float:
        """Euclidean distance between two points.

        Parameters:
            - a: The first point.
            - b: The second point.

        Returns:
            - The distance from a to b.
        """
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _path_len(self, pts: Stroke) -> float:
        """Total polyline length of a stroke.

        Parameters:
            - pts: The stroke points.

        Returns:
            - The summed segment lengths.
        """
        return sum(self._dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))

    def update(self, tip: Point | None, now: float) -> Stroke | None:
        """Feed one frame's tip position and maybe return a finished stroke.

        A stroke ends when the tip leaves the frame OR the wand is held still
        for `end_pause` seconds -- the latter matters for an always-on LED tip,
        which never simply "disappears" mid-spell.

        Parameters:
            - tip: The tip position this frame, or None if not visible.
            - now: The current timestamp in seconds.

        Returns:
            - The completed stroke when one just ended, otherwise None.
        """
        if tip is not None:
            if not self.active:
                self.active = True
                self.points = [tip]
                self.start_time = now
                self.last_move = now
            elif self._dist(tip, self.points[-1]) >= self.min_step:
                self.points.append(tip)
                self.last_move = now
            self.last_seen = now
            # held still long enough -> end of spell
            if (now - self.last_move) > self.end_pause:
                return self._finalize()
            if now - self.start_time > self.max_duration:
                return self._finalize()
            return None

        # tip not visible this frame
        if self.active and (now - self.last_seen) > self.end_pause:
            return self._finalize()
        return None

    def _finalize(self) -> Stroke | None:
        """Reset capture state and return the stroke if it meets thresholds.

        Returns:
            - The captured stroke if it has enough points and path length,
              otherwise None.
        """
        pts = self.points
        self.active = False
        self.points = []
        if len(pts) >= self.min_points and self._path_len(pts) >= self.min_path:
            return pts
        return None
