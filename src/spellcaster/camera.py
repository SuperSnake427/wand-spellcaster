"""
Camera abstraction.

Uses the Raspberry Pi camera stack (picamera2) when available, and otherwise
falls back to any OpenCV-readable camera (USB webcam / laptop).  That means you
can develop and test the whole pipeline on a Windows/Mac laptop, then run the
exact same code on the Pi 5 with the NoIR module -- no code changes needed.

If the requested camera can't be opened, the Camera raises CameraError with a
list of the cameras it CAN find, so a multi-camera setup can pick the right one
via CAMERA_INDEX in config.py rather than silently grabbing the wrong feed.
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


class CameraError(RuntimeError):
    """Raised when the requested camera cannot be opened."""


def _opencv_backend() -> int:
    """
    OpenCV capture backend for this platform.

    Returns:
        - cv2.CAP_DSHOW on Windows (opens faster/more reliably than MSMF),
          cv2.CAP_ANY elsewhere.
    """
    return cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY


def available_opencv_cameras(count: int = 8) -> list[int]:
    """
    Probe OpenCV device indices and return the ones that open.

    Parameters:
        - count: How many indices (0..count-1) to probe.

    Returns:
        - The sorted list of device indices that opened successfully.
    """
    found: list[int] = []
    for i in range(count):
        cap = cv2.VideoCapture(i, _opencv_backend())
        try:
            if cap.isOpened():
                found.append(i)
        finally:
            cap.release()
    return found


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
        - camera_index: Which camera to open -- an OpenCV device index or a
          picamera2 camera number (default 0).
        - probe_count: How many OpenCV indices to probe when listing the
          available cameras after a failure (default 8).
        - swap_rb: Swap the red/blue channels of picamera2 frames if the colours
          look wrong (default False).
        - lock_camera: Freeze AE/AWB after a 2-second settle (picamera2 only) so
          colour tracking is not disrupted by mid-session re-adjustment
          (default True).

    Raises:
        - CameraError: If the requested camera cannot be opened. The message
          lists the cameras that ARE available (or states none were found).
    """

    def __init__(self, width: int = 640, height: int = 480, fps: int = 60,
                 prefer_picamera: bool = True, camera_index: int = 0,
                 probe_count: int = 8, swap_rb: bool = False,
                 lock_camera: bool = True) -> None:
        self.width = width
        self.height = height
        self.swap_rb = swap_rb
        self.backend = ""
        self._picam: Any = None
        self._cap: Any = None

        if _HAS_PICAMERA and prefer_picamera:
            self._open_picamera(width, height, fps, camera_index, lock_camera)
        else:
            self._open_opencv(width, height, fps, camera_index, probe_count)

    # -- backends -----------------------------------------------------------
    def _open_picamera(self, width: int, height: int, fps: int,
                       camera_index: int, lock_camera: bool) -> None:
        """
        Open the requested picamera2 camera, validating it exists first.

        Parameters:
            - width, height: Requested capture size in pixels.
            - fps: Requested frame rate.
            - camera_index: The picamera2 camera number to open.
            - lock_camera: Whether to freeze AE/AWB after the settle.

        Raises:
            - CameraError: If no camera is present or the index is out of range.
        """
        infos = Picamera2.global_camera_info()
        if not infos:
            raise CameraError(
                "no camera found (picamera2). Check the ribbon / USB connection.")
        if camera_index >= len(infos):
            listing = ", ".join(
                f"{i}: {c.get('Model', '?')}" for i, c in enumerate(infos))
            raise CameraError(
                f"picamera2 camera #{camera_index} not available. "
                f"Cameras found: [{listing}]. Set CAMERA_INDEX in config.py.")

        self._picam = Picamera2(camera_index)
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
        print(f"[camera] picamera2 #{camera_index} "
              f"({infos[camera_index].get('Model', '?')})")

    def _open_opencv(self, width: int, height: int, fps: int,
                     camera_index: int, probe_count: int) -> None:
        """
        Open the requested OpenCV camera, failing clearly if it cannot.

        Parameters:
            - width, height: Requested capture size in pixels.
            - fps: Requested frame rate.
            - camera_index: The OpenCV device index to open.
            - probe_count: How many indices to probe when listing alternatives.

        Raises:
            - CameraError: If the index won't open. The message lists the
              indices that DID open, or states none were found.
        """
        self._cap = cv2.VideoCapture(camera_index, _opencv_backend())
        if not self._cap.isOpened():
            self._cap.release()
            self._cap = None
            available = available_opencv_cameras(probe_count)
            if available:
                raise CameraError(
                    f"camera index {camera_index} could not be opened. "
                    f"Available camera indices: {available}. "
                    f"Set CAMERA_INDEX in config.py to one of these.")
            raise CameraError(
                "no camera found (OpenCV). Plug a webcam in, set a different "
                "CAMERA_INDEX in config.py, or run in mouse-test mode.")

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        self.backend = "opencv"
        # Webcams often ignore the requested resolution; log what we got.
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (actual_w, actual_h) != (width, height):
            print(f"[camera] OpenCV index {camera_index}: WARNING requested "
                  f"{width}x{height} but got {actual_w}x{actual_h} — "
                  f"update FRAME_WIDTH/HEIGHT in config.py to match")
        else:
            print(f"[camera] OpenCV index {camera_index}: "
                  f"{actual_w}x{actual_h} @ {fps}fps")

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
