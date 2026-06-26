"""
Wand spell-casting station -- core engine.

Run with:   python main.py

Keys
  q            quit
  m            toggle the detection "mask" view (use it to tune detection)
  l            (colour mode) LEARN the tip colour: follow the on-screen steps
               (light OFF to learn background, then light ON and circle the wand)
  p            (colour mode) hover the mouse over the lit tip and press to
               auto-sample its colour into the HSV gate
  [ / ]        (brightness mode) lower / raise the brightness threshold
  c            clear the current trail
  r            record a sample: type the spell key in the console, then draw it
  t            toggle MOUSE TEST mode (draw spells with the mouse, no camera)
  h            toggle the on-screen help / spell list
  space        toggle PRESENTATION mode (themed background, no dev text)
  f            toggle fullscreen
"""
import time
from typing import Any

import cv2
import numpy as np

from . import calibrate, config, hud, spellbook
from .camera import Camera
from .dollar import Recognizer
from .effects import EffectController
from .tracker import GestureCapture, WandTracker

WINDOW = "Spell Casting Station"
_MAX_DEAD_FRAMES = 60   # consecutive empty reads before we give up on the camera


class App:
    """
    The wand spell-casting application: camera, tracking, UI, and effects.

    Wires together the tracker, gesture capture, recogniser, and effect
    controller from config, then runs the OpenCV capture/render/input loop.
    """

    def __init__(self) -> None:
        self.tracker = WandTracker(
            mode=config.TRACK_MODE,
            threshold=config.BRIGHTNESS_THRESHOLD,
            blur=config.BLUR_KERNEL,
            min_area=config.MIN_BLOB_AREA,
            max_area=config.MAX_BLOB_AREA,
            min_aspect=config.MIN_BLOB_ASPECT,
            hsv_lower=config.HSV_LOWER,
            hsv_upper=config.HSV_UPPER,
            motion_gate=config.TRACK_MOTION_GATE,
            border_crop=config.BORDER_CROP,
        )
        self.gesture = GestureCapture(
            end_pause=config.GESTURE_END_PAUSE,
            min_points=config.GESTURE_MIN_POINTS,
            min_path=config.GESTURE_MIN_PATH,
            min_step=config.GESTURE_MIN_STEP,
            max_duration=config.GESTURE_MAX_DURATION,
        )
        self.recognizer = Recognizer(
            rotation_tolerant=config.RECOGNIZER_ROTATION_TOLERANT)
        self.recorded = spellbook.load_templates(
            self.recognizer, config.TEMPLATES_FILE)
        self.effects = EffectController(use_gpio=config.USE_GPIO)

        # Colour training and any previously-learned tip colour.
        self.swatch_color = None   # BGR of the last trained/sampled tip colour
        self.calibrator = calibrate.ColorCalibrator()
        self.cal_info = None
        if config.TRACK_MODE == "color":
            profile = calibrate.load_profile(config.COLOR_PROFILE_FILE)
            if profile:
                self.tracker.hsv_lower = np.array(profile["lower"], np.uint8)
                self.tracker.hsv_upper = np.array(profile["upper"], np.uint8)
                print(f"[main] loaded colour profile "
                      f"{profile['lower']}..{profile['upper']}")
                if profile.get("blob_min") and profile.get("blob_max"):
                    self.tracker.min_area = profile["blob_min"]
                    self.tracker.max_area = profile["blob_max"]
                    print(f"[main] loaded blob size limits "
                          f"{profile['blob_min']}..{profile['blob_max']}px")
            self.swatch_color = hud.swatch_color(
                self.tracker.hsv_lower, self.tracker.hsv_upper)

        self.camera = None
        self.current_frame = None
        self.show_mask = False
        self.show_help = True
        self.test_mode = False
        self.presentation = config.PRESENTATION_MODE   # themed bg, no dev text
        self.fullscreen = config.FULLSCREEN
        self.background = hud.load_background(
            config.BACKGROUND_IMAGE, (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT))
        self.recording = False          # in-window record mode (toggle with 'r')
        self.record_target = 0          # index into spellbook.SPELLS being recorded
        self.banner = None              # (text, color, expire_time)
        self.last_trail = []            # keep last stroke visible briefly
        self.last_trail_until = 0.0
        self.mouse: dict[str, Any] = {"pos": None, "down": False}
        self._fps = 0.0
        self._fps_t = time.time()
        self._fps_n = 0
        self._dead_frames = 0

    @property
    def record_key(self) -> str | None:
        """
        The spell key currently being recorded, or None when not recording.

        Returns:
            - The target spell's key while in record mode, else None.
        """
        if self.recording:
            return spellbook.SPELLS[self.record_target]["key"]
        return None

    def _window_size(self) -> tuple[int, int]:
        """
        Current OpenCV window image size in screen pixels.

        Returns:
            - The (width, height) of the window, falling back to the configured
              display size if it can't be queried.
        """
        try:
            _, _, ww, wh = cv2.getWindowImageRect(WINDOW)
        except Exception:
            ww, wh = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT
        if ww <= 0 or wh <= 0:
            ww, wh = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT
        return ww, wh

    def _apply_fullscreen(self) -> None:
        """Apply the current fullscreen flag to the OpenCV window."""
        cv2.setWindowProperty(
            WINDOW, cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN if self.fullscreen else cv2.WINDOW_NORMAL)

    # -- input sources ------------------------------------------------------
    def _on_mouse(self, event: int, x: int, y: int, flags: int,
                  _param: object) -> None:
        """
        OpenCV mouse callback tracking button state and cursor position.

        Parameters:
            - event: The OpenCV mouse event code.
            - x: Cursor x in screen pixels.
            - y: Cursor y in screen pixels.
            - flags: OpenCV event flags (unused).
            - _param: Unused callback userdata.
        """
        if event == cv2.EVENT_LBUTTONDOWN:
            self.mouse["down"] = True
        elif event == cv2.EVENT_LBUTTONUP:
            self.mouse["down"] = False
        self.mouse["pos"] = (x, y)

    def _get_tip(self, frame: np.ndarray,
                 now: float) -> tuple[float, float] | None:
        """
        Get the tip position from the mouse (test mode) or the tracker.

        Parameters:
            - frame: The current frame, used for display→frame scaling.
            - now: The current timestamp in seconds (unused; kept for symmetry).

        Returns:
            - The (x, y) tip in frame coordinates, or None if not available.
        """
        if self.test_mode:
            if self.mouse["down"] and self.mouse["pos"] is not None:
                # Mouse callback gives display coords; gesture needs frame coords.
                sx = config.DISPLAY_WIDTH / frame.shape[1]
                sy = config.DISPLAY_HEIGHT / frame.shape[0]
                mx, my = self.mouse["pos"]
                return (mx / sx, my / sy)
            return None
        return self.tracker.find_tip(frame)

    # -- main loop ----------------------------------------------------------
    def run(self) -> None:
        """Open the camera and run the capture/render/input loop until quit."""
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW, self._on_mouse)
        self._apply_fullscreen()
        try:
            self.camera = Camera(
                width=config.FRAME_WIDTH, height=config.FRAME_HEIGHT,
                fps=config.TARGET_FPS, prefer_picamera=config.PREFER_PICAMERA,
                camera_index=config.CAMERA_INDEX,
                probe_count=config.CAMERA_PROBE_COUNT,
                swap_rb=config.SWAP_RB, lock_camera=config.LOCK_CAMERA)
            print(f"[main] camera backend: {self.camera.backend}")
        except Exception as exc:
            bar = "=" * 64
            print(f"\n{bar}\n  CAMERA ERROR: {exc}\n{bar}")
            if config.REQUIRE_CAMERA:
                raise SystemExit(1) from exc
            print("  -> no camera; falling back to MOUSE TEST MODE "
                  "(hold the left mouse button and draw)\n")
            self.test_mode = True

        while True:
            now = time.time()
            if self.test_mode or self.camera is None:
                frame = np.zeros((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3),
                                 np.uint8)
            else:
                frame = self.camera.read()
                if frame is None:
                    # Camera hiccup or disconnect: keep the window responsive so
                    # 'q' still quits, and give up if it persists.
                    self._dead_frames += 1
                    if self._dead_frames > _MAX_DEAD_FRAMES:
                        print("[main] camera stopped returning frames; exiting")
                        break
                    if not self._handle_keys(cv2.waitKey(1) & 0xFF):
                        break
                    continue
                self._dead_frames = 0
                if config.MIRROR_PREVIEW:
                    frame = cv2.flip(frame, 1)

            self.current_frame = frame

            if self.calibrator.active:
                self.cal_info = self.calibrator.update(frame, now)
                if self.cal_info and self.cal_info.get("done"):
                    self._apply_calibration(self.cal_info.get("result"), now)
                tip = None
            else:
                self.cal_info = None
                tip = self._get_tip(frame, now)
                stroke = self.gesture.update(tip, now)
                if stroke:
                    self._handle_stroke(stroke, now)
                elif self.recording and self.gesture.dropped:
                    n_pts, path = self.gesture.dropped
                    self.banner = (f"too short ({n_pts} pts / {path:.0f}px) - "
                                   "draw bigger, then pause to save",
                                   (80, 140, 255), now + 1.5)
                self.gesture.dropped = None

            display = self._render(frame, tip, now)
            cv2.imshow(WINDOW, display)

            if not self._handle_keys(cv2.waitKey(1) & 0xFF):
                break

        self._shutdown()

    def _handle_stroke(self, stroke: list[tuple[float, float]],
                       now: float) -> None:
        """
        Record or recognise a completed stroke and set the feedback banner.

        Parameters:
            - stroke: The completed gesture as an ordered list of points.
            - now: The current timestamp in seconds.
        """
        self.last_trail = stroke
        self.last_trail_until = now + 1.5

        if self.recording:
            # In record mode every stroke saves a sample for the selected spell;
            # recognition and effects are suppressed until you press 'r'.
            key = spellbook.SPELLS[self.record_target]["key"]
            spellbook.save_sample(config.TEMPLATES_FILE, self.recorded, key, stroke)
            self.recognizer.add_template(key, stroke)
            count = len(self.recorded.get(key, []))
            self.banner = (f"REC {key}: {count} saved", (120, 255, 120), now + 2.0)
            return

        name, score = self.recognizer.recognize(stroke)
        if name and score >= config.MIN_SCORE:
            spell = spellbook.get(name)
            assert spell is not None
            self.effects.trigger(spell)
            self.banner = (f"{spell['name']}  ({score:.2f})",
                           (80, 220, 255), now + 1.8)
        else:
            shown = f"{score:.2f}" if name else "--"
            self.banner = (f"no spell ({shown})", (120, 120, 120), now + 1.0)

    # -- rendering ----------------------------------------------------------
    def _render(self, frame: np.ndarray, tip: tuple[float, float] | None,
                now: float) -> np.ndarray:
        """
        Compose the display canvas: backdrop, trail, markers, and overlays.

        Parameters:
            - frame: The current camera frame.
            - tip: The current tip position, or None.
            - now: The current timestamp in seconds.

        Returns:
            - The rendered display-resolution canvas.
        """
        # Always render at display resolution so text is legible fullscreen
        # regardless of presentation mode.
        disp_w, disp_h = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT
        sx = disp_w / frame.shape[1]
        sy = disp_h / frame.shape[0]

        if self.show_mask and not self.test_mode and self.tracker.last_mask is not None:
            canvas = cv2.cvtColor(self.tracker.last_mask, cv2.COLOR_GRAY2BGR)
            canvas = cv2.resize(canvas, (disp_w, disp_h),
                                interpolation=cv2.INTER_NEAREST)
        elif self.presentation:
            canvas = self.background.copy()   # themed backdrop, not the camera
        else:
            canvas = cv2.resize(frame, (disp_w, disp_h),
                                interpolation=cv2.INTER_LINEAR)

        # live trail, or the just-finished one for a moment
        if self.gesture.active and len(self.gesture.points) > 1:
            hud.draw_trail(canvas, self.gesture.points, sx, sy)
        elif now < self.last_trail_until and len(self.last_trail) > 1:
            hud.draw_trail(canvas, self.last_trail, sx, sy)

        # tip marker -- show in dev mode at scaled position
        if tip is not None and not self.presentation:
            cv2.circle(canvas, (int(tip[0] * sx), int(tip[1] * sy)),
                       12, (0, 255, 255), 2)

        self._update_fps(now)
        hud.draw_banner(canvas, self.banner, now)   # spell feedback: always shown
        if not self.presentation:
            ww, wh = self._window_size()
            hud.draw_chrome(canvas, self.tracker, test_mode=self.test_mode,
                            record_key=self.record_key, fps=self._fps,
                            show_help=self.show_help)        # status + help
            hud.draw_reticle(canvas, self.mouse["pos"], self.tracker,
                             self.current_frame, ww, wh)     # 'p' targeting
            hud.draw_swatch(canvas, self.swatch_color)       # trained colour block
        if self.cal_info:
            hud.draw_calibration(canvas, self.cal_info)
        if self.recording:
            key = spellbook.SPELLS[self.record_target]["key"]
            hud.draw_record_overlay(canvas, key, len(self.recorded.get(key, [])))
        return canvas

    def _update_fps(self, now: float) -> None:
        """
        Update the rolling FPS estimate.

        Parameters:
            - now: The current timestamp in seconds.
        """
        self._fps_n += 1
        if now - self._fps_t >= 0.5:
            self._fps = self._fps_n / (now - self._fps_t)
            self._fps_t, self._fps_n = now, 0

    # -- keyboard -----------------------------------------------------------
    def _handle_keys(self, key: int) -> bool:
        """
        Dispatch a single keypress to its action.

        Parameters:
            - key: The key code from cv2.waitKey (masked to 8 bits).

        Returns:
            - False if the app should quit, True to keep running.
        """
        if key in (ord("q"), 27):
            return False
        elif key == ord("m"):
            self.show_mask = not self.show_mask
        elif key == ord("h"):
            self.show_help = not self.show_help
        elif key == ord(" "):
            self.presentation = not self.presentation
            print(f"[main] presentation mode: {self.presentation}")
        elif key == ord("f"):
            self.fullscreen = not self.fullscreen
            self._apply_fullscreen()
        elif key == ord("t"):
            self.test_mode = not self.test_mode
            print(f"[main] mouse test mode: {self.test_mode}")
        elif key == ord("c"):
            self.gesture.points = []
            self.gesture.active = False
            self.last_trail = []
        elif key == ord("["):
            if self.recording:
                self.record_target = (self.record_target - 1) % len(spellbook.SPELLS)
            else:
                self._nudge_floor(-5)
        elif key == ord("]"):
            if self.recording:
                self.record_target = (self.record_target + 1) % len(spellbook.SPELLS)
            else:
                self._nudge_floor(+5)
        elif key == ord("r"):
            self.recording = not self.recording
            tgt = spellbook.SPELLS[self.record_target]["key"]
            if self.recording:
                print(f"[record] recording '{tgt}' — draw to add samples; "
                      "[ / ] change spell; r to stop")
            else:
                print(f"[record] stopped ('{tgt}')")
        elif key == ord("p"):
            self._sample_color()
        elif key == ord("g"):
            on = self.tracker.toggle_motion()
            print(f"[tune] motion gate: {'on' if on else 'off'}")
        elif key == ord("b"):
            self.tracker.mode = ("brightness" if self.tracker.mode == "color"
                                 else "color")
            print(f"[tune] tracking mode: {self.tracker.mode}")
        elif key == ord("l"):
            if self.calibrator.active:
                self.calibrator.cancel()
                print("[train] cancelled")
            elif self.tracker.mode == "color":
                self.calibrator.start(time.time())
                print("[train] colour training started -- follow the on-screen steps")
            else:
                print("[train] switch TRACK_MODE to 'color' to train a colour")
        return True

    def _apply_calibration(self, result: dict | None, now: float) -> None:
        """
        Apply a finished colour-training result to the tracker and save it.

        Parameters:
            - result: The calibrator result dict, or None if training failed.
            - now: The current timestamp in seconds.
        """
        if not result:
            self.banner = ("training failed - try again, wave more",
                           (60, 60, 255), now + 2.5)
            print("[train] not enough LED pixels seen; try again with the light "
                  "ON and bigger circles")
            return
        lo, hi = result["lower"], result["upper"]
        self.tracker.hsv_lower = np.array(lo, np.uint8)
        self.tracker.hsv_upper = np.array(hi, np.uint8)

        blob_min = result.get("blob_min")
        blob_max = result.get("blob_max")
        blob_med = result.get("blob_median")
        if blob_min and blob_max:
            self.tracker.min_area = blob_min
            self.tracker.max_area = blob_max

        calibrate.save_profile(config.COLOR_PROFILE_FILE, lo, hi, blob_min, blob_max)
        self.swatch_color = hud.swatch_color(
            self.tracker.hsv_lower, self.tracker.hsv_upper)

        print(f"[train] HSV gate : {lo}  ..  {hi}  ({result['n']} px)")
        if blob_min and blob_max:
            print(f"[train] blob size: median={blob_med}px  "
                  f"range={blob_min}..{blob_max}px")
            print(f"[train] → config.py: "
                  f"MIN_BLOB_AREA = {blob_min}  "
                  f"MAX_BLOB_AREA = {blob_max}")
        print(f"[train] saved to {config.COLOR_PROFILE_FILE}")

        self.banner = (f"learned colour + size!  {blob_med}px median",
                       (120, 255, 120), now + 2.5)

    def _nudge_floor(self, delta: int) -> None:
        """
        In colour mode adjust the brightness (V) floor; else the threshold.

        Raising the V floor is the quickest way to drop a passively-lit
        background (a shirt) while keeping the bright wand tip.

        Parameters:
            - delta: The amount to add to the floor/threshold (may be negative).
        """
        if self.tracker.mode == "color":
            new_v = int(self.tracker.hsv_lower[2]) + delta
            new_v = max(0, min(254, new_v))
            self.tracker.hsv_lower[2] = new_v
            print(f"[tune] colour brightness floor Vmin={new_v}")
        else:
            self.tracker.threshold = max(0, min(255, self.tracker.threshold + delta))

    def _display_to_frame(self, dx: int, dy: int) -> tuple[int, int]:
        """
        Convert OpenCV mouse (screen) coords to frame pixel coords.

        Mouse callback returns screen-space pixels.  The canvas (1920x1080) is
        scaled by OpenCV to fill whatever the actual window size is, so we must
        map through the real window rect rather than assuming the canvas fills
        the screen 1:1.

        Parameters:
            - dx: Cursor x in screen pixels.
            - dy: Cursor y in screen pixels.

        Returns:
            - The (x, y) position clamped to frame pixel coordinates.
        """
        frame = self.current_frame
        if frame is None:
            return 0, 0
        fh, fw = frame.shape[:2]
        ww, wh = self._window_size()
        # screen → canvas → frame
        cx = dx * config.DISPLAY_WIDTH  / ww
        cy = dy * config.DISPLAY_HEIGHT / wh
        fx = int(cx * fw / config.DISPLAY_WIDTH)
        fy = int(cy * fh / config.DISPLAY_HEIGHT)
        return int(np.clip(fx, 0, fw - 1)), int(np.clip(fy, 0, fh - 1))

    def _sample_color(self) -> None:
        """Sample tip colour + blob size under the reticle (colour mode only)."""
        if self.tracker.mode != "color":
            print("[calibrate] switch TRACK_MODE to 'color' to sample a colour")
            return
        pos = self.mouse["pos"]
        if pos is None or self.current_frame is None:
            print("[calibrate] move the reticle over the lit tip first, then press 'p'")
            return

        fx, fy = self._display_to_frame(pos[0], pos[1])

        # Diagnostic: print raw coords, window rect, and BGR at exact cursor pixel
        ww, wh = self._window_size()
        fh, fw = self.current_frame.shape[:2]
        bgr_at_cursor = self.current_frame[fy, fx]
        print(f"[p] screen=({pos[0]},{pos[1]})  window={ww}x{wh}  "
              f"frame={fw}x{fh}  →  frame=({fx},{fy})  "
              f"BGR@cursor=({int(bgr_at_cursor[0])},{int(bgr_at_cursor[1])},{int(bgr_at_cursor[2])})")

        h, s, v = self.tracker.sample_hsv(self.current_frame, fx, fy)
        loc = self.tracker.last_sample_loc
        assert loc is not None
        print(f"[calibrate] cursor=({fx},{fy})  "
              f"snapped to=({loc[0]},{loc[1]})  HSV={h},{s},{v}")
        lo = tuple(int(x) for x in self.tracker.hsv_lower)
        hi = tuple(int(x) for x in self.tracker.hsv_upper)
        self.swatch_color = hud.swatch_color(
            self.tracker.hsv_lower, self.tracker.hsv_upper)

        # Measure the blob at the sampled point through the full tracker pipeline.
        area, blob_min, blob_max = self._measure_blob_at(self.current_frame, fx, fy)
        if area is not None:
            assert blob_min is not None and blob_max is not None
            self.tracker.min_area = blob_min
            self.tracker.max_area = blob_max
            calibrate.save_profile(config.COLOR_PROFILE_FILE, lo, hi, blob_min, blob_max)
            print(f"[calibrate] HSV={h},{s},{v}  gate={lo}..{hi}")
            print(f"[calibrate] blob={area}px  → min={blob_min}  max={blob_max}")
            print(f"[calibrate] config.py: HSV_LOWER={lo}  HSV_UPPER={hi}  "
                  f"MIN_BLOB_AREA={blob_min}  MAX_BLOB_AREA={blob_max}")
            self.banner = (f"H{h} S{s} V{v}  blob={area}px  ({blob_min}..{blob_max})",
                           (200, 120, 255), time.time() + 2.5)
        else:
            calibrate.save_profile(config.COLOR_PROFILE_FILE, lo, hi)
            print(f"[calibrate] HSV={h},{s},{v}  gate={lo}..{hi}  (no blob found at reticle)")
            print(f"[calibrate] config.py: HSV_LOWER={lo}  HSV_UPPER={hi}")
            self.banner = (f"sampled H{h} S{s} V{v}  (aim reticle at tape for size)",
                           (200, 120, 255), time.time() + 2.0)

    def _measure_blob_at(self, frame: np.ndarray, fx: int, fy: int
                         ) -> tuple[int | None, int | None, int | None]:
        """
        Apply current gate + tracker morphology and measure the blob at (fx,fy).

        Parameters:
            - frame: The current BGR frame.
            - fx: Sample x in frame pixels.
            - fy: Sample y in frame pixels.

        Returns:
            - (area, min_area, max_area) with generous headroom so the wand can
              move closer/farther without dropping out, or (None, None, None) if
              no blob is found near the sampled point.
        """
        blurred = frame
        if self.tracker.blur:
            k = self.tracker.blur | 1
            blurred = cv2.GaussianBlur(frame, (k, k), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.tracker.hsv_lower, self.tracker.hsv_upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        if self.tracker.border_crop:
            c = self.tracker.border_crop
            mask[:c, :] = 0
            mask[-c:, :] = 0
            mask[:, :c] = 0
            mask[:, -c:] = 0

        n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        if n <= 1:
            return None, None, None
        h, w = mask.shape

        # Try the blob directly under the cursor first.
        lbl = int(labels[max(0, min(h-1, fy)), max(0, min(w-1, fx))])

        # Fallback: nearest centroid within 50 px of the cursor.
        if lbl == 0:
            best_d, lbl = float("inf"), 0
            for i in range(1, n):
                cx, cy = centroids[i]
                d = (cx - fx)**2 + (cy - fy)**2
                if d < best_d:
                    best_d, lbl = d, i
            if best_d > 50**2:
                return None, None, None

        area = int(stats[lbl, cv2.CC_STAT_AREA])
        # 30 % below and 5x above the observed size gives headroom for distance
        # variation while still excluding large false positives.
        blob_min = max(5, int(area * 0.30))
        blob_max = int(area * 5)
        return area, blob_min, blob_max

    def _shutdown(self) -> None:
        """Release the camera, clean up effects, and close all windows."""
        if self.camera is not None:
            self.camera.close()
        self.effects.cleanup()
        cv2.destroyAllWindows()


def main() -> None:
    """Build the app and run the capture/render/input loop (entry point)."""
    App().run()


if __name__ == "__main__":
    main()
