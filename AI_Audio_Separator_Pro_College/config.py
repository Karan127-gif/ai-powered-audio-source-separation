import os
import sys

# Version
APP_VERSION = "2.1.0"
APP_NAME = "AI Audio Separator Pro"


def resource_path(relative_name: str) -> str:
    """Return the absolute path to a bundled resource.

    When running from a PyInstaller onedir EXE, files are extracted to
    ``sys._MEIPASS``.  During normal development ``__file__`` is used.
    """
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_name)


# Detect PyInstaller bundle
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    DATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'AIAudioSeparatorPro')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = BASE_DIR

os.makedirs(DATA_DIR, exist_ok=True)

# Paths
MODEL_PATH = os.path.join(BASE_DIR, "multistem_unet_best.pth")
DATABASE_PATH = os.path.join(DATA_DIR, "audio_separator.db")
TEAM_PHOTOS_DIR = os.path.join(DATA_DIR, "team_photos")
OUTPUT_DIR = os.path.join(DATA_DIR, "separated_output")
LOG_PATH = os.path.join(DATA_DIR, "app_error.log")
AUDIO_VISUAL_PATH = os.path.join(BASE_DIR, "audio_visual.png")
ICON_PATH = resource_path("app_icon.ico")

os.makedirs(TEAM_PHOTOS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Audio Processing — MUST match training parameters in train.py
SAMPLE_RATE = 22050
N_FFT = 1024        # train.py uses n_fft=1024  (513 freq bins)
HOP_LENGTH = 256    # train.py uses hop_length=256
NUM_STEMS = 4
STEM_NAMES = ["vocals", "drums", "bass", "other"]

# Credit System
FREE_CREDITS_ON_REGISTER = 5
SINGLE_STEM_COST = 1
ALL_STEMS_COST = 2

CREDIT_PACKAGES = [
    {"credits": 10,  "price": 100, "label": "Starter",   "discount": 0},
    {"credits": 25,  "price": 240, "label": "Popular",   "discount": 4},
    {"credits": 50,  "price": 450, "label": "Pro",       "discount": 10},
    {"credits": 100, "price": 850, "label": "Best Deal", "discount": 15},
]

# Security
BCRYPT_ROUNDS = 10

# Admin defaults
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_ADMIN_EMAIL = "pashtesahil10@gmail.com"

# ── UI Colors ────────────────────────────────────────────────────────────────
# Background layers
COLOR_BG_DARK    = "#09090E"   # --bg:       Deepest background
COLOR_BG_SURFACE = "#0F0F18"   # --surface:  Sidebar / panels (near-invisible border with bg)
COLOR_BG_CARD    = "#141421"   # --card:     Cards, modals

# Borders & text  (near-invisible — depth from background layers only)
COLOR_BORDER     = "rgba(255,255,255,0.05)"  # hairline, essentially borderless
COLOR_TEXT       = "#E8E8F0"   # --text-primary
COLOR_TEXT_MUTED = "#5A5A78"   # --text-muted: Subtitles, placeholders

# Accent palette  (purple-based, professional)
COLOR_ACCENT      = "#7C5CF0"  # Primary CTA, active states
COLOR_ACCENT_SOFT = "#A78BFA"  # Hover, badges, secondary highlights
COLOR_ACCENT_DIM  = "#3D2F80"  # Subtle accent fill for backgrounds

# Status / semantic (kept soft — not aggressive)
COLOR_GREEN      = "#22C55E"   # --green: Success
COLOR_CYAN       = "#6366F1"   # --indigo: AI features (harmonises with purple)
COLOR_CORAL      = "#EF4444"   # --red:   Error only (used sparingly)
COLOR_AMBER      = "#A78BFA"   # remapped → soft purple (was yellow — too aggressive)
COLOR_ORANGE     = "#7C5CF0"   # remapped → primary accent (was orange — too aggressive)
