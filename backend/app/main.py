import json
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import paste, prompts, review, storage, synctex
from .changes import ApplyItem, apply_changes
from .config import CORS_ORIGINS, LATEX_ENGINE
from .latex import LatexError, compile_tex, engine_available
from .prompts import DEFAULT_SYSTEM_PROMPT


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.init_storage()
    yield


app = FastAPI(title="Resume Tailor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _latex_http_error(e: LatexError, status: int = 422) -> HTTPException:
    return HTTPException(status, {"message": str(e), "log": e.log_excerpt})


# ---------- health ----------

@app.get("/api/health")
def health():
    return {"ok": True, "latex_engine": LATEX_ENGINE, "latex_available": engine_available()}


# ---------- base resume ----------

class ResumeIn(BaseModel):
    tex: str
    force: bool = False  # save even if it doesn't compile to one page


def _check_resume(tex: str, force: bool) -> dict:
    if r"\begin{document}" not in tex or r"\end{document}" not in tex:
        raise HTTPException(422, {"message": "This doesn't look like a full LaTeX document (missing \\begin{document} or \\end{document})."})
    if not engine_available():
        return {"pages": None, "warning": "LaTeX is not installed, so the resume was saved without a compile check."}
    try:
        pages = compile_tex(tex).pages
    except LatexError as e:
        if not force:
            raise _latex_http_error(e)
        return {"pages": None, "warning": f"Saved, but it does not compile: {e}"}
    if pages > 1 and not force:
        raise HTTPException(422, {"message": f"The base resume compiles to {pages} pages. It must be one page.", "pages": pages})
    return {"pages": pages, "warning": None}


@app.get("/api/resume")
def get_resume():
    return {"tex": storage.get_resume()}


@app.put("/api/resume")
def put_resume(body: ResumeIn):
    check = _check_resume(body.tex, body.force)
    archived = storage.save_resume(body.tex)
    return {"saved": True, "archived_previous_as": archived, **check}


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...), force: bool = False):
    if not file.filename or not file.filename.lower().endswith(".tex"):
        raise HTTPException(422, {"message": "Upload a .tex file."})
    raw = await file.read()
    try:
        tex = raw.decode("utf-8")
    except UnicodeDecodeError:
        tex = raw.decode("latin-1")
    check = _check_resume(tex, force)
    archived = storage.save_resume(tex)
    return {"saved": True, "archived_previous_as": archived, "tex": tex, **check}


@app.get("/api/resume/pdf")
def base_resume_pdf():
    try:
        result = compile_tex(storage.get_resume())
    except LatexError as e:
        raise _latex_http_error(e)
    return Response(result.pdf, media_type="application/pdf", headers={"X-Page-Count": str(result.pages)})


@app.get("/api/resume/history")
def resume_history():
    return {"versions": storage.list_history()}


@app.get("/api/resume/history/{name}")
def resume_version(name: str):
    try:
        return {"name": name, "tex": storage.get_history(name)}
    except FileNotFoundError:
        raise HTTPException(404, {"message": "Version not found."})


@app.post("/api/resume/history/{name}/restore")
def restore_version(name: str):
    try:
        tex = storage.get_history(name)
    except FileNotFoundError:
        raise HTTPException(404, {"message": "Version not found."})
    archived = storage.save_resume(tex)
    return {"saved": True, "archived_previous_as": archived, "tex": tex}


# ---------- settings ----------

class PromptIn(BaseModel):
    prompt: str


@app.get("/api/settings/prompt")
def get_prompt():
    prompt, is_default = storage.get_prompt()
    return {"prompt": prompt, "is_default": is_default, "default_prompt": DEFAULT_SYSTEM_PROMPT}


@app.put("/api/settings/prompt")
def put_prompt(body: PromptIn):
    storage.save_prompt(body.prompt)
    return get_prompt()


@app.delete("/api/settings/prompt")
def reset_prompt():
    storage.save_prompt(None)
    return get_prompt()


# ---------- copy-paste tailoring ----------
# The app makes no AI calls. It builds the prompt you paste into a Claude chat,
# then checks the JSON reply you paste back.

class TailorPromptIn(BaseModel):
    jd: str


class FitItem(ApplyItem):
    section: str = ""
    kind: str = ""
    rationale: str = ""
    keywords: list[str] = []


class FitPromptIn(BaseModel):
    jd: str = ""
    changes: list[FitItem]
    pages: int = 2


class ProcessIn(BaseModel):
    text: str


@app.post("/api/prompt/tailor")
def tailor_prompt(body: TailorPromptIn):
    if len(body.jd.strip()) < 40:
        raise HTTPException(422, {"message": "Paste the full job description first (it looks too short)."})
    system_prompt, _ = storage.get_prompt()
    return {"prompt": prompts.tailor_prompt(system_prompt, storage.get_resume(), body.jd)}


@app.post("/api/prompt/fit")
def fit_prompt(body: FitPromptIn):
    base = storage.get_resume()
    system_prompt, _ = storage.get_prompt()
    new_tex, _ = apply_changes(base, body.changes)
    order = ("id", "section", "kind", "original", "proposed", "rationale", "keywords")
    payload = json.dumps([{k: getattr(c, k) for k in order} for c in body.changes], indent=1, ensure_ascii=False)
    return {"prompt": prompts.fit_prompt(system_prompt, base, body.jd, payload, body.pages, len(base), len(new_tex))}


@app.post("/api/process")
def process_reply(body: ProcessIn):
    try:
        result, malformed, notes = paste.read_reply(body.text)
    except paste.PasteError as e:
        raise HTTPException(422, {"message": str(e)})
    return review.build(storage.get_resume(), result, malformed, notes)


# ---------- compile ----------

class CompileIn(BaseModel):
    changes: list[ApplyItem]


class CompileTexIn(BaseModel):
    tex: str


def _compile_and_store(tex: str, errors: list[str]) -> dict:
    try:
        result = compile_tex(tex)
    except LatexError as e:
        # Send the LaTeX back too, so it can be fixed by hand in the editor.
        raise HTTPException(422, {"message": str(e), "log": e.log_excerpt, "tex": tex})
    job = uuid.uuid4().hex[:12]
    (storage.OUTPUT_DIR / f"{job}.pdf").write_bytes(result.pdf)
    (storage.OUTPUT_DIR / f"{job}.tex").write_text(tex, encoding="utf-8")
    if result.synctex:
        (storage.OUTPUT_DIR / f"{job}.synctex.gz").write_bytes(result.synctex)
    return {
        "id": job,
        "pages": result.pages,
        "one_page": result.pages == 1,
        "errors": errors,
        "pdf_url": f"/api/output/{job}.pdf",
        "tex_url": f"/api/output/{job}.tex",
        "tex": tex,
    }


@app.post("/api/compile")
def compile_route(body: CompileIn):
    """Base resume + the accepted changes."""
    tex, errors = apply_changes(storage.get_resume(), body.changes)
    return _compile_and_store(tex, errors)


@app.post("/api/compile/tex")
def compile_tex_route(body: CompileTexIn):
    """A full document edited by hand on the Tailor page. The base resume is not changed."""
    if r"\begin{document}" not in body.tex or r"\end{document}" not in body.tex:
        raise HTTPException(422, {"message": "This doesn't look like a full LaTeX document (missing \\begin{document} or \\end{document}).", "tex": body.tex})
    return _compile_and_store(body.tex, [])


@app.get("/api/output/{job}/source")
def output_source(job: str, page: int, x: float, y: float, text: str = "", word: str = ""):
    """Where text clicked on a compiled PDF comes from in that compile's LaTeX. x and y are in PDF
    points from the page's top-left corner; text is the run of PDF text clicked, word the word."""
    if not re.fullmatch(r"[0-9a-f]{12}", job) or not (storage.OUTPUT_DIR / f"{job}.tex").exists():
        raise HTTPException(404, {"message": "File not found."})
    spot = synctex.find(storage.OUTPUT_DIR, job, page, x, y, text, word)
    if spot is None:
        raise HTTPException(404, {"message": "That text wasn't found in the LaTeX."})
    return spot


def _download_name(filename: str | None, suffix: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename or "").strip("._")[:150]
    stem = stem[: -len(suffix)] if stem.lower().endswith(suffix) else stem
    return (stem or "tailored_resume") + suffix


@app.get("/api/output/{name}")
def output_file(name: str, download: bool = False, filename: str | None = None):
    path = (storage.OUTPUT_DIR / name).resolve()
    if path.parent != storage.OUTPUT_DIR.resolve() or not path.exists() or path.suffix not in (".pdf", ".tex"):
        raise HTTPException(404, {"message": "File not found."})
    media = "application/pdf" if path.suffix == ".pdf" else "application/x-tex"
    return FileResponse(
        path,
        media_type=media,
        filename=_download_name(filename, path.suffix),
        content_disposition_type="attachment" if download else "inline",
    )
