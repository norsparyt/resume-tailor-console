"""Reads the JSON reply pasted back from a Claude chat.

A chat reply arrives however it was copied: inside a ```json fence or not, maybe
with a sentence around it. A chat also has no schema enforcement, so small slips
are expected. This module finds the JSON object, repairs LaTeX backslashes that
were left unescaped, and normalises loose field values (for example "emphasise"
or "Nice to have") before building the strict TailoringResult.
"""
import json
import re

from .changes import Gap, KeywordAnalysis, ProposedChange, RejectedChange, TailoringResult


class PasteError(ValueError):
    pass


_FENCE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n(.*?)```", re.S)
# One backslash escape: \uXXXX or a backslash plus any single character.
_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.S)

KINDS = ("rephrase", "reorder", "emphasize", "condense", "remove")
_KIND_ALIASES = {
    "emphasise": "emphasize", "emphasis": "emphasize", "reword": "rephrase", "rewrite": "rephrase",
    "re-order": "reorder", "shorten": "condense", "delete": "remove", "removal": "remove",
}
IMPORTANCE = ("critical", "important", "nice-to-have")
_IMPORTANCE_ALIASES = {"high": "critical", "must-have": "critical", "medium": "important", "low": "nice-to-have", "optional": "nice-to-have"}


def _escape_latex(raw: str) -> str:
    r"""Repair JSON written without escaping LaTeX backslashes. Real JSON escapes
    (\", \\, \/, \n, \uXXXX) are kept. Any other backslash becomes a literal one,
    including \t, \r, \b and \f before a letter, since in a resume those are
    \textbf, \resumeItem, \bfseries or \footnotesize rather than control characters."""

    def fix(m: re.Match) -> str:
        seq = m.group(1)
        if seq in ('"', "\\", "/", "n") or len(seq) == 5:
            return m.group(0)
        if seq in "trbf" and not raw[m.end():m.end() + 1].isalpha():
            return m.group(0)
        return "\\\\" + seq

    return _ESCAPE.sub(fix, raw)


def _candidates(text: str) -> list[str]:
    """Fenced blocks first, then the whole paste, each cut to its outermost brackets."""
    out = []
    for block in [*_FENCE.findall(text), text]:
        block = block.strip()
        opener, closer = ("[", "]") if block.startswith("[") else ("{", "}")  # a bare list of changes is accepted too
        start, end = block.find(opener), block.rfind(closer)
        if start != -1 and end > start:
            out.append(block[start:end + 1])
    return out


def _load(text: str) -> tuple[object, bool]:
    """Returns (parsed JSON, whether backslashes had to be repaired)."""
    text = text.strip().lstrip("\ufeff")
    if not text:
        raise PasteError("Paste Claude's JSON reply first.")
    candidates = _candidates(text)
    if not candidates:
        raise PasteError("No JSON object found in the pasted text. Copy Claude's reply with the copy button on its code block.")

    parsed: list[tuple[object, bool]] = []
    first_error: json.JSONDecodeError | None = None
    for cand in candidates:
        try:
            value, repaired = json.loads(cand, strict=False), False
        except json.JSONDecodeError as e:
            first_error = first_error or e
            if "escape" not in e.msg:
                continue
            try:
                value, repaired = json.loads(_escape_latex(cand), strict=False), True
            except json.JSONDecodeError:
                continue
        if isinstance(value, list) or (isinstance(value, dict) and "changes" in value):
            return value, repaired
        parsed.append((value, repaired))
    if parsed:
        return parsed[0]

    e = first_error
    hint = "Copy Claude's whole reply again, or ask Claude to resend the JSON as one valid ```json code block."
    if e.pos >= len(e.doc) - 3:
        hint = "It looks cut off. If Claude's reply stopped early, ask it to continue, or to resend the complete JSON."
    raise PasteError(f"The pasted text isn't valid JSON ({e.msg}, line {e.lineno}, column {e.colno}). {hint}")


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "\n".join(_text(x) for x in v)
    return v if isinstance(v, str) else str(v)


def _words(v) -> list[str]:
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        return []
    return [w for w in (_text(x).strip() for x in v) if w]


def _pick(value, allowed: tuple[str, ...], aliases: dict[str, str], default: str) -> str:
    v = re.sub(r"[\s_]+", "-", _text(value).strip().lower())
    v = aliases.get(v, v)
    return v if v in allowed else default


def read_reply(text: str) -> tuple[TailoringResult, list[RejectedChange], list[str]]:
    """Parse a pasted reply. Returns (result, malformed changes, notes for the UI).
    Raises PasteError with a readable message when there is nothing usable."""
    data, repaired = _load(text)
    if isinstance(data, list):
        data = {"changes": data}
    if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
        raise PasteError('The JSON has no "changes" list. Make sure you pasted Claude\'s reply to the prompt from step 2.')

    changes: list[ProposedChange] = []
    malformed: list[RejectedChange] = []
    for i, raw in enumerate(data["changes"], 1):
        if not isinstance(raw, dict):
            malformed.append(RejectedChange(id=f"c{i}", section="", original="", proposed=_text(raw), reason="Not a change object."))
            continue
        cid = _text(raw.get("id")).strip() or f"c{i}"
        section = _text(raw.get("section")).strip()
        original, proposed = _text(raw.get("original")), raw.get("proposed")
        if not original.strip():
            malformed.append(RejectedChange(id=cid, section=section, original="", proposed=_text(proposed), reason='Has no "original" text to replace.'))
            continue
        if proposed is None:  # "" removes the snippet; a missing value is a mistake, not a removal
            malformed.append(RejectedChange(id=cid, section=section, original=original, proposed="", reason='Has no "proposed" text.'))
            continue
        changes.append(
            ProposedChange(
                id=cid,
                section=section,
                kind=_pick(raw.get("kind"), KINDS, _KIND_ALIASES, "rephrase"),
                original=original,
                proposed=_text(proposed),
                rationale=_text(raw.get("rationale")).strip(),
                keywords=_words(raw.get("keywords")),
            )
        )

    gaps: list[Gap] = []
    for g in data.get("unfillable_gaps") or []:
        if isinstance(g, str):
            g = {"requirement": g}
        if not isinstance(g, dict) or not _text(g.get("requirement")).strip():
            continue
        gaps.append(
            Gap(
                requirement=_text(g.get("requirement")).strip(),
                importance=_pick(g.get("importance"), IMPORTANCE, _IMPORTANCE_ALIASES, "important"),
                reason=_text(g.get("reason")).strip(),
                suggestion=_text(g.get("suggestion")).strip(),
            )
        )

    kw = data.get("keywords") if isinstance(data.get("keywords"), dict) else {}
    keywords = KeywordAnalysis(**{f: _words(kw.get(f)) for f in KeywordAnalysis.model_fields})

    notes = []
    if repaired:
        notes.append("Claude's JSON had LaTeX backslashes that weren't escaped, so they were repaired automatically. Check the changes in the LaTeX view.")
    result = TailoringResult(
        company=_text(data.get("company")).strip(),
        summary=_text(data.get("summary")).strip(),
        changes=changes,
        unfillable_gaps=gaps,
        keywords=keywords,
    )
    return result, malformed, notes
