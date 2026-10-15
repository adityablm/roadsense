"""
All settings for the backend live here.

Secret values (database password, API keys) are NOT written in the code.
They are read from "environment variables". On your laptop those come from
the file backend/.env (which is never uploaded to GitHub). On Render they are
typed into the Render dashboard.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent   # the "backend" folder
load_dotenv(BACKEND_DIR / ".env")                       # reads backend/.env if it exists


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# --- secrets -------------------------------------------------------------
DATABASE_URL = _get("DATABASE_URL")           # the Neon connection string
GEMINI_API_KEY = _get("GEMINI_API_KEY")       # from Google AI Studio
ADMIN_TOKEN = _get("ADMIN_TOKEN")             # a password you invent, protects admin actions

# --- model ---------------------------------------------------------------
MODEL_PATH = Path(_get("MODEL_PATH", str(BACKEND_DIR / "models" / "roadsense.onnx")))
CONF_THRESHOLD = float(_get("CONF_THRESHOLD", "0.30"))   # ignore detections less sure than 30%
ORT_THREADS = int(_get("ORT_THREADS", "1"))              # CPU threads for the model (free servers have ~1)

# --- behaviour -----------------------------------------------------------
HOTSPOT_RADIUS_M = float(_get("HOTSPOT_RADIUS_M", "20"))  # reports closer than this are the same spot
MAX_UPLOAD_MB = float(_get("MAX_UPLOAD_MB", "10"))
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-flash-latest")
# If the main model is busy (error 503) or rate-limited (429), these are tried next, in order.
GEMINI_FALLBACK_MODELS = [m.strip() for m in _get(
    "GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-2.5-flash,gemini-flash-lite-latest").split(",") if m.strip()]
CITY_AUTHORITY = _get("CITY_AUTHORITY", "The Commissioner, Municipal Corporation")
CONTACT_EMAIL = _get("CONTACT_EMAIL")          # optional, sent to OpenStreetMap's address lookup

# Which websites may call this API from a browser (comma separated).
FRONTEND_ORIGINS = [o.strip() for o in _get("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
