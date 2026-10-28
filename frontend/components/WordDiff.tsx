"use client";
import { diffWordsWithSpace } from "diff";
import { useMemo } from "react";

export type DiffMode = "inline" | "split";

export function WordDiff({ before, after, mode }: { before: string; after: string; mode: DiffMode }) {
  const parts = useMemo(() => diffWordsWithSpace(before, after), [before, after]);

  if (mode === "inline") {
    return (
      <pre className="diff">
        {parts.map((p, i) => (
          <span key={i} className={p.added ? "add" : p.removed ? "del" : undefined}>
            {p.value}
          </span>
        ))}
      </pre>
    );
  }
  return (
    <div className="split">
      <div>
        <div className="split-label">Original</div>
        <pre className="diff">
          {parts.filter((p) => !p.added).map((p, i) => (
            <span key={i} className={p.removed ? "del" : undefined}>{p.value}</span>
          ))}
        </pre>
      </div>
      <div>
        <div className="split-label">Proposed</div>
        <pre className="diff">
          {after === "" ? <em className="muted">(removed)</em> : parts.filter((p) => !p.removed).map((p, i) => (
            <span key={i} className={p.added ? "add" : undefined}>{p.value}</span>
          ))}
        </pre>
      </div>
    </div>
  );
}
