"use client";
import { useEffect, useRef } from "react";
import { EditorView, basicSetup } from "codemirror";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";
import { tags } from "@lezer/highlight";

// Colours come from CSS variables in globals.css, so the editor follows light and dark mode.
const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", backgroundColor: "var(--code-bg)", color: "var(--text)" },
  ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", lineHeight: "1.5" },
  ".cm-gutters": { backgroundColor: "var(--card)", color: "var(--muted)", borderRight: "1px solid var(--border)" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "var(--hl-active)" },
  ".cm-cursor": { borderLeftColor: "var(--text)" },
  // As specific as CodeMirror's own focused-selection rule, so dark mode doesn't get its light colour.
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "var(--hl-selection)",
  },
  ".cm-matchingBracket": { backgroundColor: "var(--hl-selection)", outline: "none" },
  "&.cm-focused": { outline: "none" },
});

const highlight = HighlightStyle.define([
  { tag: tags.tagName, color: "var(--hl-command)" },
  { tag: [tags.atom, tags.number], color: "var(--hl-atom)" },
  { tag: tags.keyword, color: "var(--hl-math)" },
  { tag: tags.comment, color: "var(--hl-comment)", fontStyle: "italic" },
  { tag: tags.bracket, color: "var(--hl-bracket)" },
  { tag: tags.invalid, color: "var(--no)" },
]);

// A place to select and scroll to: a line (from 1), e.g. the one a LaTeX error points at, and
// optionally the characters from..to within it. The nonce repeats a jump to the same place.
export interface EditorJump {
  line: number;
  from?: number | null;
  to?: number | null;
  nonce: number;
}

interface Props {
  value: string;
  onChange: (tex: string) => void;
  focusLine?: EditorJump | null;
}

export function LatexEditor({ value, onChange, focusLine }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const v = new EditorView({
      parent: host.current!,
      doc: value,
      extensions: [
        basicSetup,
        StreamLanguage.define(stex),
        syntaxHighlighting(highlight),
        EditorView.lineWrapping,
        theme,
        EditorView.contentAttributes.of({ "aria-label": "LaTeX source of the tailored resume" }),
        EditorView.updateListener.of((u) => { if (u.docChanged) onChangeRef.current(u.state.doc.toString()); }),
      ],
    });
    view.current = v;
    // Open at the document body: the preamble rarely needs hand edits.
    const body = value.indexOf("\\begin{document}");
    if (body > 0) v.dispatch({ selection: { anchor: body }, effects: EditorView.scrollIntoView(body, { y: "start", yMargin: 8 }) });
    return () => { v.destroy(); view.current = null; };
    // The document is created once; later outside changes arrive through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A new build or "Undo hand edits" replaces the whole document.
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    const v = view.current;
    if (!v || !focusLine) return;
    const line = v.state.doc.line(Math.min(Math.max(1, focusLine.line), v.state.doc.lines));
    const { from, to } = focusLine;
    const range = from != null && to != null && from < to && to <= line.length
      ? { anchor: line.from + from, head: line.from + to }
      : { anchor: line.from, head: line.to };
    v.dispatch({ selection: range, effects: EditorView.scrollIntoView(range.anchor, { y: "center" }) });
    v.focus();
    // On narrow screens the editor sits above the PDF, so bring it into view.
    host.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusLine]);

  return <div ref={host} className="latex-editor" />;
}
