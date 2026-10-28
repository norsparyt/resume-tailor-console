"""Turns a parsed reply into the reviewable change list the Tailor page shows.

Every change is checked against the stored base resume: it must be found, stay
out of the preamble, avoid unsafe LaTeX and compile on its own. Then the resume
is compiled with every surviving change to report the page count.
"""
from concurrent.futures import ThreadPoolExecutor

from .changes import ApplyItem, RejectedChange, ResolvedChange, TailoringResult, apply_changes, resolve_changes
from .latex import LatexError, compile_tex, engine_available


def _measure(base_tex: str, resolved: list[ResolvedChange]) -> tuple[int | None, str | None]:
    """Compile base + all resolved changes. Returns (pages, error)."""
    tex, _ = apply_changes(base_tex, [ApplyItem(id=c.id, original=c.original, proposed=c.proposed) for c in resolved])
    try:
        return compile_tex(tex).pages, None
    except LatexError as e:
        return None, f"{e} {e.log_excerpt[:500]}"


def _drop_uncompilable(base_tex: str, resolved: list[ResolvedChange]):
    """Compile the base resume with each change on its own, so any change the user
    accepts individually is known to compile. Returns (kept, rejected)."""

    def breaks(c: ResolvedChange) -> str | None:
        tex, _ = apply_changes(base_tex, [ApplyItem(id=c.id, original=c.original, proposed=c.proposed)])
        try:
            compile_tex(tex)
            return None
        except LatexError as e:
            first = next((l for l in e.log_excerpt.splitlines() if l.startswith("!")), str(e))
            return f"Breaks LaTeX compilation ({first.lstrip('! ')})"

    with ThreadPoolExecutor(max_workers=4) as pool:
        errors = list(pool.map(breaks, resolved))
    kept = [c for c, err in zip(resolved, errors) if err is None]
    dropped = [
        RejectedChange(id=c.id, section=c.section, original=c.original, proposed=c.proposed, reason=err)
        for c, err in zip(resolved, errors)
        if err is not None
    ]
    return kept, dropped


def _resolve(base_tex: str, result: TailoringResult):
    if not engine_available():
        return resolve_changes(base_tex, result.changes)
    # A change that breaks compilation may have blocked an overlapping one that works,
    # so re-resolve without the broken ones until nothing else breaks.
    broken: list[RejectedChange] = []
    while True:
        broken_ids = {b.id for b in broken}
        resolved, rejected = resolve_changes(base_tex, [c for c in result.changes if c.id not in broken_ids])
        resolved, newly_broken = _drop_uncompilable(base_tex, resolved)
        broken += newly_broken
        if not newly_broken:
            return resolved, rejected + broken


def build(base_tex: str, result: TailoringResult, malformed: list[RejectedChange], notes: list[str]) -> dict:
    resolved, rejected = _resolve(base_tex, result)
    rejected = malformed + rejected
    notes = list(notes)

    not_found = sum("not found" in r.reason for r in rejected)
    if not_found and not_found * 2 >= len(result.changes) + len(malformed):
        notes.append(
            f"{not_found} of {len(result.changes) + len(malformed)} changes don't match your current base resume. "
            "If you changed the base resume after copying the prompt, copy the prompt again and send it to Claude."
        )

    pages = None
    if not engine_available():
        notes.append("LaTeX is not installed, so the compile and one-page checks were skipped.")
    elif resolved:
        pages, err = _measure(base_tex, resolved)
        if err:
            notes.append(f"Applying every change at once does not compile: {err}")
        elif pages > 1:
            notes.append(
                f"With every change accepted the PDF is {pages} pages. Accept fewer, or compile your picks "
                "and use the shorten prompt that appears."
            )

    return {
        "company": result.company,
        "summary": result.summary,
        "changes": [c.model_dump() for c in resolved],
        "rejected": [r.model_dump() for r in rejected],
        "unfillable_gaps": [g.model_dump() for g in result.unfillable_gaps],
        "keywords": result.keywords.model_dump(),
        "pages_if_all_accepted": pages,
        "notes": notes,
        "base_resume": base_tex,
    }
