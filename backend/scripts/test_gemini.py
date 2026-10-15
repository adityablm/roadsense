"""
Checks that your Gemini API key works, before we build on it.

Run from the backend folder:
    python scripts/test_gemini.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, llm  # noqa: E402

if not config.GEMINI_API_KEY:
    sys.exit("GEMINI_API_KEY is empty. Open backend/.env and paste your key after GEMINI_API_KEY=")

client = llm._get_client()

print("1) Listing the Flash models your key can use ...")
try:
    names = [m.name for m in client.models.list() if "flash" in (m.name or "")]
    for name in names[:12]:
        print("   ", name)
except Exception as exc:
    sys.exit(f"   FAILED: {exc.__class__.__name__}: {exc}\n"
             "   -> Send this message to Claude.")

print("\n2) Asking a test question. Models tried in this order, if one is busy:")
print("   ", " -> ".join(llm.models_to_try()))
try:
    text, model = llm.generate(
        "Reply with one short line saying 'RoadSense test OK', then the same sentence in Telugu.")
    print(f"\n   Answered by {model}:")
    print("  ", text)
    print("\nYour Gemini key works.")
except Exception as exc:
    sys.exit(f"   FAILED: {exc.__class__.__name__}: {exc}\n"
             "   -> Send this message to Claude (check it does not show your key first).")
