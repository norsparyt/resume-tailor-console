"use client";
import { diffLines } from "diff";
import { useMemo } from "react";

// Side-by-side, line-level view of the whole LaTeX document.
export function FullDiff({ before, after }: { before: string; after: string }) {
  const rows = useMemo(() => {
    const out: { l?: string; r?: string; kind: "same" | "del" | "add" | "mod" }[] = [];
    const parts = diffLines(before, after);
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i];
      const lines = p.value.replace(/\n$/, "").split("\n");
      if (p.removed && parts[i + 1]?.added) {
        const next = parts[i + 1].value.replace(/\n$/, "").split("\n");
        const n = Math.max(lines.length, next.length);
        for (let j = 0; j < n; j++) out.push({ l: lines[j], r: next[j], kind: "mod" });
        i++;
      } else if (p.removed) lines.forEach((l) => out.push({ l, kind: "del" }));
      else if (p.added) lines.forEach((r) => out.push({ r, kind: "add" }));
      else lines.forEach((l) => out.push({ l, r: l, kind: "same" }));
    }
    return out;
  }, [before, after]);

  return (
    <div className="fulldiff">
      <table>
        <thead><tr><th>Base resume</th><th>With accepted changes</th></tr></thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={row.kind}>
              <td className={row.kind === "del" || row.kind === "mod" ? "del" : ""}>{row.l ?? ""}</td>
              <td className={row.kind === "add" || row.kind === "mod" ? "add" : ""}>{row.r ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
