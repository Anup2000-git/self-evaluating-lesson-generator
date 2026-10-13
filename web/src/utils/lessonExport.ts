import type { Lesson } from "../api/types";

const escape = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Minimal Markdown -> HTML for clipboard export (bold, lists, tables, quotes, paragraphs). */
function inline(text: string): string {
  return escape(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*(?!\s)(.+?)\*(?=[\s).,!?]|$)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

export function markdownToHtml(markdown: string): string {
  const lines = markdown.replace(/\r/g, "").split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (/^\|.*\|\s*$/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) {
        const cells = lines[i].trim().slice(1, -1).split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{3,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      out.push(
        `<table border="1" cellpadding="6" style="border-collapse:collapse"><thead><tr>${head
          .map((c) => `<th>${inline(c)}</th>`)
          .join("")}</tr></thead><tbody>${body
          .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`)
          .join("")}</tbody></table>`,
      );
      continue;
    }
    if (/^\s*([-*]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*]|\d+[.)])\s+/.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(/^\s*([-*]|\d+[.)])\s+/, ""))}</li>`);
        i++;
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quote.push(inline(lines[i].replace(/^>\s?/, "")));
        i++;
      }
      out.push(`<blockquote>${quote.join("<br/>")}</blockquote>`);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 6);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(\||>|#|\s*([-*]|\d+[.)])\s)/.test(lines[i])) {
      paragraph.push(inline(lines[i]));
      i++;
    }
    out.push(`<p>${paragraph.join(" ")}</p>`);
  }
  return out.join("\n");
}

export function lessonToMarkdown(lesson: Lesson, helperLanguage = "Hindi"): string {
  const parts = [`# ${lesson.title}`, ""];
  if (lesson.learning_objectives.length) {
    parts.push("**By the end of this lesson, you will be able to:**", "");
    lesson.learning_objectives.forEach((o) => parts.push(`- ${o}`));
    parts.push("");
  }
  lesson.sections.forEach((s) => parts.push(`## ${s.heading}`, "", s.body_markdown.trim(), ""));
  if (lesson.glossary.length) {
    parts.push("## Key words (Glossary)", "", `| Word | Simple meaning | ${helperLanguage} |`, "|---|---|---|");
    lesson.glossary.forEach((g) => parts.push(`| **${g.term}** | ${g.simple_meaning} | ${g.helper_meaning} |`));
    parts.push("");
  }
  if (lesson.quiz.length) {
    parts.push("## Check your understanding", "");
    lesson.quiz.forEach((q, i) => {
      parts.push(`**${i + 1}. ${q.question}**`, "");
      q.options.forEach((o, j) => parts.push(`- ${String.fromCharCode(65 + j)}) ${o}`));
      parts.push("");
    });
    parts.push("### Answers", "");
    lesson.quiz.forEach((q, i) =>
      parts.push(`${i + 1}. **${String.fromCharCode(65 + q.correct_option_index)}** - ${q.explanation}`),
    );
  }
  return parts.join("\n").trim() + "\n";
}

/** Copies the lesson as rich text (pastes formatted into Google Docs) plus a Markdown fallback. */
export async function copyLessonForDocs(lesson: Lesson, helperLanguage = "Hindi"): Promise<void> {
  const markdown = lessonToMarkdown(lesson, helperLanguage);
  const html = `<meta charset="utf-8">${markdownToHtml(markdown)}`;
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([markdown], { type: "text/plain" }),
      }),
    ]);
    return;
  }
  await navigator.clipboard.writeText(markdown);
}

export function downloadText(filename: string, text: string, type = "text/markdown"): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
