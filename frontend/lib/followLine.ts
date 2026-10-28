import { diffLines } from "diff";

// Where line (from 1) of before is in after, following the edits made in between. same is false
// when that line was changed or deleted; it then maps to where its replacement starts.
export function followLine(before: string, after: string, line: number): { line: number; same: boolean } {
  if (before === after) return { line, same: true };
  let a = 1;
  let b = 1;
  for (const part of diffLines(before, after)) {
    const n = part.count ?? 0;
    if (part.added) {
      b += n;
      continue;
    }
    if (line < a + n) return part.removed ? { line: b, same: false } : { line: b + (line - a), same: true };
    a += n;
    if (!part.removed) b += n;
  }
  return { line: Math.max(1, b - 1), same: false };
}
