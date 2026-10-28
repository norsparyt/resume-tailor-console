import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data")).resolve()
TEMPLATE_DIR = BACKEND_DIR / "templates"

# pdflatex | xelatex | lualatex | tectonic
LATEX_ENGINE = os.getenv("LATEX_ENGINE", "pdflatex")
LATEX_TIMEOUT_SECONDS = int(os.getenv("LATEX_TIMEOUT_SECONDS", "60"))

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
