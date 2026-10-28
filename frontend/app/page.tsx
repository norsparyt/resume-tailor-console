"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type ApplyItem, type CompileResult, type FitItem, type TailorResult } from "@/lib/api";
import { ChangeCard, type Decision } from "@/components/ChangeCard";
import { GapsPanel, KeywordPanel, RejectedPanel } from "@/components/InsightPanels";
import { FullDiff } from "@/components/FullDiff";
import { LatexEditor, type EditorJump } from "@/components/LatexEditor";
import { PdfPreview, type PdfClick } from "@/components/PdfPreview";
import { followLine } from "@/lib/followLine";
import type { DiffMode } from "@/components/WordDiff";

const STORE_KEY = "resume-tailor-session-v1";
const MIN_JD_CHARS = 40;
// Downloads are named <owner>_<company>_resume.pdf.
const FILE_NAME_OWNER = "Utkarsh_Tiwari";

// The preamble never changes, so the full-document view starts at \begin{document}.
const bodyOf = (tex: string) => tex.slice(Math.max(0, tex.indexOf("\\begin{document}")));

// "Acme Payments (India)" -> "Acme_Payments_India", with accents dropped so the name is safe everywhere.
const fileSlug = (s: string) =>
  s.normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

// Which prompt the next pasted reply answers. A reply to the shorten prompt starts out accepted.
type PromptKind = "tailor" | "fit";

// The LaTeX in the step 5 editor. generatedTex is what the accepted changes produced and key
// records which changes those were, so hand edits and later pick changes can be told apart.
interface FinalTex {
  tex: string;
  generatedTex: string;
  key: string;
}

interface Session {
  jd: string;
  pasted: string;
  pasteFor: PromptKind;
  result: TailorResult | null;
  decisions: Record<string, Decision>;
  edits: Record<string, string>;
  company: string;
  final: FinalTex | null;
}

type Compiled = CompileResult & { fitPrompt: string | null };

interface BuildError {
  message: string;
  log: string | null;
  line: number | null;
}

function load(): Partial<Session> | null {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {}
  }
  // Fallback for browsers without the clipboard API, or a page opened over plain http from another machine.
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch {}
  ta.remove();
  return ok;
}

export default function TailorPage() {
  const [jd, setJd] = useState("");
  const [prompt, setPrompt] = useState<{ jd: string; text: string } | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [focusCount, setFocusCount] = useState(0);
  const [pasted, setPasted] = useState("");
  const [pasteFor, setPasteFor] = useState<PromptKind>("tailor");
  const [result, setResult] = useState<TailorResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [company, setCompany] = useState("");
  const [final, setFinal] = useState<FinalTex | null>(null);
  const [mode, setMode] = useState<DiffMode>("inline");
  const [readable, setReadable] = useState(true);
  const [view, setView] = useState<"changes" | "document">("changes");
  const [busy, setBusy] = useState<null | "process" | "compile" | "recompile">(null);
  const [copied, setCopied] = useState<PromptKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorLog, setErrorLog] = useState<string | null>(null);
  const [buildError, setBuildError] = useState<BuildError | null>(null);
  const [focusLine, setFocusLine] = useState<EditorJump | null>(null);
  // compiled is the PDF on screen; built is the last build from the accepted changes, kept so
  // "Undo hand edits" can bring its PDF back without recompiling.
  const [compiled, setCompiled] = useState<Compiled | null>(null);
  const [built, setBuilt] = useState<Compiled | null>(null);
  const [loaded, setLoaded] = useState(false);
  const scrollToReview = useRef(false);

  useEffect(() => {
    const s = load();
    if (s) {
      setJd(s.jd ?? "");
      setPasted(s.pasted ?? "");
      setPasteFor(s.pasteFor ?? "tailor");
      setResult(s.result ?? null);
      setDecisions(s.decisions ?? {});
      setEdits(s.edits ?? {});
      setCompany(s.company ?? s.result?.company ?? "");
      setFinal(s.final ?? null);
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ jd, pasted, pasteFor, result, decisions, edits, company, final } satisfies Session));
    } catch {}
  }, [jd, pasted, pasteFor, result, decisions, edits, company, final, loaded]);

  // Coming back to this tab rebuilds the prompt, in case the base resume or Settings prompt changed in another tab.
  useEffect(() => {
    const onFocus = () => setFocusCount((n) => n + 1);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  // Rebuild the prompt shortly after the job description stops changing.
  const jdReady = jd.trim().length >= MIN_JD_CHARS;
  useEffect(() => {
    if (!loaded || !jdReady) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      api.tailorPrompt(jd)
        .then((r) => { if (!cancelled) { setPrompt({ jd, text: r.prompt }); setPromptError(null); } })
        .catch((e) => { if (!cancelled) setPromptError(e.message || String(e)); });
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jd, jdReady, loaded, focusCount]);
  const readyPrompt = jdReady && prompt?.jd === jd ? prompt.text : null;

  useEffect(() => {
    if (result && scrollToReview.current) {
      scrollToReview.current = false;
      document.getElementById("review")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result]);

  const changes = result?.changes ?? [];
  const textOf = (id: string, fallback: string) => edits[id] ?? fallback;
  const accepted: ApplyItem[] = useMemo(
    () => changes.filter((c) => decisions[c.id] === "accepted").map((c) => ({ id: c.id, original: c.original, proposed: textOf(c.id, c.proposed) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [changes, decisions, edits],
  );
  const acceptedKey = useMemo(() => JSON.stringify(accepted), [accepted]);
  const counts = useMemo(() => {
    const c = { accepted: 0, discarded: 0, pending: 0 };
    changes.forEach((ch) => c[decisions[ch.id] ?? "pending"]++);
    return c;
  }, [changes, decisions]);

  const previewTex = useMemo(() => {
    if (!result) return "";
    let tex = result.base_resume;
    [...changes]
      .filter((c) => decisions[c.id] === "accepted")
      .sort((a, b) => b.start - a.start)
      .forEach((c) => { tex = tex.slice(0, c.start) + textOf(c.id, c.proposed) + tex.slice(c.end); });
    return tex;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, decisions, edits]);

  const handEdited = final !== null && final.tex !== final.generatedTex;
  const picksChanged = final !== null && final.key !== acceptedKey;
  const uncompiled = final !== null && (!compiled || compiled.tex !== final.tex);
  const canDownload = compiled !== null && compiled.one_page && !uncompiled;
  const fileBase = [FILE_NAME_OWNER, fileSlug(company), "resume"].filter(Boolean).join("_");

  function showError(e: any) {
    setError(e.message || String(e));
    setErrorLog(e.detail?.log || null);
  }

  function showBuildError(e: any) {
    const log: string | null = e.detail?.log || null;
    const line = log?.match(/^l\.(\d+)/m); // pdflatex reports the failing line as "l.93 ..."
    setBuildError({ message: e.message || String(e), log, line: line ? Number(line[1]) : null });
  }

  function resetBuild() {
    setCompiled(null); setBuilt(null); setFinal(null); setBuildError(null);
  }

  // A changed pick makes the built LaTeX out of date. Hand edits are kept, and step 5 says how to rebuild.
  function picksEdited() {
    if (!handEdited) resetBuild();
  }

  const keepsHandEdits = (action: string) =>
    !handEdited || confirm(`${action} replaces the LaTeX you edited by hand in step 5. Continue?`);

  function adopt(r: TailorResult, initial: Decision) {
    setResult(r);
    setDecisions(Object.fromEntries(r.changes.map((c) => [c.id, initial])));
    setEdits({});
    // A reply to the shorten prompt keeps the company already set if it doesn't name one.
    setCompany((c) => r.company || (initial === "accepted" ? c : ""));
    resetBuild();
  }

  function clearAll() {
    if (!keepsHandEdits("Clearing the results")) return;
    setResult(null); setDecisions({}); setEdits({}); setCompany(""); resetBuild();
    setPasted(""); setPasteFor("tailor"); setError(null); setErrorLog(null);
  }

  async function copyPrompt(kind: PromptKind, text: string) {
    setError(null); setErrorLog(null);
    if (!(await copyText(text))) {
      setError("Couldn't copy to the clipboard. Open the prompt under the button, select all of it and copy it yourself.");
      return;
    }
    setPasteFor(kind);
    setCopied(kind);
    setTimeout(() => setCopied((c) => (c === kind ? null : c)), 2500);
  }

  async function runProcess() {
    if (!keepsHandEdits("Processing a new reply")) return;
    setBusy("process"); setError(null); setErrorLog(null);
    try {
      const r = await api.processReply(pasted);
      scrollToReview.current = true;
      adopt(r, pasteFor === "fit" ? "accepted" : "pending");
      setPasteFor("tailor");
      setView("changes");
    } catch (e) { showError(e); } finally { setBusy(null); }
  }

  async function runCompile() {
    if (!keepsHandEdits("Compiling from the accepted changes")) return;
    setBusy("compile"); setBuildError(null);
    const key = acceptedKey;
    try {
      const r = await api.compile(accepted);
      let fitPrompt: string | null = null;
      if (!r.one_page && accepted.length > 0) {
        const items: FitItem[] = changes
          .filter((c) => decisions[c.id] === "accepted")
          .map((c) => ({ id: c.id, section: c.section, kind: c.kind, original: c.original, proposed: textOf(c.id, c.proposed), rationale: c.rationale, keywords: c.keywords }));
        try {
          fitPrompt = (await api.fitPrompt(jd, items, r.pages)).prompt;
        } catch (e) { showBuildError(e); }
      }
      const done = { ...r, fitPrompt };
      setFinal({ tex: r.tex, generatedTex: r.tex, key });
      setCompiled(done);
      setBuilt(done);
      if (r.errors.length) setBuildError({ message: `Some accepted changes could not be applied: ${r.errors.join("; ")}`, log: null, line: null });
    } catch (e: any) {
      setCompiled(null); setBuilt(null);
      // When the combination doesn't compile, load it into the editor so it can be fixed by hand.
      if (e.detail?.tex) setFinal({ tex: e.detail.tex, generatedTex: e.detail.tex, key });
      showBuildError(e);
    } finally { setBusy(null); }
  }

  async function runRecompile() {
    if (!final) return;
    setBusy("recompile"); setBuildError(null);
    try {
      const r = await api.compileTex(final.tex);
      setCompiled({ ...r, fitPrompt: null });
    } catch (e) { showBuildError(e); } finally { setBusy(null); }
  }

  // A click on the PDF selects the LaTeX that printed it. The PDF can be older than the editor's
  // text, so the line is followed through the edits made since that compile.
  async function showInEditor(click: PdfClick) {
    if (!compiled || !final) return;
    try {
      const spot = await api.sourceAt(compiled.id, click);
      const { line, same } = followLine(compiled.tex, final.tex, spot.line);
      setFocusLine({ line, from: same ? spot.start : null, to: same ? spot.end : null, nonce: Date.now() });
    } catch {
      // The text couldn't be traced (say the compiled files were deleted); the editor stays put.
    }
  }

  function undoHandEdits() {
    if (!final) return;
    setFinal({ ...final, tex: final.generatedTex });
    if (built && built.tex === final.generatedTex) setCompiled(built);
    setBuildError(null);
  }

  const decideAll = (d: Decision) => { setDecisions(Object.fromEntries(changes.map((c) => [c.id, d]))); picksEdited(); };

  return (
    <div className="stack">
      <section className="card">
        <h2>1. Paste the job description</h2>
        <textarea
          className="jd"
          value={jd}
          onChange={(e) => setJd(e.target.value)}
          placeholder="Paste the full job description here: role, responsibilities, must-have skills, experience…"
          rows={10}
        />
      </section>

      <section className="card">
        <h2>2. Copy the prompt into Claude</h2>
        <p className="small muted">
          One message with your tailoring prompt (from Settings), your base resume and this job description.
          Paste it into a new chat on claude.ai, pick Opus in the model menu, and send it.
        </p>
        <div className="row">
          <button className="btn primary" disabled={!readyPrompt} onClick={() => readyPrompt && copyPrompt("tailor", readyPrompt)}>
            {copied === "tailor" ? "✓ Copied" : "Copy to Clipboard"}
          </button>
          <a className="btn" href="https://claude.ai/new" target="_blank" rel="noreferrer">Open Claude ↗</a>
          {jdReady && !readyPrompt && promptError ? (
            <span className="small errtext">Couldn&apos;t build the prompt: {promptError}</span>
          ) : (
            <span className="small muted">
              {!jdReady ? "Paste the job description first." : readyPrompt ? `${readyPrompt.length.toLocaleString()} characters` : "Building the prompt…"}
            </span>
          )}
        </div>
        {readyPrompt && (
          <details className="preview">
            <summary className="small">Show the full prompt</summary>
            <textarea className="code" readOnly rows={14} value={readyPrompt} onFocus={(e) => e.currentTarget.select()} />
          </details>
        )}
      </section>

      <section className="card" id="paste">
        <h2>3. Paste Claude&apos;s JSON reply</h2>
        <p className="small muted">
          Use the copy button on the code block in Claude&apos;s reply, then paste it here. A ```json fence or a sentence around the JSON is fine.
        </p>
        {pasteFor === "fit" && (
          <p className="note">ℹ You copied the shorten prompt, so the changes in the next reply you process start out accepted.</p>
        )}
        <textarea
          className="code"
          rows={10}
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          placeholder='{ "company": "…", "summary": "…", "changes": [ … ], "unfillable_gaps": [ … ], "keywords": { … } }'
          spellCheck={false}
        />
        <div className="row">
          <button className="btn primary" disabled={busy !== null || !pasted.trim()} onClick={runProcess}>
            {busy === "process" ? "Processing… (checking each change compiles)" : "Process JSON"}
          </button>
          {(result || pasted) && <button className="btn ghost" onClick={clearAll}>Clear results</button>}
        </div>
      </section>

      {error && (
        <div className="alert error">
          {error}
          {errorLog && <pre className="log">{errorLog}</pre>}
        </div>
      )}

      {result && (
        <>
          <section className="card" id="review">
            <h2>4. Review the proposed changes</h2>
            <p>{result.summary}</p>
            {result.notes.map((n) => <p key={n} className="note">ℹ {n}</p>)}
          </section>

          <div className="grid">
            <div className="stack">
              <div className="toolbar card">
                <div className="seg">
                  <button className={view === "changes" ? "on" : ""} onClick={() => setView("changes")}>Changes ({changes.length})</button>
                  <button className={view === "document" ? "on" : ""} onClick={() => setView("document")}>Full document</button>
                </div>
                {view === "changes" && (
                  <>
                    <div className="seg">
                      <button className={mode === "inline" ? "on" : ""} onClick={() => setMode("inline")}>Inline</button>
                      <button className={mode === "split" ? "on" : ""} onClick={() => setMode("split")}>Side by side</button>
                    </div>
                    <div className="seg">
                      <button className={readable ? "on" : ""} onClick={() => setReadable(true)}>Readable</button>
                      <button className={!readable ? "on" : ""} onClick={() => setReadable(false)}>LaTeX</button>
                    </div>
                  </>
                )}
                <div className="spacer" />
                <span className="small muted">{counts.accepted} accepted · {counts.discarded} discarded · {counts.pending} pending</span>
                <button className="btn ok small-btn" onClick={() => decideAll("accepted")}>Accept all</button>
                <button className="btn no small-btn" onClick={() => decideAll("discarded")}>Discard all</button>
              </div>

              {view === "changes" ? (
                changes.length === 0 ? (
                  <p className="card muted">No usable changes in this reply.</p>
                ) : (
                  changes.map((c) => (
                    <ChangeCard
                      key={c.id}
                      change={c}
                      decision={decisions[c.id] ?? "pending"}
                      proposed={textOf(c.id, c.proposed)}
                      mode={mode}
                      readable={readable}
                      onDecide={(d) => { setDecisions((s) => ({ ...s, [c.id]: d })); picksEdited(); }}
                      onEdit={(t) => { setEdits((s) => ({ ...s, [c.id]: t })); picksEdited(); }}
                    />
                  ))
                )
              ) : (
                <FullDiff before={bodyOf(result.base_resume)} after={bodyOf(previewTex)} />
              )}
              <RejectedPanel rejected={result.rejected} />
            </div>

            <aside className="stack">
              <KeywordPanel k={result.keywords} />
              <GapsPanel gaps={result.unfillable_gaps} />
            </aside>
          </div>

          <section className="card" id="build">
            <h2>5. Build the PDF</h2>
            <p className="small muted">
              Compiles your base LaTeX with only the accepted changes. You can then edit the LaTeX by hand and recompile before
              downloading. Hand edits change only this tailored version, never your base resume. The PDF must fit on one page.
            </p>
            <div className="row">
              <button className="btn primary" disabled={busy !== null} onClick={runCompile}>
                {busy === "compile" ? "Compiling…" : `Compile with ${counts.accepted} change(s)`}
              </button>
              {picksChanged && handEdited && (
                <span className="warn">Your accepted changes changed after you edited the LaTeX. Compile again to use them; that replaces your hand edits.</span>
              )}
            </div>

            {buildError && (
              <div className="alert error">
                {buildError.message}
                {buildError.log && <pre className="log">{buildError.log}</pre>}
                {buildError.line !== null && final && (
                  <button className="btn small-btn jump" onClick={() => setFocusLine({ line: buildError.line!, nonce: Date.now() })}>
                    Go to line {buildError.line} in the editor
                  </button>
                )}
              </div>
            )}

            {final && (
              <>
                <div className="build-grid">
                  <div className="stack tight0">
                    <div className="pane-bar">
                      <strong>LaTeX</strong>
                      <span className="small muted">{handEdited ? "Edited by hand" : "Built from your accepted changes"}</span>
                      <div className="spacer" />
                      {handEdited && <button className="btn ghost small-btn" onClick={undoHandEdits}>Undo hand edits</button>}
                      <button className="btn primary small-btn" disabled={busy !== null || !uncompiled} onClick={runRecompile}>
                        {busy === "recompile" ? "Compiling…" : "Recompile"}
                      </button>
                    </div>
                    <LatexEditor value={final.tex} onChange={(tex) => setFinal((f) => (f ? { ...f, tex } : f))} focusLine={focusLine} />
                  </div>
                  <div className="stack tight0">
                    <div className="pane-bar">
                      <strong>PDF</strong>
                      <span className="small muted">
                        {!compiled
                          ? "Recompile to see it"
                          : `${compiled.pages} page${compiled.pages > 1 ? "s" : ""}${uncompiled ? " · before your latest edits" : ""} · click any text to find it in the LaTeX`}
                      </span>
                      <div className="spacer" />
                      {compiled && <a className="btn ghost small-btn" href={fileUrl(compiled.pdf_url)} target="_blank" rel="noreferrer">Open ↗</a>}
                    </div>
                    {compiled ? (
                      <PdfPreview url={fileUrl(compiled.pdf_url)} onPick={showInEditor} />
                    ) : (
                      <div className="pdf-empty">No PDF yet for this LaTeX.</div>
                    )}
                  </div>
                </div>

                <div className="build-status">
                  {!compiled ? (
                    <p className="warn">There&apos;s no PDF for this LaTeX yet. Fix it if needed, then press Recompile.</p>
                  ) : uncompiled ? (
                    <p className="warn">The LaTeX has edits that aren&apos;t compiled yet. Press Recompile to check them before downloading.</p>
                  ) : compiled.one_page ? (
                    <p className="okmsg">✓ Fits on one page.</p>
                  ) : accepted.length === 0 && !handEdited ? (
                    <p className="warn">Your base resume itself runs to {compiled.pages} pages. Shorten it on the Base Resume page.</p>
                  ) : handEdited || !compiled.fitPrompt ? (
                    <p className="warn">This version runs to {compiled.pages} pages. Shorten the LaTeX and press Recompile.</p>
                  ) : (
                    <div className="stack tight0">
                      <p className="warn">
                        This version runs to {compiled.pages} pages. Discard a longer change, shorten something in the LaTeX, or have
                        Claude tighten the accepted changes.
                      </p>
                      <div className="row">
                        <button className="btn primary" onClick={() => compiled.fitPrompt && copyPrompt("fit", compiled.fitPrompt)}>
                          {copied === "fit" ? "✓ Copied" : "Copy shorten prompt"}
                        </button>
                        <span className="small muted">
                          Paste it into Claude (the same chat is fine), then paste the reply in <a href="#paste">step 3</a> and press Process JSON.
                          The shortened changes come back already accepted.
                        </span>
                      </div>
                      <details className="preview">
                        <summary className="small">Show the shorten prompt</summary>
                        <textarea className="code" readOnly rows={8} value={compiled.fitPrompt} onFocus={(e) => e.currentTarget.select()} />
                      </details>
                    </div>
                  )}
                </div>

                <div className="download-bar">
                  <label className="field">
                    Company
                    <input type="text" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Company name" />
                  </label>
                  <span className="small muted">Saves as <code>{fileBase}.pdf</code></span>
                  <div className="spacer" />
                  {canDownload ? (
                    <>
                      <a className="btn ok" href={fileUrl(compiled!.pdf_url, true, fileBase)}>Download PDF</a>
                      <a className="btn ghost" href={fileUrl(compiled!.tex_url, true, fileBase)}>Download .tex</a>
                    </>
                  ) : (
                    <span className="small muted">Download appears once the compiled PDF fits on one page.</span>
                  )}
                </div>
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
