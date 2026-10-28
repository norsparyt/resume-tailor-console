"use client";
import { useEffect, useRef, useState } from "react";
import type { PageViewport } from "pdfjs-dist/legacy/build/pdf.mjs";

// A click on text in the preview: the page (from 1), the point in PDF points from the page's
// top-left corner, the run of text under it and the word clicked.
export interface PdfClick {
  page: number;
  x: number;
  y: number;
  text: string;
  word: string;
}

// A run of text on the page, in PDF user space (origin at the bottom left).
interface Run {
  str: string;
  x0: number;
  x1: number;
  baseline: number;
  size: number;
}

interface Page {
  n: number;
  view: number[];
  viewport: PageViewport;
  runs: Run[];
  canvas: HTMLCanvasElement;
}

// pdf.js needs browser APIs, so it loads on first use instead of during server rendering. Loading
// its worker module as well lets it parse on the page's own thread, which needs no worker URL setup
// and is quick for a one-page resume.
let pdfjs: Promise<typeof import("pdfjs-dist/legacy/build/pdf.mjs")> | null = null;
function loadPdfjs() {
  pdfjs ??= Promise.all([
    import("pdfjs-dist/legacy/build/pdf.mjs"),
    // @ts-ignore: the worker build ships without type declarations.
    import("pdfjs-dist/legacy/build/pdf.worker.min.mjs"),
  ]).then(([lib]) => lib);
  return pdfjs;
}

function toRun(item: { str: string; transform: number[]; width: number }): Run {
  const [a, b, c, d, e, f] = item.transform;
  return { str: item.str, x0: e, x1: e + item.width, baseline: f, size: Math.hypot(c, d) || Math.hypot(a, b) };
}

// The run under a point, allowing a couple of points of slack around each line of text.
function runAt(runs: Run[], x: number, y: number): Run | null {
  let best: Run | null = null;
  let bestGap = 2;
  for (const r of runs) {
    const dx = Math.max(r.x0 - x, 0, x - r.x1);
    const dy = Math.max(r.baseline - 0.25 * r.size - y, 0, y - (r.baseline + 0.85 * r.size));
    if (dx + dy <= bestGap) {
      best = r;
      bestGap = dx + dy;
    }
  }
  return best;
}

let ruler: CanvasRenderingContext2D | null = null;
// Width of the first n characters as a share of the whole run, measured in a serif font, which
// spaces letters much like the PDF does.
function share(str: string, n: number): number {
  ruler ??= document.createElement("canvas").getContext("2d");
  if (!ruler) return n / str.length;
  ruler.font = "100px serif";
  return ruler.measureText(str.slice(0, n)).width / (ruler.measureText(str).width || 1);
}

// The word at x in a run, with its left and right edges.
function wordAt(run: Run, x: number): { word: string; x0: number; x1: number } {
  const s = run.str;
  const target = (x - run.x0) / (run.x1 - run.x0 || 1);
  let lo = 0;
  let hi = s.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (share(s, mid + 1) <= target) lo = mid + 1;
    else hi = mid;
  }
  let i = lo;
  if (/\s/.test(s[i])) i = i + 1 < s.length && !/\s/.test(s[i + 1]) ? i + 1 : Math.max(0, i - 1);
  let start = i;
  let end = i + 1;
  while (start > 0 && !/\s/.test(s[start - 1])) start--;
  while (end < s.length && !/\s/.test(s[end])) end++;
  const width = run.x1 - run.x0;
  return { word: s.slice(start, end), x0: run.x0 + share(s, start) * width, x1: run.x0 + share(s, end) * width };
}

interface Props {
  url: string;
  onPick: (click: PdfClick) => void;
}

// Draws the PDF with pdf.js so a click on any text can be traced back to the LaTeX.
// Falls back to the browser's own PDF viewer, without click-to-find, if that fails.
export function PdfPreview({ url, onPick }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const [width, setWidth] = useState(0);
  // A failure applies to that PDF only; the next compile tries pdf.js again.
  const [failure, setFailure] = useState<{ url: string; message: string } | null>(null);
  const failed = failure?.url === url ? failure.message : null;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, [failed]);

  useEffect(() => {
    const el = host.current;
    if (!el || width < 100) return;
    let cancelled = false;
    let destroy = () => {};
    const draw = async () => {
      const lib = await loadPdfjs();
      const task = lib.getDocument({ url, verbosity: lib.VerbosityLevel.ERRORS });
      destroy = () => void task.destroy();
      const doc = await task.promise;
      const pages: Page[] = [];
      for (let n = 1; n <= doc.numPages && !cancelled; n++) {
        const page = await doc.getPage(n);
        const viewport = page.getViewport({ scale: (width - 24) / page.getViewport({ scale: 1 }).width });
        const dpr = window.devicePixelRatio || 1;
        const canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        await page.render({ canvas, viewport, transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0] }).promise;
        const text = await page.getTextContent();
        const runs = text.items.flatMap((it) => ("str" in it && it.str.trim() ? [toRun(it)] : []));
        pages.push({ n, view: page.view, viewport, runs, canvas });
      }
      destroy();
      if (!cancelled) el.replaceChildren(...pages.map(pageElement));
    };
    // Waiting a moment lets the size settle while the window is being resized.
    const timer = setTimeout(() => {
      draw().catch((e) => {
        if (!cancelled) setFailure({ url, message: e?.message || String(e) });
      });
    }, 80);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      destroy();
    };
  }, [url, width]);

  function pageElement(p: Page): HTMLElement {
    const box = document.createElement("div");
    box.className = "pdf-page";
    box.append(p.canvas);
    const at = (e: MouseEvent) => {
      const rect = p.canvas.getBoundingClientRect();
      const [x, y] = p.viewport.convertToPdfPoint(e.clientX - rect.left, e.clientY - rect.top);
      return { x, y, run: runAt(p.runs, x, y) };
    };
    box.addEventListener("mousemove", (e) => {
      box.style.cursor = at(e).run ? "pointer" : "";
    });
    box.addEventListener("click", (e) => {
      const { x, run } = at(e);
      if (!run) return;
      const w = wordAt(run, Math.min(Math.max(x, run.x0), run.x1));
      // Mark the word that was picked, briefly.
      const [l, t] = p.viewport.convertToViewportPoint(w.x0, run.baseline + 0.85 * run.size);
      const [r, b] = p.viewport.convertToViewportPoint(w.x1, run.baseline - 0.25 * run.size);
      const mark = document.createElement("div");
      mark.className = "pdf-mark";
      Object.assign(mark.style, { left: `${l}px`, top: `${t}px`, width: `${r - l}px`, height: `${b - t}px` });
      host.current?.querySelectorAll(".pdf-mark").forEach((m) => m.remove());
      box.append(mark);
      // SyncTeX expects points from the top-left corner. The middle of the line keeps the point
      // inside that line's box.
      onPickRef.current({
        page: p.n,
        x: Math.min(Math.max(x, run.x0), run.x1) - p.view[0],
        y: p.view[3] - (run.baseline + 0.3 * run.size),
        text: run.str,
        word: w.word,
      });
    });
    return box;
  }

  if (failed) {
    return (
      <div className="stack tight0">
        <iframe className="pdf" src={url} title="Tailored resume PDF" />
        <p className="small muted">Couldn&apos;t draw the PDF in the page ({failed}), so clicking text won&apos;t find it in the LaTeX.</p>
      </div>
    );
  }
  return <div ref={host} className="pdf-view" aria-label="Tailored resume PDF. Click any text to find it in the LaTeX." />;
}
