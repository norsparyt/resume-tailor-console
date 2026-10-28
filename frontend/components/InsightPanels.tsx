"use client";
import type { Gap, Keywords, RejectedChange } from "@/lib/api";

export function GapsPanel({ gaps }: { gaps: Gap[] }) {
  return (
    <section className="card gaps">
      <h3>Unfillable Gaps <span className="count">{gaps.length}</span></h3>
      <p className="muted small">JD requirements your base resume can't truthfully meet. These were not added to the resume.</p>
      {gaps.length === 0 ? (
        <p className="muted">None. Your resume covers every key requirement.</p>
      ) : (
        <ul className="gap-list">
          {gaps.map((g, i) => (
            <li key={i}>
              <span className={`tag imp-${g.importance}`}>{g.importance}</span> <strong>{g.requirement}</strong>
              <div className="small">{g.reason}</div>
              {g.suggestion && <div className="small muted">Tip: {g.suggestion}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function KeywordPanel({ k }: { k: Keywords }) {
  const row = (label: string, list: string[], cls: string) =>
    list.length > 0 && (
      <div className="kw-row">
        <div className="small muted">{label}</div>
        <div className="chips">{list.map((w) => <span key={w} className={`chip ${cls}`}>{w}</span>)}</div>
      </div>
    );
  const total = k.jd_keywords.length || 1;
  const covered = new Set([...k.already_present, ...k.surfaced_by_changes].map((s) => s.toLowerCase()));
  const pct = Math.round((k.jd_keywords.filter((w) => covered.has(w.toLowerCase())).length / total) * 100);
  return (
    <section className="card">
      <h3>ATS keywords <span className="count">{pct}% covered</span></h3>
      {row("Already in resume", k.already_present, "neutral")}
      {row("Surfaced by changes", k.surfaced_by_changes, "good")}
      {row("Missing (not truthful to add)", k.missing, "bad")}
    </section>
  );
}

export function RejectedPanel({ rejected }: { rejected: RejectedChange[] }) {
  if (rejected.length === 0) return null;
  return (
    <details className="card">
      <summary>{rejected.length} suggestion(s) from Claude's reply were dropped automatically</summary>
      <ul className="small">
        {rejected.map((r, i) => <li key={`${r.id}-${i}`}><strong>{r.section || r.id}</strong>: {r.reason}</li>)}
      </ul>
    </details>
  );
}
