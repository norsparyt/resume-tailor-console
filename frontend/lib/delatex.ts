// Turns resume LaTeX into readable text for the review view. Display only; never sent back.
export function delatex(tex: string): string {
  return tex
    .replace(/(^|[^\\])%.*$/gm, "$1")
    .replace(/\\resumeItem\s*\{/g, "\n• {")
    .replace(/\\item\b/g, "\n• ")
    .replace(/\\(href)\{[^}]*\}/g, "")
    .replace(/\\(vspace|hspace)\*?\{[^}]*\}/g, "")
    .replace(/\\\\/g, "\n")
    .replace(/\\([%&$#_{}])/g, "$1")
    .replace(/\$\|\$/g, "|")
    .replace(/--/g, "–")
    .replace(/\\[a-zA-Z]+\*?/g, "")
    .replace(/[{}]/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/\n\s*\n+/g, "\n")
    .trim();
}
