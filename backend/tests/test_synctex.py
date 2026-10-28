"""Finding the LaTeX behind a click on the compiled PDF (app/synctex.py, GET /api/output/{id}/source).
Compile tests are skipped without LaTeX."""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="rt_test_"))

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import storage
from app.config import TEMPLATE_DIR
from app.latex import engine_available
from app.main import app
from app.synctex import SyncTex, locate

storage.init_storage()
SAMPLE = (TEMPLATE_DIR / "sample_resume.tex").read_text(encoding="utf-8")
needs_latex = pytest.mark.skipif(not engine_available(), reason="LaTeX not installed")

SP = 65781.76  # TeX scaled points per PDF point

# Part of a real resume.synctex.gz: the second line on the page of a paragraph written on
# source line 72, which ends on line 73.
SYNCTEX = "\n".join([
    "SyncTeX Version:1",
    "Input:1:/tmp/resume_x/./resume.tex",
    "Input:2:/usr/share/texlive/texmf-dist/tex/latex/base/article.cls",
    "Output:pdf",
    "Magnification:1000",
    "Unit:1",
    "X Offset:0",
    "Y Offset:0",
    "Content:",
    "!3710",
    "{1",
    "(1,73:2368143,8086768:35522151,455111,127431",
    "x1,73:6192905,8086768",
    "g1,72:6411358,8086768",
    "x1,72:8625022,8086768",
    "g1,72:8843475,8086768",
    "k1,73:34333261,8086768:3557033",
    ")",
    "}1",
    "Postamble:",
    "Count:7",
])

TEX = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\resumeSubheading",
    r"  {Software Engineer}{2023 -- Present}",
    r"  {Acme \& Sons}{Pune}",
    r"\resumeItem{Cut costs by 60\% with a reconciliation service}",
    r"\resumeSubheading",
    r"  {Software Engineer}{2021 -- 2022}",
    r"  {Beta Labs}{Pune}",
    r"\end{document}",
])


def line_with(tex: str, snippet: str) -> int:
    return next(n for n, line in enumerate(tex.split("\n"), 1) if snippet in line)


def text_start(pdf_path, prefix: str) -> tuple[float, float, str]:
    """Where the line of PDF text starting with prefix begins, in points from the page's top-left."""
    page = PdfReader(pdf_path).pages[0]
    height = float(page.mediabox.height)
    found = []

    def visit(text, cm, tm, font, size):
        if not found and text.strip().startswith(prefix):
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            found.append((x, height - y, text.strip()))

    page.extract_text(visitor_text=visit)
    return found[0]


def test_synctex_credits_a_wrapped_word_to_its_own_line():
    st = SyncTex(SYNCTEX.encode())
    v = 8_000_000 / SP  # just above the baseline
    assert st.line_at(1, 5_000_000 / SP, v) == 72  # first word on the line, followed by a space from line 72
    assert st.line_at(1, 7_000_000 / SP, v) == 72
    assert st.line_at(2, 10, v) is None


@pytest.mark.parametrize(
    "word, text, near, line, picked",
    [
        ("Engineer", "Software Engineer", 5, 4, "Engineer"),  # macro arguments are credited to where the call ends
        ("Engineer", "Software Engineer", 9, 8, "Engineer"),  # the repeat nearest to the SyncTeX line
        ("Sons", "Acme & Sons", 5, 5, "Sons"),
        ("60%", "Cut costs by 60% with a reconciliation", 6, 6, "60"),
        ("ciliation", "ciliation service", 6, 6, "reconciliation"),  # half of a hyphenated word
        ("•", "•", 6, 6, None),  # nothing to match: the whole line
    ],
)
def test_locate_finds_the_word_near_the_synctex_line(word, text, near, line, picked):
    spot = locate(TEX, text, word, near=near)
    assert spot["line"] == line
    got = TEX.split("\n")[line - 1][spot["start"] : spot["end"]] if spot["start"] is not None else None
    assert got == picked


def test_locate_without_synctex_uses_the_position_on_the_page():
    assert locate(TEX, "2021 – 2022", "2021", guess=0.9)["line"] == 8
    assert locate(TEX, "Software Engineer", "Software", guess=0.1)["line"] == 4
    assert locate(TEX, "nothing", "Zanzibar", guess=0.5) is None


@needs_latex
def test_clicking_pdf_text_finds_its_latex():
    c = TestClient(app)
    job = c.post("/api/compile/tex", json={"tex": SAMPLE}).json()["id"]
    pdf = storage.OUTPUT_DIR / f"{job}.pdf"
    sync = storage.OUTPUT_DIR / f"{job}.synctex.gz"
    assert sync.exists()
    lines = SAMPLE.split("\n")
    for prefix, word, snippet in [
        ("Software Engineer II", "Software", "{Software Engineer II}"),  # a \resumeSubheading argument
        ("reconciliation systems", "reconciliation", r"\small{Backend engineer"),  # first word of a wrapped line
        ("Languages", "Languages", r"\textbf{Languages}"),
    ]:
        x, y, text = text_start(pdf, prefix)
        spot = c.get(f"/api/output/{job}/source", params={"page": 1, "x": x + 3, "y": y - 3, "text": text, "word": word}).json()
        line = line_with(SAMPLE, snippet)
        assert spot["line"] == line, (prefix, spot)
        assert lines[line - 1][spot["start"] : spot["end"]] == word
    x, y, _ = text_start(pdf, "reconciliation systems")
    assert SyncTex(sync.read_bytes()).line_at(1, x + 3, y - 3) == line_with(SAMPLE, r"\small{Backend engineer")


@needs_latex
def test_without_synctex_the_clicked_text_is_matched():
    c = TestClient(app)
    job = c.post("/api/compile/tex", json={"tex": SAMPLE}).json()["id"]
    (storage.OUTPUT_DIR / f"{job}.synctex.gz").unlink()
    params = {"page": 1, "x": 100, "y": 320, "text": "Mentored two junior engineers and ran weekly code reviews", "word": "junior"}
    spot = c.get(f"/api/output/{job}/source", params=params).json()
    line = line_with(SAMPLE, "Mentored two junior engineers")
    assert spot["line"] == line and SAMPLE.split("\n")[line - 1][spot["start"] : spot["end"]] == "junior"
    assert c.get(f"/api/output/{job}/source", params={**params, "word": "Zanzibar"}).status_code == 404
    assert c.get("/api/output/not-a-job/source", params=params).status_code == 404
