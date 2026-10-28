"""File-based storage: one base resume, its history, and the settings JSON."""
import json
import shutil
from datetime import datetime, timezone

from .config import DATA_DIR, TEMPLATE_DIR
from .prompts import DEFAULT_SYSTEM_PROMPT

RESUME_PATH = DATA_DIR / "base_resume.tex"
HISTORY_DIR = DATA_DIR / "history"
SETTINGS_PATH = DATA_DIR / "settings.json"
OUTPUT_DIR = DATA_DIR / "output"


def init_storage() -> None:
    for d in (DATA_DIR, HISTORY_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not RESUME_PATH.exists():
        shutil.copy(TEMPLATE_DIR / "sample_resume.tex", RESUME_PATH)


def get_resume() -> str:
    return RESUME_PATH.read_text(encoding="utf-8")


def save_resume(tex: str) -> str:
    """Archive the current base resume, then replace it. Returns the archive file name."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archived = HISTORY_DIR / f"base_resume_{stamp}.tex"
    if RESUME_PATH.exists():
        shutil.copy(RESUME_PATH, archived)
    RESUME_PATH.write_text(tex, encoding="utf-8")
    return archived.name


def list_history() -> list[str]:
    return sorted((p.name for p in HISTORY_DIR.glob("base_resume_*.tex")), reverse=True)


def get_history(name: str) -> str:
    path = (HISTORY_DIR / name).resolve()
    if path.parent != HISTORY_DIR.resolve() or not path.exists():
        raise FileNotFoundError(name)
    return path.read_text(encoding="utf-8")


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return {}


def get_prompt() -> tuple[str, bool]:
    """Returns (prompt, is_default)."""
    custom = _load_settings().get("system_prompt")
    if custom:
        return custom, False
    return DEFAULT_SYSTEM_PROMPT, True


def save_prompt(prompt: str | None) -> None:
    settings = _load_settings()
    if prompt is None or prompt.strip() == "" or prompt == DEFAULT_SYSTEM_PROMPT:
        settings.pop("system_prompt", None)
    else:
        settings["system_prompt"] = prompt
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
