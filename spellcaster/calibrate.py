"""
Color training for the wand tip.

Single-point colour sampling struggles when the background contains a similar
colour (a purple shirt).  This learns the tip colour by *difference* instead:

  1. Capture the scene with the wand light OFF  -> background model.
  2. Capture it with the light ON while you wave the wand in circles.
  3. Keep only the pixels that CHANGED and got brighter between off and on --
     those are the LED and nothing else -- and learn their HSV distribution.

Because a static shirt doesn't change between the two phases, it's excluded
automatically.  The result is a tight HSV gate saved to a profile file so it
survives restarts (no editing config.py needed).

The whole thing is a small state machine driven one frame at a time so the live
preview keeps running and the user can see what to do.
"""
import json
import os

import cv2
import numpy as np

IDLE = "idle"
COUNTDOWN_BG = "cd_bg"
CAPTURE_BG = "cap_bg"
COUNTDOWN_FG = "cd_fg"
CAPTURE_FG = "cap_fg"


class ColorCalibrator:
    """State machine that learns the wand-tip HSV gate by light off/on diff.

    Parameters:
        - countdown: Seconds of count-in before each capture phase
          (default 3.0).
        - bg_secs: Seconds spent averaging the light-off background
          (default 2.0).
        - fg_secs: Seconds spent sampling the lit tip (default 6.0).
        - change_delta: How much brighter a pixel must get between off and on
          to count as the LED (default 35).
        - min_value: How bright a changed pixel must end up to count
          (default 110).
    """

    def __init__(self, countdown: float = 3.0, bg_secs: float = 2.0,
                 fg_secs: float = 6.0, change_delta: int = 35,
                 min_value: int = 110) -> None:
        self.countdown = countdown
        self.bg_secs = bg_secs
        self.fg_secs = fg_secs
        self.change_delta = change_delta   # how much brighter a pixel must get
        self.min_value = min_value         # ...and how bright it must end up
        self.state = IDLE
        self.phase_start = 0.0
        self._bg_sum: np.ndarray | None = None
        self._bg_n = 0
        self.bg_gray: np.ndarray | None = None
        self._samples: list[np.ndarray] = []
        self._blob_sizes: list[int] = []   # per-frame blob area measurements
        self._rng = np.random.default_rng(0)

    @property
    def active(self) -> bool:
        """Whether a calibration run is currently in progress."""
        return self.state != IDLE

    def start(self, now: float) -> None:
        """Begin a calibration run, resetting all accumulators.

        Parameters:
            - now: The current timestamp in seconds.
        """
        self.state = COUNTDOWN_BG
        self.phase_start = now
        self._bg_sum = None
        self._bg_n = 0
        self.bg_gray = None
        self._samples = []
        self._blob_sizes = []

    def cancel(self) -> None:
        """Abort the current run and return to the idle state."""
        self.state = IDLE

    # -- per-frame driver ---------------------------------------------------
    def update(self, frame: np.ndarray, now: float) -> dict | None:
        """Advance the state machine by one frame.

        Parameters:
            - frame: The current BGR frame.
            - now: The current timestamp in seconds.

        Returns:
            - An info dict for the overlay (text/progress/done/result), or None
              when idle.
        """
        elapsed = now - self.phase_start

        if self.state == COUNTDOWN_BG:
            if elapsed >= self.countdown:
                self._enter(CAPTURE_BG, now)
            return self._info(f"Turn the wand light OFF   {self._count_in(elapsed)}")

        if self.state == CAPTURE_BG:
            self._accum_bg(frame)
            if elapsed >= self.bg_secs:
                self._finish_bg()
                self._enter(COUNTDOWN_FG, now)
            return self._info("Learning the background... hold still",
                              progress=elapsed / self.bg_secs)

        if self.state == COUNTDOWN_FG:
            if elapsed >= self.countdown:
                self._enter(CAPTURE_FG, now)
            return self._info(f"Turn light ON - draw big circles   "
                              f"{self._count_in(elapsed)}")

        if self.state == CAPTURE_FG:
            self._accum_fg(frame)
            if elapsed >= self.fg_secs:
                result = self._compute()
                self.state = IDLE
                return self._info("done", done=True, result=result, progress=1.0)
            return self._info(f"Keep circling the lit tip!  ({self._n_samples()} px)",
                              progress=elapsed / self.fg_secs)

        return None

    # -- helpers ------------------------------------------------------------
    def _enter(self, state: str, now: float) -> None:
        """Transition to a new phase and reset its start time.

        Parameters:
            - state: The phase constant to enter.
            - now: The current timestamp in seconds.
        """
        self.state = state
        self.phase_start = now

    def _count_in(self, elapsed: float) -> int:
        """Countdown number to show for the current phase.

        Parameters:
            - elapsed: Seconds elapsed in the current phase.

        Returns:
            - The remaining whole-second count (at least 1).
        """
        return max(1, int(self.countdown - elapsed) + 1)

    def _info(self, text: str, done: bool = False, result: dict | None = None,
              progress: float | None = None) -> dict:
        """Build the overlay info dict returned each frame.

        Parameters:
            - text: The status text to display.
            - done: True on the final frame of a successful run (default False).
            - result: The computed gate result when done (default None).
            - progress: Phase progress in [0, 1], if applicable (default None).

        Returns:
            - The assembled info dict.
        """
        return {"text": text, "done": done, "result": result,
                "progress": progress}

    def _gray(self, frame: np.ndarray) -> np.ndarray:
        """Convert a frame to a blurred grayscale image.

        Parameters:
            - frame: A BGR frame.

        Returns:
            - The blurred single-channel grayscale image.
        """
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(g, (5, 5), 0)

    def _accum_bg(self, frame: np.ndarray) -> None:
        """Accumulate one frame into the running background average.

        Parameters:
            - frame: A light-off BGR frame.
        """
        g = self._gray(frame).astype(np.float64)
        if self._bg_sum is None:
            self._bg_sum = g
            self._bg_n = 1
        else:
            self._bg_sum += g
            self._bg_n += 1

    def _finish_bg(self) -> None:
        """Finalise the averaged background into ``bg_gray``."""
        self.bg_gray = (self._bg_sum / max(1, self._bg_n)).astype(np.uint8)

    def _accum_fg(self, frame: np.ndarray) -> None:
        """Collect lit-tip HSV samples from one light-on frame.

        Keeps only small changed-and-brighter blobs (the tape tip) so the
        sweeping wand body and UV-lit background don't contaminate the sample.

        Parameters:
            - frame: A light-on BGR frame.
        """
        if self.bg_gray is None:
            return
        g = self._gray(frame)
        diff = cv2.absdiff(g, self.bg_gray)
        mask = (diff > self.change_delta) & (g > self.min_value)
        if not mask.any():
            return

        # Segment changed pixels into blobs (with tracker-equivalent morphology).
        # Only keep SMALL blobs: the tape tip is a tiny spot, but the wand body
        # sweeping across the UV-lit background produces large changed regions that
        # would contaminate the colour sample with pink/purple background pixels.
        m8 = mask.astype(np.uint8) * 255
        m8 = cv2.morphologyEx(m8, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        n_cc, labels_cc, cc_stats, _ = cv2.connectedComponentsWithStats(m8, 8)
        tip_mask = np.zeros_like(m8)
        for lbl in range(1, n_cc):
            area = int(cc_stats[lbl, cv2.CC_STAT_AREA])
            if 5 <= area <= 800:    # discard large wand-body-sweep blobs
                tip_mask[labels_cc == lbl] = 255
                self._blob_sizes.append(area)

        if not tip_mask.any():
            return

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        pix = hsv[tip_mask > 0]
        if len(pix) > 1500:               # cap memory; sample a subset per frame
            idx = self._rng.choice(len(pix), 1500, replace=False)
            pix = pix[idx]
        self._samples.append(pix)

    def _n_samples(self) -> int:
        """Total number of LED pixels collected so far.

        Returns:
            - The running count of sampled pixels across all frames.
        """
        return sum(len(s) for s in self._samples)

    def _compute(self) -> dict | None:
        """Turn collected LED pixels into an HSV gate + blob size limits.

        Returns:
            - A result dict with "lower"/"upper" HSV bounds, sample count, and
              blob size limits, or None if too few pixels were collected.
        """
        if not self._samples:
            return None
        s = np.concatenate(self._samples, axis=0).astype(np.int32)
        if len(s) < 50:
            return None

        # --- blob size limits -------------------------------------------
        blob_min = blob_max = blob_median = None
        if self._blob_sizes:
            sizes = np.array(self._blob_sizes, dtype=np.int32)
            blob_median = int(np.median(sizes))
            p5  = int(np.percentile(sizes,  5))
            p95 = int(np.percentile(sizes, 95))
            # Give 40% below the smallest observed and 2.5× above the largest,
            # so the wand can move a bit closer or farther without dropping out,
            # while still rejecting large false positives.
            blob_min = max(5, int(p5 * 0.4))
            blob_max = max(blob_min + 20, int(p95 * 2.5))

        # --- HSV gate ---------------------------------------------------
        low_s_ratio = float((s[:, 1] <= 50).mean())
        if low_s_ratio > 0.4:
            # Blown-out / near-white emitter: hue is meaningless (S≈0).
            v_lo = int(max(180, np.percentile(s[:, 2], 10) - 20))
            return {"lower": (0, 0, v_lo), "upper": (179, 60, 255),
                    "n": int(len(s)),
                    "blob_min": blob_min, "blob_max": blob_max,
                    "blob_median": blob_median}

        coloured = s[s[:, 1] >= 25]       # ignore near-white core for hue
        hue_src = coloured if len(coloured) >= 50 else s
        hue = hue_src[:, 0]
        h_lo = int(np.percentile(hue, 5))
        h_hi = int(np.percentile(hue, 95))
        if h_hi - h_lo > 90:              # implausibly wide -> fall back to median
            hm = int(np.median(hue))
            h_lo, h_hi = hm - 12, hm + 12
        h_lo = max(0, h_lo - 4)
        h_hi = min(179, h_hi + 4)

        s_lo = int(max(30, np.percentile(s[:, 1], 10) - 25))
        v_lo = int(max(60, np.percentile(s[:, 2], 10) - 25))

        return {"lower": (h_lo, s_lo, v_lo), "upper": (h_hi, 255, 255),
                "n": int(len(s)),
                "blob_min": blob_min, "blob_max": blob_max,
                "blob_median": blob_median}


# -- profile persistence ----------------------------------------------------
def save_profile(path: str, lower: tuple[int, int, int],
                 upper: tuple[int, int, int], blob_min: int | None = None,
                 blob_max: int | None = None) -> None:
    """Write a learned HSV gate (and optional blob limits) to a JSON file.

    Parameters:
        - path: The file path to write.
        - lower: The lower HSV gate bound.
        - upper: The upper HSV gate bound.
        - blob_min: Minimum blob area to keep, if known (default None).
        - blob_max: Maximum blob area to keep, if known (default None).
    """
    data = {"lower": list(lower), "upper": list(upper)}
    if blob_min is not None:
        data["blob_min"] = int(blob_min)
    if blob_max is not None:
        data["blob_max"] = int(blob_max)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def load_profile(path: str) -> dict | None:
    """Read a saved HSV gate profile from a JSON file.

    Parameters:
        - path: The file path to read.

    Returns:
        - A dict with "lower"/"upper" tuples and "blob_min"/"blob_max", or None
          if the file is missing or unreadable.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return {
            "lower":    tuple(d["lower"]),
            "upper":    tuple(d["upper"]),
            "blob_min": d.get("blob_min"),
            "blob_max": d.get("blob_max"),
        }
    except Exception:
        return None
