"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const [prompt, setPrompt] = useState("");
  const [saved, setSaved] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  const apply = (r: { prompt: string; is_default: boolean }) => { setPrompt(r.prompt); setSaved(r.prompt); setIsDefault(r.is_default); };
  useEffect(() => { api.getPrompt().then(apply).catch((e) => setMsg(e.message)); }, []);

  return (
    <div className="stack">
      <section className="card">
        <h2>Tailoring prompt</h2>
        <p className="small muted">
          These are the instructions at the top of the prompt you copy into Claude on the Tailor page. {isDefault ? "You are using the default prompt." : "You are using a custom prompt."}{" "}
          The copied prompt always ends with a short fixed block that sets the JSON reply format and blocks unsafe LaTeX, so edits here can't break the diff viewer.
        </p>
        <textarea className="code" rows={34} value={prompt} onChange={(e) => setPrompt(e.target.value)} spellCheck={false} />
        <div className="row">
          <button className="btn primary" disabled={prompt === saved} onClick={async () => { apply(await api.savePrompt(prompt)); setMsg("Saved."); }}>Save prompt</button>
          <button className="btn" disabled={isDefault && prompt === saved} onClick={async () => {
            if (!confirm("Reset to the default prompt? Your custom prompt will be lost.")) return;
            apply(await api.resetPrompt()); setMsg("Reset to default.");
          }}>Reset to default</button>
          {prompt !== saved && <button className="btn ghost" onClick={() => setPrompt(saved)}>Discard edits</button>}
          {msg && <span className="small muted">{msg}</span>}
        </div>
      </section>
    </div>
  );
}
