import os
import sys
from pathlib import Path

if os.getenv("VERCEL"):
    os.environ["HOME"] = "/tmp"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    Path.home = lambda: Path("/tmp")

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from main import app