"""Schemas for the model's output, plus locating and applying individual changes.

Every change is an (original -> proposed) replacement of one contiguous snippet of
the base LaTeX. Changes are located against the base resume, validated, and
applied independently, which is what lets the UI accept or discard each one.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

from .latex import braces_balanced, unsafe_commands


# ---------- structured output returned by the model ----------

class ProposedChange(BaseModel):
    id: str = Field(description="Short stable id such as 'c1', 'c2'.")
    section: str = Field(description="Resume section the change is in, e.g. 'Summary', 'Skills', 'Experience - Acme Corp'.")
    kind: Literal["rephrase", "reorder", "emphasize", "condense", "remove"]
    original: str = Field(description="Exact, unique substring of the base resume LaTeX that is replaced.")
    proposed: str = Field(description="LaTeX replacement. Empty string removes the original.")
    rationale: str = Field(description="One sentence tying the change to the JD.")
    keywords: list[str] = Field(description="JD keywords this change surfaces (each must already be supported by the resume).")


class Gap(BaseModel):
    requirement: str
    importance: Literal["critical", "important", "nice-to-have"]
    reason: str = Field(description="Why the base resume cannot truthfully meet it.")
    suggestion: str = Field(description="Honest suggestion, or empty string.")


class KeywordAnalysis(BaseModel):
    jd_keywords: list[str] = Field(description="Most important JD keywords, highest priority first.")
    already_present: list[str] = Field(description="JD keywords already present in the base resume.")
    surfaced_by_changes: list[str] = Field(description="JD keywords the proposed changes add, truthfully.")
    missing: list[str] = Field(description="JD keywords the resume cannot truthfully include.")


class TailoringResult(BaseModel):
    company: str = Field("", description="The hiring company's short name from the JD, or empty. Used for the PDF file name.")
    summary: str = Field(description="Two or three sentences on the tailoring strategy.")
    changes: list[ProposedChange]
    unfillable_gaps: list[Gap]
    keywords: KeywordAnalysis


# ---------- validation and application ----------

class ResolvedChange(ProposedChange):
    start: int
    end: int
    warnings: list[str] = []


class RejectedChange(BaseModel):
    id: str
    section: str
    original: str
    proposed: str
    reason: str


class ApplyItem(BaseModel):
    id: str
    original: str
    proposed: str


def _body_start(tex: str) -> int:
    idx = tex.find(r"\begin{document}")
    return idx + len(r"\begin{document}") if idx >= 0 else 0


def locate(tex: str, original: str) -> tuple[int, int] | str:
    """Find a unique span for `original`. Falls back to whitespace-insensitive matching.
    Returns (start, end) or an error message."""
    if not original.strip():
        return "Original snippet is empty."
    count = tex.count(original)
    if count == 1:
        start = tex.index(original)
        return start, start + len(original)
    if count > 1:
        return "Original snippet appears more than once in the base resume."
    tokens = original.split()
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens))
    matches = list(pattern.finditer(tex))
    if len(matches) == 1:
        return matches[0].start(), matches[0].end()
    if len(matches) > 1:
        return "Original snippet appears more than once in the base resume."
    return "Original snippet was not found in the base resume."


# Numbers in visible text; LaTeX lengths such as -7pt or 0.97\textwidth are ignored.
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\d.,]|\s*(?:pt|in|em|ex|cm|mm|\\textwidth)\b)(?:\s*(?:\\%|x|\+|k|K|L|LPA|lakh|cr|Cr|M|million|crore)\b)?")


def factuality_warnings(base_tex: str, original: str, proposed: str) -> list[str]:
    """Cheap guard: flag numbers in the proposal that don't exist anywhere in the base resume."""
    warnings = []
    base_numbers = {re.sub(r"\D", "", m.group(0)) for m in _NUMBER.finditer(base_tex[_body_start(base_tex):])}
    for m in _NUMBER.finditer(proposed):
        digits = re.sub(r"\D", "", m.group(0))
        if digits and digits not in base_numbers:
            warnings.append(f"Number '{m.group(0).strip()}' does not appear in your base resume. Check it is true.")
    return warnings


def resolve_changes(base_tex: str, changes: list[ProposedChange]) -> tuple[list[ResolvedChange], list[RejectedChange]]:
    body_start = _body_start(base_tex)
    accepted: list[ResolvedChange] = []
    rejected: list[RejectedChange] = []
    taken: list[tuple[int, int]] = []
    seen_ids: set[str] = set()

    for ch in changes:
        def reject(reason: str):
            rejected.append(RejectedChange(id=ch.id, section=ch.section, original=ch.original, proposed=ch.proposed, reason=reason))

        if ch.id in seen_ids:
            ch = ch.model_copy(update={"id": f"{ch.id}_{len(seen_ids)}"})
        seen_ids.add(ch.id)

        if ch.original == ch.proposed:
            reject("No-op change.")
            continue
        span = locate(base_tex, ch.original)
        if isinstance(span, str):
            reject(span)
            continue
        start, end = span
        if start < body_start:
            reject("Change touches the LaTeX preamble, which must stay unchanged.")
            continue
        if any(start < e and s < end for s, e in taken):
            reject("Overlaps another change.")
            continue
        bad = unsafe_commands(ch.proposed)
        if bad:
            reject(f"Uses disallowed LaTeX commands: {', '.join(bad)}.")
            continue
        if not braces_balanced(ch.proposed):
            reject("Unbalanced braces in proposed LaTeX.")
            continue
        taken.append((start, end))
        accepted.append(
            ResolvedChange(
                **ch.model_dump(exclude={"original"}),
                original=base_tex[start:end],
                start=start,
                end=end,
                warnings=factuality_warnings(base_tex, ch.original, ch.proposed),
            )
        )
    accepted.sort(key=lambda c: c.start)
    return accepted, rejected


def apply_changes(base_tex: str, items: list[ApplyItem]) -> tuple[str, list[str]]:
    """Apply the selected changes to the base resume. Returns (new_tex, errors)."""
    errors: list[str] = []
    spans: list[tuple[int, int, str]] = []
    for item in items:
        span = locate(base_tex, item.original)
        if isinstance(span, str):
            errors.append(f"{item.id}: {span}")
            continue
        s, e = span
        if s < _body_start(base_tex):
            errors.append(f"{item.id}: touches the preamble.")
            continue
        if any(s < pe and ps < e for ps, pe, _ in spans):
            errors.append(f"{item.id}: overlaps another accepted change.")
            continue
        bad = unsafe_commands(item.proposed)
        if bad:
            errors.append(f"{item.id}: uses disallowed commands {', '.join(bad)}.")
            continue
        if not braces_balanced(item.proposed):
            errors.append(f"{item.id}: unbalanced braces.")
            continue
        spans.append((s, e, item.proposed))
    out = base_tex
    for s, e, text in sorted(spans, key=lambda x: x[0], reverse=True):
        out = out[:s] + text + out[e:]
    return out, errors
