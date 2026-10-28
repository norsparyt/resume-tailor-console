# Resume Tailor

Paste a job description, copy one prompt into your Claude chat, paste Claude's JSON reply back, accept or discard each edit in a visual diff, and download a one-page PDF.

**No API keys and no per-request billing.** The app never calls an AI service. You run the prompt in your own chat on claude.ai, which uses your normal Claude plan.

## How it works

The Tailor page walks through five steps:

1. **Paste the job description.**
2. **Copy the prompt into Claude.** *Copy to Clipboard* copies one message: your tailoring prompt (Settings), your base resume LaTeX and the JD, ending with a fixed block that tells Claude the exact JSON to reply with. Paste it into a new chat on claude.ai, pick Opus, and send it.
3. **Paste Claude's JSON reply** (the copy button on Claude's code block is easiest) and press **Process JSON**.
4. **Review the proposed changes** in an inline or side-by-side diff. Accept, discard or edit each one. The Unfillable Gaps and ATS keyword panels sit alongside.
5. **Build the PDF.** *Compile* builds exactly the accepted changes and shows the LaTeX in an editor next to the PDF. Click any text in the PDF to jump to the LaTeX that prints it, make any last edits by hand and press *Recompile*; hand edits apply only to this tailored version, never to your base resume. Downloads are offered once the PDF fits on one page and are named `Utkarsh_Tiwari_<Company>_resume.pdf`, with the company taken from Claude's reply and editable before you download. If the PDF runs longer, *Copy shorten prompt* gives you a second prompt for Claude; paste its reply in step 3 and the shortened changes come back already accepted.

## 1. Architecture and stack rationale

```
 Browser (Next.js + React)                         FastAPI backend (makes no AI calls)
 ─────────────────────────                         ───────────────────────────────────
 1. Job description
 2. Copy to Clipboard ── POST /api/prompt/tailor ─▶ prompts.tailor_prompt(): Settings prompt + base resume
        │                                             + JD + fixed JSON output format
        ▼  you paste it into claude.ai and copy Claude's JSON reply
 3. Process JSON ─────── POST /api/process ───────▶ paste.read_reply(): find the JSON, repair unescaped
                                                      │ LaTeX backslashes, normalise loose values
                                                      ▼
                                                    review.build(): locate each edit in the base .tex, reject
                                                      │ unsafe / overlapping / preamble edits, compile each edit
                                                      ▼ on its own, page count with every edit applied
 4. Review: word diff per change, accept / discard / edit, full-document view, gaps + ATS keywords
 5. Compile ──────────── POST /api/compile ───────▶ apply accepted edits ▶ pdflatex ▶ page count ▶ PDF + .tex
    LaTeX editor ─────── POST /api/compile/tex ───▶ compile the hand-edited document (base resume untouched)
    Click on the PDF ─── GET /api/output/{id}/source ▶ SyncTeX: point on the page ▶ source line ▶ clicked word
    Download ─────────── GET /api/output/{file} ──▶ saved as Utkarsh_Tiwari_<Company>_resume.pdf / .tex
    over one page? Copy shorten prompt ── POST /api/prompt/fit ─▶ same prompt + accepted edits + page count
 Base Resume page ────── /api/resume* ────────────▶ storage: data/base_resume.tex (+ history/)
 Settings page ───────── /api/settings/prompt ────▶ storage: data/settings.json
```

- **Next.js (React, TypeScript)** for the UI. Three pages, no UI framework. `diff` does the word- and line-level diffs, CodeMirror 6 (with its LaTeX mode) is the step 5 editor: line numbers, highlighting, search and undo. pdf.js draws the step 5 PDF in the page, so a click on its text can be traced back to the LaTeX. The session (JD, pasted reply, decisions, hand edits, company) is kept in the browser, so a reload loses nothing.
- **FastAPI (Python)** for the API. Python makes subprocess control of LaTeX and PDF inspection (`pypdf`) simple, and Pydantic validates the pasted JSON.
- **LaTeX (`pdflatex` by default)** does all formatting and PDF output. The app never edits your preamble, margins or macros; it only replaces snippets of body text, so the original formatting is preserved. Every compile also writes a SyncTeX file (`-synctex=1`, built into pdflatex, xelatex, lualatex and tectonic) that maps points on the PDF back to source lines; the backend reads it itself, so no extra tool is needed.
- **Claude in your own browser instead of an API.** A chat reply has no schema enforcement, so the backend reads it defensively: it finds the JSON inside a code fence or surrounding text, repairs LaTeX backslashes Claude forgot to escape, accepts loose values (`emphasise`, `Nice to have`), and lists anything it can't use instead of failing the whole reply.
- **Plain files for storage** (`backend/data/`). A single-user tool doesn't need a database; history is a folder of timestamped `.tex` files.

### How edits stay reviewable and one page

1. Claude returns a list of independent `original → proposed` replacements, each tied to an exact snippet of your base LaTeX.
2. The backend locates every snippet (whitespace-tolerant) and drops any edit that is not found, is ambiguous, overlaps another, touches the preamble, uses unsafe commands (`\input`, `\write18`, `\def` …), has unbalanced braces, or **fails to compile on its own**. Dropped edits are listed in the UI with the reason. If most edits don't match, the UI says so, which usually means the base resume changed after the prompt was copied.
3. It compiles the resume with *all* surviving edits and tells you if that runs past one page.
4. In the UI you accept or discard each edit (or edit its LaTeX). **Compile** builds exactly the accepted set, and you can still edit the whole document by hand before downloading. Download is only offered when the latest compile is one page and matches the editor; otherwise discard something, shorten the LaTeX, or use **Copy shorten prompt**. If you change your picks after editing by hand, your edits are kept until you choose to rebuild.
5. A factuality guard flags any number in a proposed edit that doesn't exist anywhere in your base resume.

## 2. Project structure

```
resume-tailor/
├── README.md
├── docker-compose.yml            # backend with LaTeX preinstalled
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example              # optional settings, no keys
│   ├── app/
│   │   ├── main.py               # FastAPI routes
│   │   ├── config.py             # env-var settings
│   │   ├── prompts.py            # default prompt, fixed JSON output format, prompt builders
│   │   ├── paste.py              # reads Claude's pasted reply: finds the JSON, repairs and normalises it
│   │   ├── review.py             # per-change compile check and page count for a pasted reply
│   │   ├── changes.py            # reply schema, locating/validating/applying edits, factuality guard
│   │   ├── latex.py              # sandboxed compile, page count, LaTeX safety checks
│   │   ├── synctex.py            # PDF click → LaTeX line (reads LaTeX's SyncTeX file) → clicked word
│   │   └── storage.py            # base resume, version history, prompt settings
│   ├── templates/
│   │   └── sample_resume.tex     # placeholder base resume used on first run
│   ├── tests/
│   │   ├── test_core.py          # prompts, change validation, compiling, hand-edited LaTeX, download names, settings
│   │   ├── test_paste.py         # pasted replies: fences, prose, bad escapes, loose values, broken JSON
│   │   └── test_synctex.py       # clicking PDF text finds its line and word in the LaTeX
│   └── data/                     # created at runtime (gitignored)
└── frontend/
    ├── package.json
    ├── .env.local.example
    ├── app/
    │   ├── layout.tsx            # nav + backend health banner
    │   ├── page.tsx              # Tailor: JD, copy prompt, paste reply, review, compile, download
    │   ├── resume/page.tsx       # Base resume: edit, upload .tex, preview, restore history
    │   ├── settings/page.tsx     # Editable tailoring prompt
    │   └── globals.css
    ├── components/
    │   ├── ChangeCard.tsx        # one change: accept / discard / edit
    │   ├── LatexEditor.tsx       # step 5 LaTeX editor (CodeMirror)
    │   ├── PdfPreview.tsx        # step 5 PDF drawn with pdf.js; a click finds the text in the LaTeX
    │   ├── WordDiff.tsx          # inline and side-by-side word diff
    │   ├── FullDiff.tsx          # whole-document side-by-side line diff
    │   ├── InsightPanels.tsx     # Unfillable Gaps, ATS keywords, dropped suggestions
    │   └── Nav.tsx
    └── lib/
        ├── api.ts                # typed API client
        ├── followLine.ts         # follows a line through edits made since the last compile
        └── delatex.ts            # LaTeX → readable text for the review view
```

## 3. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | LaTeX status |
| GET / PUT | `/api/resume` | Read or replace the base resume (must compile to one page unless `force`) |
| POST | `/api/resume/upload` | Replace the base resume with an uploaded `.tex` |
| GET | `/api/resume/pdf` | Compile the base resume |
| GET | `/api/resume/history`, `/api/resume/history/{name}` | List or read previous versions |
| POST | `/api/resume/history/{name}/restore` | Restore a previous version |
| GET / PUT / DELETE | `/api/settings/prompt` | Read, save, or reset the tailoring prompt |
| POST | `/api/prompt/tailor` | `{jd}` → the prompt to paste into Claude |
| POST | `/api/prompt/fit` | `{jd, changes, pages}` → a prompt asking Claude to shorten an accepted set |
| POST | `/api/process` | `{text}` (Claude's pasted reply) → validated changes, gaps, keywords, page estimate |
| POST | `/api/compile` | `{changes}` → compiled PDF and `.tex` with page count |
| POST | `/api/compile/tex` | `{tex}` (the hand-edited document) → compiled PDF and `.tex` with page count |
| GET | `/api/output/{file}` | Fetch a compiled PDF or `.tex` (`?download=true&filename=…` to save under that name) |
| GET | `/api/output/{id}/source` | `?page&x&y&text&word` (a click on that compile's PDF) → `{line, start, end}` in its LaTeX |

Interactive docs: http://localhost:8000/docs

## 4. The prompt

*Copy to Clipboard* copies one message, in this order (source: `backend/app/prompts.py`):

1. Your tailoring prompt from Settings (the default is below).
2. Your base resume inside `<base_resume_latex>` tags.
3. The job description inside `<job_description>` tags.
4. One line asking Claude to tailor the resume to the JD.
5. The fixed output-format block (below). It isn't editable, so a customised prompt can't break the JSON the diff viewer reads.

*Copy shorten prompt* sends the same parts plus your accepted changes in `<current_changes_json>` and the page count, and asks for a tighter set. It repeats everything, so it works in the same chat or a new one.

Default tailoring prompt, shown and editable on the Settings page:

````text
You are an expert resume strategist and LaTeX editor for the Indian job market. You tailor an existing LaTeX resume to one specific job description (JD) by proposing small, surgical edits that the candidate reviews one at a time.

## 1. Strict factuality (highest priority, never violate)
- Use ONLY facts already present in the base resume: employers, titles, dates, projects, tools, technologies, metrics, degrees, certifications, achievements.
- You may rephrase, reorder, merge, condense, or emphasise those facts. You may swap a word for an accurate synonym the JD uses (e.g. "built REST services" -> "developed RESTful APIs" if the resume shows that work).
- NEVER invent or inflate: no new skills, tools, employers, responsibilities, numbers, percentages, team sizes, durations, seniority, or outcomes. Do not upgrade "familiar with" to "expert in". Do not turn "assisted" into "led".
- A keyword may be added only when the resume already demonstrates it. If the evidence is indirect, leave it out and list it as a gap.
- When unsure whether something is supported, do not propose it. A missed keyword is acceptable; a fabricated one is not.

## 2. Target audience: Indian job market and ATS
- Assume the resume is first parsed by an ATS (Naukri RMS, Taleo, Workday, Greenhouse, Lever, Darwinbox, SuccessFactors) and then skimmed by an Indian recruiter in 6 to 10 seconds.
- Extract the JD's hard requirements: role title, must-have skills, tools/stack, domain, years of experience, certifications, and location or notice-period cues. Mirror the JD's exact phrasing and spelling for skills the resume genuinely supports (e.g. "Spring Boot" not "Springboot", "CI/CD" not "continuous delivery"), including both the acronym and the expansion when space allows (e.g. "Machine Learning (ML)").
- Keep ATS-friendly wording: standard section names, plain text skills, no keyword stuffing, no hidden text, no tables or graphics introduced.
- Use Indian conventions already used in the resume (e.g. LPA, lakh, CGPA out of 10, B.Tech/M.Tech). Do not convert or invent them.

## 3. Strong top third
- The top third of page one (header/headline, summary or profile, skills, and the first bullets of the most recent role) must carry the strongest, most JD-relevant signal.
- Prioritise edits there: align the headline or summary with the JD's role title and top 3 to 5 requirements (truthfully), reorder skills so the JD's must-haves come first, and lead the most recent role with the bullet that best matches the JD.
- Bullets should start with a strong action verb and keep existing quantified impact up front.

## 4. Gap analysis
- For every critical or important JD requirement the base resume cannot truthfully support, do not force it into the resume. Report it as an unfillable gap with a one-line reason and, where useful, an honest suggestion (e.g. "mention in cover letter if you have used it", "consider a certification").

## 5. One page, original formatting
- The compiled PDF must stay on exactly one page. Treat the base resume's length as the budget: across all your changes the total text should be the same length or shorter. If you lengthen one bullet, shorten or remove a weaker, less relevant one.
- Prefer rewording within the same line length. Removing low-relevance bullets is allowed and counts as an edit the candidate can reject.
- Never change the preamble, document class, packages, margins, font sizes, spacing commands, custom macros or their definitions, or section structure. Edit only the human-readable content inside the document body.

## 6. How to write each change
- Each change replaces one exact, contiguous snippet of the base LaTeX ("original") with new LaTeX ("proposed"). Keep changes small and independent, usually one bullet, one skills line, or one summary sentence, so each can be accepted or discarded alone.
- "original" must be copied character-for-character from the base resume and must be unique in it. Include a little surrounding text if needed to make it unique. Changes must not overlap.
- "proposed" must be valid LaTeX that uses the same macros and structure as the original (e.g. keep \resumeItem{...}, keep braces balanced, escape &, %, $, #, _ as the original does).
- To reorder items, use one change whose original spans the items and whose proposed has them in the new order.
- To remove a bullet, set proposed to an empty string (or to the remaining items). Never leave a list environment with no items: if you remove the only bullet of an entry, include the surrounding list start and end commands in "original" so the whole list goes.
- Every change must compile on its own, because the candidate may accept any one of them without the others.
- Order the change list by impact, most important first, and give each a short rationale tied to the JD.
````

Fixed output-format block, always at the end:

````text
---
Output format (fixed by the application, which reads your reply automatically)

Reply with one JSON object in a single ```json code block, and no text before or after it. Do not put it in an artifact or a file. The values below only illustrate the format:

```json
{
  "company": "Acme Payments",
  "summary": "Two or three sentences on the tailoring strategy.",
  "changes": [
    {
      "id": "c1",
      "section": "Experience - Acme Corp",
      "kind": "rephrase",
      "original": "\\resumeItem{Built REST services for the payments team}",
      "proposed": "\\resumeItem{Developed RESTful APIs for the payments team}",
      "rationale": "Mirrors the JD's wording for work the resume already shows.",
      "keywords": ["RESTful APIs"]
    }
  ],
  "unfillable_gaps": [
    {
      "requirement": "Kubernetes",
      "importance": "critical",
      "reason": "The resume shows no Kubernetes work.",
      "suggestion": "Mention it in a cover letter if you have used it."
    }
  ],
  "keywords": {
    "jd_keywords": ["RESTful APIs", "Kubernetes"],
    "already_present": [],
    "surfaced_by_changes": ["RESTful APIs"],
    "missing": ["Kubernetes"]
  }
}
```

Rules for the JSON:
- "company" is the hiring company's name as the JD gives it, in its short form (for example "Razorpay", not "Razorpay Software Private Limited"), or "" if the JD doesn't name one.
- "kind" is one of rephrase, reorder, emphasize, condense or remove. "importance" is one of critical, important or nice-to-have.
- "original" is an exact, unique snippet of the base resume LaTeX from inside the document body. "proposed" is its LaTeX replacement, or "" to remove it.
- "jd_keywords" lists the JD's most important keywords, highest priority first. "already_present", "surfaced_by_changes" and "missing" sort them into keywords the base resume already has, keywords your changes add truthfully, and keywords that cannot be added truthfully.
- It must be valid JSON: write every LaTeX backslash as \\ (\\resumeItem, \\textbf, \\%), a double quote as \", and a line break as \n. No comments and no trailing commas.
- Never use \input, \include, \write18, \immediate, \openin, \openout, \catcode, \def or \newcommand in "proposed".
- If no truthful improvement is possible, return an empty "changes" list and explain why in "summary".
````

The reply is validated against this schema (`backend/app/changes.py`):

```
TailoringResult
  company: str            # hiring company, for the download file name ("" if the JD doesn't name one)
  summary: str
  changes: [{ id, section, kind: rephrase|reorder|emphasize|condense|remove,
              original, proposed, rationale, keywords[] }]
  unfillable_gaps: [{ requirement, importance: critical|important|nice-to-have, reason, suggestion }]
  keywords: { jd_keywords[], already_present[], surfaced_by_changes[], missing[] }
```

## 5. Setup

### Prerequisites

- Python 3.10+
- Node.js 20+ (on Node 20, `npm install` warns that pdf.js wants 22.13 or newer; pdf.js only runs in the browser here, so the warning is harmless)
- A LaTeX distribution with `pdflatex` on your PATH
  - macOS: `brew install --cask mactex-no-gui` (or BasicTeX + `sudo tlmgr install titlesec enumitem fancyhdr preprint`)
  - Ubuntu/Debian: `sudo apt install texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended`
  - Windows: MiKTeX (installs missing packages on first compile)
  - Or skip local LaTeX and run the backend with Docker (below).
- A Claude account at https://claude.ai. The prompt is written with Opus in mind.

### Upgrading an existing copy

1. Copy the `backend/data` folder from your old copy into this one. It holds your base resume, its history and your custom prompt.
2. In `frontend`, run `npm install` again. The step 5 LaTeX editor adds CodeMirror and the clickable PDF preview adds pdf.js.
3. Coming from the Gemini version only: in the backend's virtualenv, `pip uninstall google-genai` (optional, nothing uses it any more) and `pip install -r requirements.txt`. Delete the `GEMINI_*` lines from `backend/.env`, or delete the file; it's optional now. If you want to be sure the old key can never be billed, delete it in Google AI Studio.

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

No `.env` is needed. To change the LaTeX engine or allowed origins, `cp .env.example .env` and edit it.

Or with Docker (includes LaTeX): `docker compose up --build`.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local                         # points at http://localhost:8000
npm run dev
```

Open http://localhost:3000.

### First run

1. Go to **Base Resume** and replace the placeholder with your own `.tex` (upload or paste, then Save). It must compile to one page; previous versions are kept under "Previous versions".
2. Optionally adjust the prompt under **Settings**.
3. On **Tailor**, follow the five steps above. The download name's `Utkarsh_Tiwari` part is set by `FILE_NAME_OWNER` in `frontend/app/page.tsx`.

If your resume uses packages your TeX install lacks, the compile error log is shown in the UI. If it needs XeLaTeX (e.g. `fontspec`), set `LATEX_ENGINE=xelatex`.

### Tips for the Claude chat

- Start a new chat for each job description, so an earlier JD doesn't colour the next one.
- claude.ai shows a long paste as an attachment. That's expected, and Claude still reads all of it.
- If **Process JSON** says the reply isn't valid JSON or looks cut off, ask Claude to "resend the complete JSON as one ```json code block" and paste that.
- Your resume and the JD go into your Claude chat under your Claude account's privacy settings. The app itself sends nothing anywhere.

### Tests

```bash
cd backend && pip install pytest httpx && pytest -q
```

No network is needed. Tests that compile are skipped when LaTeX isn't installed.

## Configuration

All settings are optional environment variables in `backend/.env` (see `.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `LATEX_ENGINE` | `pdflatex` | `xelatex`, `lualatex` or `tectonic` |
| `LATEX_TIMEOUT_SECONDS` | `60` | per compile |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated |
| `DATA_DIR` | `backend/data` | base resume, history, settings, PDFs |
