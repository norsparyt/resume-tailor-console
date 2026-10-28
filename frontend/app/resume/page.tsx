"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

export default function ResumePage() {
  const [tex, setTex] = useState("");
  const [saved, setSaved] = useState("");
  const [versions, setVersions] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ kind: "ok" | "error" | "warn"; text: string; log?: string } | null>(null);
  const [canForce, setCanForce] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pending = useRef<File | null>(null);

  const refresh = async () => {
    const [r, h] = await Promise.all([api.getResume(), api.history()]);
    setTex(r.tex); setSaved(r.tex); setVersions(h.versions);
  };
  useEffect(() => { refresh().catch((e) => setMsg({ kind: "error", text: e.message })); }, []);

  function handle(e: unknown) {
    const err = e as ApiError;
    setMsg({ kind: "error", text: err.message, log: err.detail?.log });
    setCanForce(err.status === 422);
  }

  function afterSave(r: { pages: number | null; warning: string | null }) {
    setCanForce(false);
    setMsg(r.warning ? { kind: "warn", text: r.warning } : { kind: "ok", text: `Saved. Compiles to ${r.pages} page.` });
    setPdfUrl(null);
    refresh();
  }

  async function save(force = false) {
    setBusy(true); setMsg(null);
    try {
      afterSave(pending.current ? await api.uploadResume(pending.current, force) : await api.saveResume(tex, force));
      pending.current = null;
    } catch (e) { handle(e); } finally { setBusy(false); }
  }

  async function onUpload(file: File) {
    pending.current = file;
    setBusy(true); setMsg(null);
    try {
      afterSave(await api.uploadResume(file));
      pending.current = null;
    } catch (e) {
      setTex(await file.text());
      handle(e);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function restore(name: string) {
    if (!confirm(`Restore ${name}? The current base resume is archived first.`)) return;
    try {
      await api.restoreVersion(name);
      setMsg({ kind: "ok", text: `Restored ${name}.` });
      refresh();
    } catch (e) { handle(e); }
  }

  const dirty = tex !== saved;

  return (
    <div className="stack">
      <section className="card">
        <h2>Base resume (LaTeX)</h2>
        <p className="small muted">
          This is the source every tailored version starts from. It must compile to exactly one page. Every save archives the previous version below.
        </p>
        <div className="row">
          <button className="btn primary" disabled={busy || !dirty} onClick={() => { pending.current = null; save(); }}>Save changes</button>
          <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>Replace with a .tex file…</button>
          <input ref={fileRef} type="file" accept=".tex" hidden onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
          <button className="btn ghost" onClick={() => setPdfUrl(api.baseResumePdfUrl())}>Preview PDF</button>
          {dirty && <button className="btn ghost" onClick={() => setTex(saved)}>Discard edits</button>}
        </div>
        {msg && (
          <div className={`alert ${msg.kind}`}>
            {msg.text}
            {msg.log && <pre className="log">{msg.log}</pre>}
            {canForce && msg.kind === "error" && (
              <div><button className="btn small-btn" onClick={() => save(true)}>Save anyway</button></div>
            )}
          </div>
        )}
        <textarea className="code" value={tex} onChange={(e) => { pending.current = null; setTex(e.target.value); }} spellCheck={false} rows={32} />
      </section>

      {pdfUrl && (
        <section className="card">
          <h3>Base resume preview</h3>
          <iframe className="pdf" src={pdfUrl} title="Base resume PDF" />
        </section>
      )}

      <section className="card">
        <h3>Previous versions</h3>
        {versions.length === 0 ? <p className="muted small">No previous versions yet.</p> : (
          <ul className="versions">
            {versions.map((v) => (
              <li key={v}>
                <code>{v}</code>
                <button className="btn ghost small-btn" onClick={() => restore(v)}>Restore</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
