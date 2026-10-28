"""Finds the LaTeX source line behind a point on the compiled PDF.

The compile step runs LaTeX with -synctex=1, which writes resume.synctex.gz next to
the PDF. That file records, for every line of text on the page, a box with its
position and, inside it, where each run of characters ends and which source line
the glue (space) or kern before it came from. This reads just enough of it to
answer "which line of resume.tex produced the text at this spot".
"""
import gzip
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

# SyncTeX positions are in TeX scaled points; PDF positions are in big points (1/72 in).
_SP_PER_BP = 65781.76

# A record such as "(1,72:2368143,7300336:35522151,455111,127431": type, tag, line, h, v and,
# for boxes, width, height and depth. Kern records ("k...:width") carry only a width.
_RECORD = re.compile(r"([\[(hvxkg$r])(\d+),(\d+)(?:,-?\d+)?:(-?\d+),(-?\d+|=)(?::(-?\d+)(?:,(-?\d+),(-?\d+))?)?")


@dataclass
class _Node:
    kind: str
    tag: int
    line: int
    h: int
    v: int


@dataclass
class _Box:
    kind: str  # "(" for a horizontal box (a line of text), "[" for a vertical one
    tag: int
    line: int
    h: int
    v: int
    width: int
    height: int
    depth: int
    first: int  # index of the first node inside the box
    last: int = 0  # index after the last node inside the box


@dataclass
class _Page:
    nodes: list[_Node] = field(default_factory=list)
    boxes: list[_Box] = field(default_factory=list)


class SyncTex:
    def __init__(self, data: bytes, main_file: str = "resume.tex"):
        text = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        self.pages: dict[int, _Page] = {}
        self.main_tag: int | None = None
        unit, magnification = 1.0, 1000.0
        page: _Page | None = None
        open_boxes: list[_Box] = []
        in_content = False
        last_v = 0
        for raw in text.decode("utf-8", "replace").splitlines():
            if not in_content:
                key, _, value = raw.partition(":")
                if key == "Input":
                    tag, _, path = value.partition(":")
                    if self.main_tag is None and path.replace("\\", "/").endswith("/" + main_file):
                        self.main_tag = int(tag)
                elif key == "Unit":
                    unit = float(value)
                elif key == "Magnification":
                    magnification = float(value)
                elif key == "Content":
                    in_content = True
                continue
            if not raw:
                continue
            c = raw[0]
            if c == "{":
                page = self.pages.setdefault(int(raw[1:] or 0), _Page())
                open_boxes = []
            elif c == "}":
                page = None
            elif page is None:
                if raw.startswith("Postamble:"):
                    break
            elif c in ")]":
                if open_boxes:
                    open_boxes.pop().last = len(page.nodes)
            else:
                m = _RECORD.match(raw)
                if not m:
                    continue
                kind, tag, line, h = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
                v = last_v if m.group(5) == "=" else int(m.group(5))
                last_v = v
                if kind in "[(":
                    box = _Box(kind, tag, line, h, v, int(m.group(6) or 0), int(m.group(7) or 0), int(m.group(8) or 0), len(page.nodes))
                    page.boxes.append(box)
                    open_boxes.append(box)
                else:
                    page.nodes.append(_Node(kind, tag, line, h, v))
        if self.main_tag is None:
            self.main_tag = 1
        self._per_bp = _SP_PER_BP / (unit * magnification / 1000.0)  # file units per PDF point

    def line_at(self, page: int, x: float, y: float) -> int | None:
        """The source line for a point given in PDF points from the top-left corner of the page."""
        p = self.pages.get(page)
        if p is None:
            return None
        h, v = x * self._per_bp, y * self._per_bp
        box = self._box_at(p, h, v)
        if box is None:
            return None
        inside = [n for n in p.nodes[box.first : box.last] if n.tag == self.main_tag]
        # Each "x" record marks where a run of characters ends, so the run under the point
        # ends at the first one at or to the right of it.
        runs = [i for i, n in enumerate(inside) if n.kind == "x"]
        after = next((i for i in runs if inside[i].h >= h), runs[-1] if runs else None)
        if after is None:
            return box.line if box.tag == self.main_tag else None
        run = inside[after]
        # A run takes its line from the node before it, which for the first word of a wrapped
        # line is the margin glue, numbered with the line where the paragraph ended. The space
        # after the word was read from the same source line as the word, so prefer it.
        nxt = inside[after + 1] if after + 1 < len(inside) else None
        if nxt is not None and nxt.kind == "g" and nxt.h > run.h:
            return nxt.line
        return run.line

    def _box_at(self, p: _Page, h: float, v: float) -> _Box | None:
        """The smallest horizontal box (line of text) around the point, or the nearest one."""
        lines = [b for b in p.boxes if b.kind == "(" and b.width > 0 and b.last > b.first]
        best, best_key = None, None
        for b in lines or [b for b in p.boxes if b.width > 0 and b.last > b.first]:
            dx = max(b.h - h, 0, h - (b.h + b.width))
            dy = max(b.v - b.height - v, 0, v - (b.v + b.depth))
            key = (dx + dy, b.width * (b.height + b.depth))
            if best_key is None or key < best_key:
                best, best_key = b, key
        return best


# ---------- matching the clicked text in the source ----------

def _tokens(s: str) -> list[str]:
    """Lower-case words and numbers, with accents and ligatures (ﬁ) unfolded."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return [t.lower() for t in re.findall(r"[^\W_]+", s)]


def _plain(line: str) -> str:
    """Roughly the text a line of LaTeX prints: no comments, link targets or command names."""
    line = re.sub(r"(?<!\\)%.*", "", line)
    line = re.sub(r"\\href\s*\{[^}]*\}", " ", line)
    line = re.sub(r"\\[A-Za-z@]+\*?", " ", line)
    return line


def _match(tokens: list[str], want: list[str]) -> int:
    """2 if want appears in tokens as consecutive words, 1 if it is the start or end of a longer
    word (half of a word hyphenated at a line break), else 0."""
    n = len(want)
    if any(tokens[i : i + n] == want for i in range(len(tokens) - n + 1)):
        return 2
    w = want[0]
    return int(n == 1 and len(w) >= 3 and any(t != w and (t.startswith(w) or t.endswith(w)) for t in tokens))


def _span(line: str, word: str) -> tuple[int, int] | None:
    """Where word sits in a line of LaTeX, allowing escapes such as \\% or \\& inside it."""
    want = _tokens(word)
    if not want:
        return None
    pattern = r"[^0-9A-Za-z]{0,6}".join(re.escape(t) for t in want)
    m = re.search(rf"(?<![0-9A-Za-z]){pattern}(?![0-9A-Za-z])", line, re.I)
    if not m and len(want) == 1 and len(want[0]) >= 3:
        m = re.search(pattern, line, re.I)
    if not m:
        return None
    start, end = m.span()
    # Half of a hyphenated word selects the whole word.
    while start > 0 and line[start - 1].isalnum():
        start -= 1
    while end < len(line) and line[end].isalnum():
        end += 1
    return start, end


def locate(tex: str, text: str, word: str, near: int | None = None, guess: float | None = None) -> dict | None:
    """The line (1-based) and character span of the clicked word in tex.

    text is the run of PDF text around the click and word the word clicked. near is the
    line SyncTeX gave. Text a macro prints is credited to the line where the macro call
    ends, so the word is looked for a few lines around it first. Without SyncTeX, guess
    (0 at the top of the document, 1 at the bottom) picks between repeated text.
    """
    lines = tex.split("\n")
    begin = next((i + 1 for i, l in enumerate(lines) if "\\begin{document}" in l), 1)
    end = next((i + 1 for i, l in enumerate(lines) if "\\end{document}" in l), len(lines))
    want, around = _tokens(word), set(_tokens(text))

    def best_of(candidates: range, anchor: float, pull: float) -> int | None:
        best, best_score = None, 0.0
        for n in candidates:
            tokens = _tokens(_plain(lines[n - 1]))
            match = _match(tokens, want) if want else 0
            if not match:
                continue
            overlap = len(around & set(tokens)) / len(around) if around else 0.0
            score = match + overlap - pull * abs(n - anchor)
            if best is None or score > best_score:
                best, best_score = n, score
        return best

    found = None
    if near is not None:
        found = best_of(range(max(1, near - 6), min(len(lines), near + 2) + 1), near, 0.05)
    if found is None:
        anchor = near if near is not None else begin + (guess or 0.0) * (end - begin)
        found = best_of(range(begin, end + 1), anchor, 0.01) or best_of(range(1, len(lines) + 1), anchor, 0.01)
    if found is None:
        if near is None:
            return None
        found = near
    span = _span(lines[found - 1], word)
    return {"line": found, "start": span[0] if span else None, "end": span[1] if span else None}


def find(out_dir: Path, job: str, page: int, x: float, y: float, text: str, word: str) -> dict | None:
    """Where text clicked on the PDF of compile job comes from in its LaTeX."""
    tex = (out_dir / f"{job}.tex").read_text(encoding="utf-8")
    sync_path = out_dir / f"{job}.synctex.gz"
    near = SyncTex(sync_path.read_bytes()).line_at(page, x, y) if sync_path.exists() else None
    guess = None
    if near is None and (out_dir / f"{job}.pdf").exists():
        # Without SyncTeX, how far down the document the click was picks between repeated text.
        pdf = PdfReader(out_dir / f"{job}.pdf")
        count = len(pdf.pages)
        height = float(pdf.pages[min(max(page, 1), count) - 1].mediabox.height) if count else 1.0
        guess = ((page - 1) + y / height) / max(count, 1)
    return locate(tex, text, word, near=near, guess=guess)
