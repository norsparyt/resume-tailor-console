"""Reading replies pasted from a Claude chat (app/paste.py and POST /api/process)."""
import json
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="rt_test_"))

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app
from app.paste import PasteError, read_reply

storage.init_storage()

CHANGE = {
    "id": "c1",
    "section": "Summary",
    "kind": "rephrase",
    "original": "Mentored two junior engineers",
    "proposed": "Mentored 2 junior engineers",
    "rationale": "r",
    "keywords": ["Mentoring"],
}
REPLY = {
    "company": "  Zeta ",
    "summary": "Led with Python.",
    "changes": [CHANGE],
    "unfillable_gaps": [{"requirement": "Go", "importance": "critical", "reason": "Not in resume.", "suggestion": ""}],
    "keywords": {"jd_keywords": ["Go"], "already_present": [], "surfaced_by_changes": [], "missing": ["Go"]},
}


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(REPLY),
        "```json\n" + json.dumps(REPLY, indent=2) + "\n```",
        "Here is the tailored JSON:\n\n```json\n" + json.dumps(REPLY) + "\n```\n\nLet me know if you want {more} changes.",
        "Sure. " + json.dumps(REPLY) + " Hope this helps!",
        json.dumps([CHANGE]),  # just the list of changes
    ],
)
def test_finds_the_json_however_it_was_copied(text):
    result, malformed, notes = read_reply(text)
    assert [c.original for c in result.changes] == ["Mentored two junior engineers"]
    assert not malformed and not notes
    assert result.company == ("" if text.startswith("[") else "Zeta")


def test_loose_values_are_normalised():
    loose = {
        "changes": [
            {"kind": "Emphasise", "original": "a", "proposed": "b", "keywords": "Kafka, AWS"},
            {"id": "x", "kind": "something else", "original": "c", "proposed": ""},
        ],
        "unfillable_gaps": [{"requirement": "Go", "importance": "Nice to have"}, "Kubernetes", {"importance": "high"}],
    }
    result, malformed, _ = read_reply(json.dumps(loose))
    first, second = result.changes
    assert (first.id, first.kind, first.keywords, first.section) == ("c1", "emphasize", ["Kafka", "AWS"], "")
    assert (second.id, second.kind, second.proposed) == ("x", "rephrase", "")
    assert [(g.requirement, g.importance) for g in result.unfillable_gaps] == [("Go", "nice-to-have"), ("Kubernetes", "important")]
    assert result.keywords.jd_keywords == [] and result.summary == "" and not malformed


def test_changes_missing_text_are_reported_not_applied():
    data = {"changes": [{"id": "c1", "proposed": "x"}, {"id": "c2", "original": "Mentored two junior engineers"}, "oops"]}
    result, malformed, _ = read_reply(json.dumps(data))
    assert result.changes == []
    assert [(m.id, m.reason) for m in malformed] == [
        ("c1", 'Has no "original" text to replace.'),
        ("c2", 'Has no "proposed" text.'),
        ("c3", "Not a change object."),
    ]


def test_unescaped_latex_backslashes_are_repaired():
    # As written by a model that forgot JSON escaping: \t, \r and \f would otherwise become control characters.
    raw = r'{"changes": [{"original": "\textbf{Languages}{: Python, Java}", "proposed": "\resumeItem{60\% \footnotesize ok}\n\\item", "kind": "reorder"}]}'
    result, _, notes = read_reply(raw)
    change = result.changes[0]
    assert change.original == r"\textbf{Languages}{: Python, Java}"
    assert change.proposed == "\\resumeItem{60\\% \\footnotesize ok}\n\\item"
    assert notes and "repaired" in notes[0]


def test_one_unescaped_backslash_among_escaped_ones():
    raw = '{"changes": [{"original": "\\\\textbf{x} 25\\%", "proposed": "\\\\textbf{y}\\n25\\%"}]}'
    change = read_reply(raw)[0].changes[0]
    assert change.original == r"\textbf{x} 25\%"
    assert change.proposed == "\\textbf{y}\n25\\%"


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "Paste Claude's JSON reply first"),
        ("Sorry, I can't help with that.", "No JSON object found"),
        ('{"summary": "no changes key"}', 'no "changes" list'),
        ('{"changes": [{"original": "a" "proposed": "b"}]}', "line 1, column"),
        ('```json\n{"summary": "s", "changes": [{"original": "a", "proposed": "b"},\n {"original": "c", "propo', "cut off"),
    ],
)
def test_unusable_pastes_give_a_readable_error(text, message):
    with pytest.raises(PasteError, match=message):
        read_reply(text)


def test_process_endpoint():
    c = TestClient(app)
    bad = c.post("/api/process", json={"text": "not json"})
    assert bad.status_code == 422 and "No JSON object" in bad.json()["detail"]["message"]

    ok = c.post("/api/process", json={"text": "```json\n" + json.dumps(REPLY) + "\n```"}).json()
    assert [ch["id"] for ch in ok["changes"]] == ["c1"]
    assert ok["unfillable_gaps"][0]["requirement"] == "Go"
    assert ok["base_resume"] == storage.get_resume() and "model" not in ok
    assert ok["company"] == "Zeta"

    other_resume = dict(REPLY, changes=[dict(CHANGE, id=f"c{i}", original=f"Text from another resume {i}") for i in range(3)])
    stale = c.post("/api/process", json={"text": json.dumps(other_resume)}).json()
    assert stale["changes"] == [] and len(stale["rejected"]) == 3
    assert any("don't match your current base resume" in n for n in stale["notes"])
