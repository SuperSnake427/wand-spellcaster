"""
Camera abstraction.

Uses the Raspberry Pi camera stack (picamera2) when available, and otherwise
falls back to any OpenCV-readable camera (USB webcam / laptop).  That means you
can develop and test the whole pipeline on a Windows/Mac laptop, then run the
exact same code on the Pi 5 with the NoIR module -- no code changes needed.
"""
import sys
import time
from typing import Any

import cv2
import numpy as np

try:
    from picamera2 import Picamera2
    _HAS_PICAMERA = True
except Exception:
    _HAS_PICAMERA = False


class Camera:
    """
    A picamera2-or-OpenCV camera presenting a single ``read()`` interface.

    Picks the Raspberry Pi camera stack (picamera2) when available, otherwise
    falls back to an OpenCV-readable device so the same code runs on a laptop
    or on the Pi.

    Parameters:
        - width: Requested capture width in pixels (default 640). A webcam may
          ignore this; a warning is logged if the actual size differs.
        - height: Requested capture height in pixels (default 480).
        - fps: Requested frame rate (default 60).
        - prefer_picamera: Use picamera2 when it is importable (default True).
        - swap_rb: Swap the red/blue channels of picamera2 frames if the colours
          look wrong (default False).
        - lock_camera: Freeze AE/AWB after a 2-second settle (picamera2 only) so
          colour tracking is not disrupted by mid-session re-adjustment
          (default True).
    """

    def __init__(self, width: int = 640, height: int = 480, fps: int = 60,
                 prefer_picamera: bool = True, swap_rb: bool = False,
                 lock_camera: bool = True) -> None:
        self.width = width
        self.height = height
        self.swap_rb = swap_rb
        self._picam: Any = None
        self._cap: Any = None

        if _HAS_PICAMERA and prefer_picamera:
            self._picam = Picamera2()
            cfg = self._picam.create_preview_configuration(
                main={"format": "RGB888", "size": (width, height)},
            )
            self._picam.configure(cfg)
            try:
                self._picam.set_controls({"FrameRate": float(fps)})
            except Exception:
                pass
            self._picam.start()
            # Let AE/AWB converge on the actual scene before (optionally) locking.
            # 2 s is enough for picamera2's default convergence loop.
            time.sleep(2.0)
            if lock_camera:
                self._lock_picam()
            self.backend = "picamera2"
        else:
            # DirectShow opens faster and more reliably than MSMF on Windows.
            if sys.platform.startswith("win"):
                self._cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            else:
                self._cap = cv2.VideoCapture(0)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self._cap.set(cv2.CAP_PROP_FPS, fps)
            self.backend = "opencv"
            # Webcams often ignore the requested resolution; log what we got.
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if (actual_w, actual_h) != (width, height):
                print(f"[camera] WARNING: requested {width}x{height} "
                      f"but got {actual_w}x{actual_h} — "
                      f"update FRAME_WIDTH/HEIGHT in config.py to match")
            else:
                print(f"[camera] {actual_w}x{actual_h} @ {fps}fps")

    def _lock_picam(self) -> None:
        """
        Freeze AE/AWB at their current settled values.

        Auto-exposure and auto-white-balance drift as the scene changes
        (waving the wand, moving people) and shift the HSV values the
        colour gate uses.  Locking once after the initial settle prevents
        that drift without sacrificing a good starting exposure.
        """
        try:
            meta = self._picam.capture_metadata()
            gain = float(meta.get("AnalogueGain", 1.0))
            exp = int(meta.get("ExposureTime", 16667))
            gains = meta.get("ColourGains", (2.0, 1.5))
            self._picam.set_controls({
                "AeEnable": False,
                "AwbEnable": False,
                "AnalogueGain": gain,
                "ExposureTime": exp,
                "ColourGains": (float(gains[0]), float(gains[1])),
            })
            print(f"[camera] AE/AWB locked — gain={gain:.2f} "
                  f"exp={exp}µs wb=({gains[0]:.2f},{gains[1]:.2f})")
        except Exception as exc:
            print(f"[camera] warning: could not lock AE/AWB: {exc}")

    def read(self) -> np.ndarray | None:
        """
        Capture one frame.

        Returns:
            - One BGR frame as a numpy array, or None if the capture failed.
        """
        if self._picam is not None:
            frame = self._picam.capture_array()  # picamera2 "RGB888" -> BGR-ordered
            if self.swap_rb:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return frame
        ok, frame = self._cap.read()
        if not ok:
            return None
        return frame

    def close(self) -> None:
        """Release the underlying camera backend."""
        if self._picam is not None:
            self._picam.stop()
            self._picam.close()
        if self._cap is not None:
            self._cap.release()
