// Parsing helpers for markdown lifted out of ingested documents into answers, claims, quotes and
// timelines. The extractive composer cites source text verbatim, so a claim can be a whole GFM
// table, a single table row or a GBrain timeline line ("- **date** | Source — summary").

export type Align = "left" | "center" | "right" | null;

export interface MarkdownTableData {
  header: string[];
  align: Align[];
  rows: string[][];
}

export type MarkdownSegment =
  { kind: "text"; text: string } | { kind: "table"; table: MarkdownTableData };

const DELIMITER_CELL = /^:?-+:?$/;

/** Splits on `|`, skipping escaped pipes (`\|`) and pipes inside code spans. */
function splitPipes(text: string): string[] {
  const cells: string[] = [];
  let current = "";
  let i = 0;
  while (i < text.length) {
    const char = text[i];
    if (char === "\\" && i + 1 < text.length) {
      current += text.slice(i, i + 2);
      i += 2;
    } else if (char === "`") {
      let end = i;
      while (text[end] === "`") end += 1;
      const fence = text.slice(i, end);
      const close = text.indexOf(fence, end);
      // An unmatched backtick run is literal text, so it cannot hide later pipes.
      const stop = close === -1 ? end : close + fence.length;
      current += text.slice(i, stop);
      i = stop;
    } else if (char === "|") {
      cells.push(current);
      current = "";
      i += 1;
    } else {
      current += char;
      i += 1;
    }
  }
  cells.push(current);
  return cells;
}

/** Trimmed cells of a table row, without the empty cells outside its outer pipes. */
function rowCells(line: string): string[] {
  const cells = splitPipes(line.trim());
  if (cells.length > 1 && cells[0].trim() === "") cells.shift();
  if (cells.length > 1 && cells[cells.length - 1].trim() === "") cells.pop();
  return cells.map((cell) => cell.trim());
}

function delimiterAlign(line: string): Align[] | null {
  if (!line.includes("|")) return null;
  const cells = rowCells(line);
  if (!cells.every((cell) => DELIMITER_CELL.test(cell))) return null;
  return cells.map((cell) => {
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    return left ? "left" : null;
  });
}

/** Splits text into prose and GFM tables (header row, delimiter row, then body rows). */
export function splitTables(text: string): MarkdownSegment[] {
  const lines = text.split(/\r?\n/);
  const segments: MarkdownSegment[] = [];
  let prose: string[] = [];
  const flushProse = () => {
    const joined = prose.join("\n");
    if (joined.trim()) segments.push({ kind: "text", text: joined });
    prose = [];
  };

  let i = 0;
  while (i < lines.length) {
    const align =
      i + 1 < lines.length && lines[i].includes("|")
        ? delimiterAlign(lines[i + 1])
        : null;
    const header = align ? rowCells(lines[i]) : null;
    if (!align || !header || header.length !== align.length) {
      prose.push(lines[i]);
      i += 1;
      continue;
    }
    flushProse();
    const rows: string[][] = [];
    i += 2;
    while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
      const cells = rowCells(lines[i]);
      rows.push(header.map((_, column) => cells[column] ?? ""));
      i += 1;
    }
    segments.push({ kind: "table", table: { header, align, rows } });
  }
  flushProse();
  return segments;
}

/**
 * Cells of one-line text that reads as a table row ("| a | b |") or a GBrain timeline line
 * ("**date** | Source — summary"), with delimiter cells dropped; null for ordinary prose.
 */
export function rowLikeCells(text: string): string[] | null {
  if (!/^\||\s\|\s|\|$/.test(text)) return null;
  return rowCells(text).filter((cell) => cell && !DELIMITER_CELL.test(cell));
}

export interface ParsedTimelineEntry {
  date: string;
  source: string | null;
  summary: string;
}

const TIMELINE_HEADING = /^\s*#{1,6}\s+timeline\s*$/im;
const TIMELINE_ITEM = /^[-*+]\s+\*\*([^*]+)\*\*\s*\|\s*(.+)$/;

/** Markdown timeline with its own "## Timeline" heading removed (the card already titles it). */
export function stripTimelineHeading(markdown: string): string {
  return markdown.replace(TIMELINE_HEADING, "").trim();
}

/**
 * GBrain timeline bullets ("- **2026-10-08** | Google Drive — Presented to the board.") as
 * entries; null when any non-blank line is not such a bullet (render the markdown instead).
 */
export function parseTimeline(markdown: string): ParsedTimelineEntry[] | null {
  const items: string[] = [];
  for (const line of stripTimelineHeading(markdown).split(/\r?\n/)) {
    if (!line.trim()) continue;
    if (/^[-*+]\s/.test(line.trim())) items.push(line.trim());
    else if (/^\s+\S/.test(line) && items.length > 0)
      items[items.length - 1] += ` ${line.trim()}`; // wrapped continuation line
    else return null;
  }
  const entries: ParsedTimelineEntry[] = [];
  for (const item of items) {
    const match = TIMELINE_ITEM.exec(item);
    if (!match) return null;
    const rest = match[2].trim();
    const dash = rest.indexOf(" — ");
    entries.push({
      date: match[1].trim(),
      source: dash === -1 ? null : rest.slice(0, dash).trim(),
      summary: dash === -1 ? rest : rest.slice(dash + 3).trim(),
    });
  }
  return entries.length > 0 ? entries : null;
}
