"""
Central configuration for the wand spell-casting station.

Everything you'll want to tune lives here so you don't have to dig through
the logic.  The two things that matter most for reliable tracking are
CAMERA + BRIGHTNESS_THRESHOLD (how bright the wand tip must be to count) and
the gesture-segmentation timings.  See README.md for the lighting trick that
makes detection easy.
"""
import os

# Folder this config (and the rest of the package) lives in.  Data files below
# are anchored here so they resolve the same no matter which directory you
# launch from.
_BASE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
FRAME_WIDTH = 640
FRAME_HEIGHT = 360       # 16:9 widescreen for tracking/camera (matches DISPLAY ratio)
TARGET_FPS = 60          # Pi 5 + camera can do this easily at this size
PREFER_PICAMERA = True   # use picamera2 if available, else fall back to a USB/webcam
MIRROR_PREVIEW = True    # flip horizontally so motion feels natural (like a mirror)
SWAP_RB = False          # set True if the preview colours look wrong (R/B swapped)
LOCK_CAMERA = True       # freeze AE/AWB after the 2-s settle so colour tracking
                         # isn't disrupted by the camera re-adjusting mid-session

# ---------------------------------------------------------------------------
# Wand-tip detection
# ---------------------------------------------------------------------------
# TRACK_MODE picks how the tip is found:
#   "color"      -- an active coloured LED at the tip (e.g. the purple-light
#                   wand).  Most reliable: visible at any wand angle, works in a
#                   normally-lit room.
#   "brightness" -- a retroreflective tip lit by a white light next to the lens.
TRACK_MODE = "color"

# -- colour mode -----------------------------------------------------------
# HSV gate for the lit tip (OpenCV HSV ranges: H 0-179, S 0-255, V 0-255).
# The wand LED is so bright it clips to near-white (S≈0, V=255) while the
# UV-lit room background stays highly saturated (S≈200).  We therefore gate
# on LOW saturation + HIGH brightness -- not hue -- to isolate the blown-out
# emitter from the purple ambient light.
# Best path: hover the mouse over the tip in the app and press 'p' to
# auto-sample these from YOUR wand.
#HSV_LOWER = (4, 35, 150)
#HSV_UPPER = (24, 255, 255)

HSV_LOWER=(0, 35, 179)
HSV_UPPER=(20, 255, 255)

# -- brightness mode -------------------------------------------------------
# Raise the threshold until ONLY the tip survives (press 'm' to see the mask,
# tune live with '[' and ']').
#BRIGHTNESS_THRESHOLD = 240   # 0-255  (wand tip ~255, purple room ~80, hotspot ~235)
BRIGHTNESS_THRESHOLD = 179   # 0-255  (wand tip ~255, purple room ~80, hotspot ~235)

# Motion gate (colour mode): also require the tip to be MOVING, which rejects
# static same-colour objects in the background.  Toggle live with 'g'.
# Needed even with the low-S gate: a fixed bright hotspot (e.g. a light near
# the lens) can still pass.  MOG2 reabsorption (~3 s) is far longer than any
# in-spell pause, so the tip is never dropped mid-gesture.
TRACK_MOTION_GATE = False

# -- shared ----------------------------------------------------------------
BLUR_KERNEL = 5              # pre-blur before colour/brightness detection.
                             # In colour mode it smooths the tape blob (good).
                             # In brightness mode it washes out sharp LED peaks (bad) -- set 0.
#MIN_BLOB_AREA = 3           # ignore specks smaller than this (pixels)
#MAX_BLOB_AREA = 50          # wand tape is tiny -- reject anything larger (lamps, shirts)
MIN_BLOB_ASPECT = 0.25       # min(w,h)/max(w,h); reject elongated smears -- the tape
                             # tip is roughly circular, wall-reflections are long/thin
BORDER_CROP = 0             # pixels to black-out on each edge before blob detection
                             # rejects fixed hotspots from lights/lens-flare at frame edges

MIN_BLOB_AREA=5
MAX_BLOB_AREA=60

# ---------------------------------------------------------------------------
# Gesture segmentation (turning a stream of tip positions into one "spell")
# ---------------------------------------------------------------------------
GESTURE_END_PAUSE = 0.45     # seconds tip must be gone/still to end a spell
GESTURE_MIN_POINTS = 12      # too few points = accidental flick, ignore
GESTURE_MIN_PATH = 70        # min total path length in px to count as a stroke
GESTURE_MIN_STEP = 4         # min px between stored points (de-jitter)
GESTURE_MAX_DURATION = 6.0   # auto-finish a spell after this many seconds

# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
MIN_SCORE = 0.75             # 0-1; below this we say "no spell recognised"
RECOGNIZER_ROTATION_TOLERANT = True  # forgive tilted drawings (good for kids)

# ---------------------------------------------------------------------------
# Presentation / display
# ---------------------------------------------------------------------------
# Presentation mode shows a themed backdrop with NO on-screen dev text (no green
# status line, no help) -- just the glowing spell trail and the cast banner.
# Toggle live with the spacebar; set True here to boot straight into it.
PRESENTATION_MODE = False
FULLSCREEN = True                     # show the window fullscreen ('f' toggles)
# Presentation is drawn at this (higher) resolution for a crisp fullscreen image,
# while the camera + tracking stay at FRAME_WIDTH/HEIGHT above -- tracking doesn't
# need the extra pixels.  Keep the SAME aspect ratio as the frame size (16:9).
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080
# Drop a Harry Potter themed image at background.png to use as the
# backdrop.  If it's missing, a procedural starry-night background is used.
# Set an absolute path to keep the image elsewhere.
BACKGROUND_IMAGE = os.path.join(_BASE, "background.png")

# ---------------------------------------------------------------------------
# Effects / hardware (wired up later)
# ---------------------------------------------------------------------------
USE_GPIO = True             # flip to True on the Pi once the relay is wired
ENABLE_SOUND = True

# Keyestudio RPi 4-channel relay shield (KS0212): channel -> BCM GPIO.
# These are the shield's fixed pins. VERIFY against the silkscreen / Keyestudio
# wiki and edit if yours differs -- run relay_test.py to confirm wiring+polarity.
RELAY_CH = {1: 4, 2: 22, 3: 6, 4: 26}

# True: driving the GPIO HIGH switches the relay ON (Keyestudio default).
# If a relay turns ON when it should be OFF (or clicks on at boot), set False.
RELAY_ACTIVE_HIGH = True

# Which relay channel each effect drives.  Lumos -> channel 1 (the "light").
PIN_LIGHT = RELAY_CH[2]
PIN_FAN = RELAY_CH[1]
PIN_ACTUATOR_EXTEND = RELAY_CH[3]
PIN_ACTUATOR_RETRACT = RELAY_CH[4]

# ---------------------------------------------------------------------------
# Kasa EP10 smart plugs  (python-kasa library)
# ---------------------------------------------------------------------------
# Set each IP to the address shown in the Kasa app (device info).
# Leave as "" to disable that plug — effects that target it will warn but not crash.
#
# Plug 1 is wired to Lumos (toggle) and Nox (off) — typically a lamp.
# Plug 2 is wired to Incendio (pulse) — typically a fog machine or accent light.
#
# DURATION: None = toggle state; float = turn ON for N seconds then OFF automatically.
KASA_PLUG_1_IP       = "192.168.54.58"      # e.g. "192.168.1.100"
KASA_PLUG_2_IP       = "192.168.54.4"      # e.g. "192.168.1.101"
KASA_PLUG_1_DURATION = None    # None = toggle; e.g. 5.0 = 5-second pulse
KASA_PLUG_2_DURATION = 3.0     # Incendio: 3-second burst on plug 2

# ---------------------------------------------------------------------------
# Apple TV  (pyatv Companion protocol)
# ---------------------------------------------------------------------------
# Pair once with:  python pair_appletv.py
# Credentials are saved to appletv_credentials.json automatically.
# Leave as "" to disable.
APPLETV_IP = "192.168.0.110"

# ---------------------------------------------------------------------------
# Files (anchored to the project root via _BASE)
# ---------------------------------------------------------------------------
TEMPLATES_FILE = os.path.join(_BASE, "templates.json")        # recorded spell samples
COLOR_PROFILE_FILE = os.path.join(_BASE, "color_profile.json")  # learned tip colour ('l')
