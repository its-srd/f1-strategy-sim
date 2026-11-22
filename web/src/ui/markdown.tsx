// Minimal Markdown renderer for docs/assumptions.md (headings, tables, lists,
// paragraphs, bold, inline code, links). Escapes HTML first.
function esc(s: string) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function inline(s: string) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])_([^_]+)_(?=[\s.,;:)]|$)/g, "$1<i>$2</i>")
    .replace(/\\\*/g, "*")
    .replace(/\\\|/g, "|")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
const cells = (line: string) => line.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => inline(c.trim()));

export function renderMarkdown(md: string): string {
  const lines = md.replace(/<!--.*?-->/g, "").split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (/^#{1,6} /.test(l)) { const n = l.match(/^#+/)![0].length; out.push(`<h${n}>${inline(l.slice(n + 1))}</h${n}>`); i++; continue; }
    if (l.trim().startsWith("|") && lines[i + 1]?.match(/^\s*\|[\s:|-]+\|\s*$/)) {
      const head = cells(l); i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) { rows.push(cells(lines[i])); i++; }
      out.push(`<table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (/^\s*[*-] /.test(l)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[*-] /.test(lines[i])) {
        let item = lines[i].replace(/^\s*[*-] /, ""); i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*[*-] /.test(lines[i])) { item += " " + lines[i].trim(); i++; }
        items.push(inline(item));
      }
      out.push(`<ul>${items.map((x) => `<li>${x}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+\. /.test(l)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\. /.test(lines[i])) {
        let item = lines[i].replace(/^\s*\d+\. /, ""); i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*\d+\. /.test(lines[i])) { item += " " + lines[i].trim(); i++; }
        items.push(inline(item));
      }
      out.push(`<ol>${items.map((x) => `<li>${x}</li>`).join("")}</ol>`);
      continue;
    }
    if (l.trim() === "") { i++; continue; }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !/^#{1,6} /.test(lines[i]) && !lines[i].trim().startsWith("|") && !/^\s*[*-] /.test(lines[i]) && !/^\s*\d+\. /.test(lines[i])) { para.push(lines[i]); i++; }
    out.push(`<p>${inline(para.join(" "))}</p>`);
  }
  return out.join("\n");
}
