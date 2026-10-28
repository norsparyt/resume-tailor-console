"""Run with: cd backend && pytest -q
No AI service or API key is involved: replies are pasted JSON. Compile tests are skipped without LaTeX."""
import json
import os
import re
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="rt_test_"))

import pytest
from fastapi.testclient import TestClient

from app import paste, storage
from app.changes import ApplyItem, ProposedChange, apply_changes, locate, resolve_changes
from app.latex import braces_balanced, engine_available, unsafe_commands
from app.main import app
from app.prompts import DEFAULT_SYSTEM_PROMPT, OUTPUT_FORMAT

storage.init_storage()
BASE = storage.get_resume()
needs_latex = pytest.mark.skipif(not engine_available(), reason="LaTeX not installed")

SUMMARY = "Backend engineer with 4 years of experience building Python and Java services for fintech products."


def change(id, original, proposed, kind="rephrase"):
    return ProposedChange(id=id, section="s", kind=kind, original=original, proposed=proposed, rationale="r", keywords=[])


def reply(*changes: ProposedChange) -> str:
    """A pasted reply the way Claude sends it: a sentence, then JSON in a ```json fence."""
    body = {
        "summary": "ok",
        "changes": [c.model_dump() for c in changes],
        "unfillable_gaps": [],
        "keywords": {"jd_keywords": [], "already_present": [], "surfaced_by_changes": [], "missing": []},
    }
    return "Here are the changes:\n```json\n" + json.dumps(body, indent=2) + "\n```"


def test_locate_exact_and_whitespace_insensitive():
    assert isinstance(locate(BASE, SUMMARY), tuple)
    squashed = "Backend engineer with 4 years   of\nexperience"
    s, e = locate(BASE, squashed)
    assert BASE[s:e].startswith("Backend engineer")
    assert isinstance(locate(BASE, "not in the resume at all"), str)
    assert "more than once" in locate(BASE, r"\resumeItemListStart")


def test_resolve_rejects_bad_changes():
    changes = [
        change("c1", SUMMARY, "Backend engineer (4 yrs) building Python and Java fintech services."),
        change("c2", "Backend engineer with 4 years", "x"),  # overlaps c1
        change("c3", r"\usepackage{latexsym}", ""),  # preamble
        change("c4", "Mentored two junior engineers", r"\input{/etc/passwd}"),
        change("c5", "Mentored two junior engineers", "Mentored {two"),
        change("c6", "made up text", "anything"),
    ]
    ok, bad = resolve_changes(BASE, changes)
    assert [c.id for c in ok] == ["c1"]
    reasons = {r.id: r.reason for r in bad}
    assert "Overlaps" in reasons["c2"]
    assert "preamble" in reasons["c3"]
    assert "disallowed" in reasons["c4"]
    assert "braces" in reasons["c5"]
    assert "not found" in reasons["c6"]


def test_factuality_warning_on_new_number():
    ok, _ = resolve_changes(BASE, [change("c1", "Mentored two junior engineers", "Mentored 7 junior engineers")])
    assert ok[0].warnings


def test_apply_subset_only():
    items = [
        ApplyItem(id="a", original="Python, Java, SQL, JavaScript", proposed="Java, Python, SQL, JavaScript"),
        ApplyItem(id="b", original="Mentored two junior engineers", proposed="Mentored 2 junior engineers"),
    ]
    out, errors = apply_changes(BASE, items[:1])
    assert not errors
    assert "Java, Python, SQL" in out and "Mentored two junior" in out


def test_latex_guards():
    assert unsafe_commands(r"\write18{rm -rf}") == [r"\write18"]
    assert unsafe_commands(r"\textbf{ok} 60\%") == []
    assert braces_balanced(r"\textbf{a} \{ 50\% }") is False
    assert braces_balanced(r"\textbf{a \{x\}}")


@needs_latex
def test_compile_route_and_one_page_flag():
    c = TestClient(app)
    r = c.post("/api/compile", json={"changes": [{"id": "a", "original": SUMMARY, "proposed": SUMMARY + " Strong in Kafka."}]})
    assert r.status_code == 200, r.text
    assert r.json()["pages"] == 1 and r.json()["one_page"]
    long = " ".join(["Built and shipped services."] * 400)
    r = c.post("/api/compile", json={"changes": [{"id": "a", "original": SUMMARY, "proposed": long}]})
    assert r.json()["pages"] > 1 and not r.json()["one_page"]


@needs_latex
def test_process_reports_pages_with_every_change():
    c = TestClient(app)
    short = c.post("/api/process", json={"text": reply(change("c1", SUMMARY, "Backend engineer building Python and Java fintech services for 4 years."))}).json()
    assert short["pages_if_all_accepted"] == 1 and not short["notes"]
    long = " ".join(["Built and shipped Python services."] * 300)
    body = c.post("/api/process", json={"text": reply(change("c1", SUMMARY, long))}).json()
    assert body["pages_if_all_accepted"] > 1
    assert any("shorten prompt" in n for n in body["notes"])


def test_tailor_prompt_combines_prompt_resume_and_jd():
    c = TestClient(app)
    jd = "Senior Backend Engineer, Bengaluru. Python, Kafka, AWS and RESTful APIs required."
    prompt = c.post("/api/prompt/tailor", json={"jd": jd}).json()["prompt"]
    assert prompt.startswith(DEFAULT_SYSTEM_PROMPT.strip()[:80])
    assert BASE.strip() in prompt and jd in prompt
    assert prompt.rstrip().endswith(OUTPUT_FORMAT.strip()[-80:])
    assert c.post("/api/prompt/tailor", json={"jd": "too short"}).status_code == 422

    c.put("/api/settings/prompt", json={"prompt": "MY CUSTOM RULES"})
    try:
        assert c.post("/api/prompt/tailor", json={"jd": jd}).json()["prompt"].startswith("MY CUSTOM RULES")
    finally:
        c.delete("/api/settings/prompt")


def test_fit_prompt_carries_changes_and_page_count():
    items = [{"id": "c7", "section": "Summary", "kind": "rephrase", "original": SUMMARY, "proposed": "Backend engineer \\& more", "rationale": "r", "keywords": ["Kafka"]}]
    prompt = TestClient(app).post("/api/prompt/fit", json={"jd": "Backend role", "changes": items, "pages": 3}).json()["prompt"]
    assert "compiles to 3 pages" in prompt
    payload = json.loads(re.search(r"<current_changes_json>\n(.*)\n</current_changes_json>", prompt, re.S).group(1))
    assert payload == items
    assert "Output format" in prompt and BASE.strip() in prompt


def test_output_format_example_is_a_valid_reply():
    example = re.search(r"```json\n(.*?)```", OUTPUT_FORMAT, re.S).group(1)
    result, malformed, notes = paste.read_reply(example)
    assert not malformed and not notes
    assert result.company == "Acme Payments"
    assert result.changes[0].original == "\\resumeItem{Built REST services for the payments team}"
    assert result.unfillable_gaps[0].importance == "critical"


@needs_latex
def test_compile_hand_edited_latex_and_download_name():
    c = TestClient(app)
    edited = BASE.replace("Mentored two junior engineers", "Mentored two junior engineers (hand edit)")
    r = c.post("/api/compile/tex", json={"tex": edited})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["one_page"] and body["tex"] == edited and "hand edit" in c.get(body["tex_url"]).text
    assert storage.get_resume() == BASE  # the base resume is untouched

    pdf = c.get(body["pdf_url"], params={"download": "true", "filename": "Utkarsh_Tiwari_Acme Payments/../x_resume"})
    assert pdf.content.startswith(b"%PDF")
    assert 'attachment; filename="Utkarsh_Tiwari_Acme_Payments_.._x_resume.pdf"' == pdf.headers["content-disposition"]
    assert c.get(body["tex_url"], params={"download": "true", "filename": "Utkarsh_Tiwari_Zeta_resume.tex"}).headers["content-disposition"].endswith('filename="Utkarsh_Tiwari_Zeta_resume.tex"')
    assert c.get(body["pdf_url"], params={"download": "true"}).headers["content-disposition"].endswith('filename="tailored_resume.pdf"')

    broken = BASE.replace("Mentored two junior engineers", r"Mentored \notacommand two junior engineers")
    r = c.post("/api/compile/tex", json={"tex": broken})
    assert r.status_code == 422
    detail = r.json()["detail"]
    line = 1 + broken[: broken.index("notacommand")].count("\n")
    assert f"l.{line}" in detail["log"] and detail["tex"] == broken
    assert c.post("/api/compile/tex", json={"tex": "just some text"}).status_code == 422


def test_prompt_settings_roundtrip():
    c = TestClient(app)
    assert c.get("/api/settings/prompt").json()["is_default"]
    c.put("/api/settings/prompt", json={"prompt": "custom"})
    assert c.get("/api/settings/prompt").json()["prompt"] == "custom"
    assert c.delete("/api/settings/prompt").json()["is_default"]


@needs_latex
def test_resume_replace_rejects_two_pages_and_keeps_history():
    c = TestClient(app)
    two_pages = BASE.replace(SUMMARY, " ".join(["filler text"] * 1500))
    r = c.put("/api/resume", json={"tex": two_pages})
    assert r.status_code == 422
    r = c.put("/api/resume", json={"tex": BASE})
    assert r.status_code == 200 and r.json()["pages"] == 1
    assert c.get("/api/resume/history").json()["versions"]


@needs_latex
def test_changes_that_break_latex_are_dropped():
    lonely = r"\resumeItem{Built a group expense-splitting web app with settlement suggestions, used by 300 friends and colleagues}"
    text = reply(change("c1", lonely, "", "remove"), change("c2", "Mentored two junior engineers", "Mentored 2 junior engineers"))
    body = TestClient(app).post("/api/process", json={"text": text}).json()
    assert [c["id"] for c in body["changes"]] == ["c2"]
    assert "Breaks LaTeX" in body["rejected"][0]["reason"]
