"use client";
import { useState } from "react";
import type { Change } from "@/lib/api";
import { delatex } from "@/lib/delatex";
import { WordDiff, type DiffMode } from "./WordDiff";

export type Decision = "pending" | "accepted" | "discarded";

interface Props {
  change: Change;
  decision: Decision;
  proposed: string; // possibly edited by the user
  mode: DiffMode;
  readable: boolean;
  onDecide: (d: Decision) => void;
  onEdit: (text: string) => void;
}

export function ChangeCard({ change, decision, proposed, mode, readable, onDecide, onEdit }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(proposed);
  const edited = proposed !== change.proposed;
  const before = readable ? delatex(change.original) : change.original;
  const after = readable ? delatex(proposed) : proposed;

  return (
    <article className={`card change ${decision}`}>
      <header className="change-head">
        <div>
          <span className="tag">{change.kind}</span>
          <strong>{change.section}</strong>
          {edited && <span className="tag edited">edited</span>}
        </div>
        <div className="actions">
          <button className={decision === "accepted" ? "btn ok active" : "btn ok"} onClick={() => onDecide(decision === "accepted" ? "pending" : "accepted")}>
            {decision === "accepted" ? "✓ Accepted" : "Accept"}
          </button>
          <button className={decision === "discarded" ? "btn no active" : "btn no"} onClick={() => onDecide(decision === "discarded" ? "pending" : "discarded")}>
            {decision === "discarded" ? "✕ Discarded" : "Discard"}
          </button>
          <button className="btn ghost" onClick={() => { setDraft(proposed); setEditing(!editing); }}>
            {editing ? "Close editor" : "Edit"}
          </button>
        </div>
      </header>

      <p className="rationale">{change.rationale}</p>
      {change.keywords.length > 0 && (
        <div className="chips">{change.keywords.map((k) => <span key={k} className="chip good">{k}</span>)}</div>
      )}
      {change.warnings.map((w) => <p key={w} className="warn">⚠ {w}</p>)}

      <WordDiff before={before} after={after} mode={mode} />

      {editing && (
        <div className="editor">
          <label>Proposed LaTeX</label>
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={Math.min(12, draft.split("\n").length + 2)} spellCheck={false} />
          <div className="actions">
            <button className="btn primary" onClick={() => { onEdit(draft); setEditing(false); onDecide("accepted"); }}>Save and accept</button>
            <button className="btn ghost" onClick={() => { onEdit(change.proposed); setDraft(change.proposed); }}>Revert to AI version</button>
          </div>
        </div>
      )}
    </article>
  );
}
