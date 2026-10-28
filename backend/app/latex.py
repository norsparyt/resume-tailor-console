"""LaTeX compilation and page counting.

Compiles in a throwaway directory with shell escape disabled, then counts pages
with pypdf. The layout of the base resume is never modified here: the one-page
rule is enforced by flagging content that overflows, which is then shortened.
"""
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .config import LATEX_ENGINE, LATEX_TIMEOUT_SECONDS

FORBIDDEN_PRIMITIVES = re.compile(
    r"\\(write18|immediate|input|include|openin|openout|read|catcode|def|edef|gdef|xdef|newcommand|renewcommand|usepackage|documentclass)\b"
)


class LatexError(Exception):
    def __init__(self, message: str, log_excerpt: str = ""):
        super().__init__(message)
        self.log_excerpt = log_excerpt


@dataclass
class CompileResult:
    pdf: bytes
    pages: int
    log: str
    synctex: bytes | None = None  # resume.synctex.gz: maps points on the PDF back to source lines


def engine_available() -> bool:
    return shutil.which(LATEX_ENGINE) is not None


def _command(engine: str, tex_name: str) -> list[str]:
    # SyncTeX data lets a click on the PDF preview find the LaTeX behind it.
    if engine == "tectonic":
        return ["tectonic", "--keep-logs", "--synctex", "--outdir", ".", tex_name]
    return [engine, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "-synctex=1", tex_name]


def _log_excerpt(log: str, lines: int = 25) -> str:
    out = log.splitlines()
    for i, line in enumerate(out):
        if line.startswith("!"):
            return "\n".join(out[i : i + lines])
    return "\n".join(out[-lines:])


def compile_tex(tex: str) -> CompileResult:
    if not engine_available():
        raise LatexError(f"LaTeX engine '{LATEX_ENGINE}' is not installed or not on PATH.")
    with tempfile.TemporaryDirectory(prefix="resume_") as tmp:
        workdir = Path(tmp)
        (workdir / "resume.tex").write_text(tex, encoding="utf-8")
        log = ""
        passes = 1 if LATEX_ENGINE == "tectonic" else 2
        for _ in range(passes):
            try:
                proc = subprocess.run(
                    _command(LATEX_ENGINE, "resume.tex"),
                    cwd=workdir,
                    capture_output=True,
                    timeout=LATEX_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                raise LatexError("LaTeX compilation timed out.")
            log_file = workdir / "resume.log"
            log = log_file.read_text(errors="replace") if log_file.exists() else proc.stdout.decode(errors="replace")
            if proc.returncode != 0:
                raise LatexError("LaTeX compilation failed.", _log_excerpt(log))
            if "Rerun to get" not in log and "Label(s) may have changed" not in log:
                break
        pdf_path = workdir / "resume.pdf"
        if not pdf_path.exists():
            raise LatexError("LaTeX produced no PDF.", _log_excerpt(log))
        pdf = pdf_path.read_bytes()
        pages = len(PdfReader(pdf_path).pages)
        synctex_path = workdir / "resume.synctex.gz"
        synctex = synctex_path.read_bytes() if synctex_path.exists() else None
        return CompileResult(pdf=pdf, pages=pages, log=log, synctex=synctex)


def unsafe_commands(snippet: str) -> list[str]:
    return sorted({m.group(0) for m in FORBIDDEN_PRIMITIVES.finditer(snippet)})


def braces_balanced(snippet: str) -> bool:
    depth = 0
    i = 0
    while i < len(snippet):
        c = snippet[i]
        if c == "\\":
            i += 2  # skip escaped char such as \{ or \}
            continue
        if c == "%":  # comment to end of line
            nl = snippet.find("\n", i)
            if nl == -1:
                break
            i = nl
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0
