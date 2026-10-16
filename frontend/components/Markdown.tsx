import { Fragment, type ComponentProps, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  splitTables,
  type Align,
  type MarkdownTableData,
} from "@/lib/markdown";
import { cn } from "@/lib/utils";
import { InlineMarkdown } from "./InlineMarkdown";

// Block-level renderers for markdown from ingested (untrusted) documents. None of them renders raw
// HTML (react-markdown shows it as text), images are dropped, and only http(s)/mailto links are
// live, opening in a new tab.

// --- Document bodies ----------------------------------------------------------

const DOCUMENT_COMPONENTS: Components = {
  a: SafeLink,
  table: ({ children }) => (
    <div className="w-full overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
};

/** A full markdown document (compiled truth, timeline), styled by `.markdown` in globals.css. */
export function DocumentMarkdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        disallowedElements={["img"]}
        components={DOCUMENT_COMPONENTS}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function SafeLink({ href, title, children }: ComponentProps<"a">) {
  if (!href || !/^(https?:|mailto:)/i.test(href))
    return <span>{children}</span>;
  return (
    <a href={href} title={title} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  );
}

// --- Claims and quotes ----------------------------------------------------------

/**
 * A claim or quote: inline markdown, except that a markdown table (which the extractive composer
 * cites verbatim) renders as a compact table. May return block content; wrap it in a <div>.
 */
export function SnippetMarkdown({
  text,
  tableClassName,
}: {
  text: string;
  tableClassName?: string;
}) {
  const segments = splitTables(text);
  if (segments.every((segment) => segment.kind === "text"))
    return <InlineMarkdown text={text} />;
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === "table" ? (
          <MarkdownTable
            key={index}
            table={segment.table}
            className={cn("my-1", tableClassName)}
          />
        ) : (
          <span key={index} className="block">
            <InlineMarkdown text={segment.text} />
          </span>
        ),
      )}
    </>
  );
}

// --- Composed answers -------------------------------------------------------------

// A composed answer is claims each followed by evidence markers ("… [E1][E3] …").
const MARKER_RUN = /((?:\s*\[E\d+\])+)/;

/**
 * A composed answer: claims flow as one paragraph with their evidence markers; a claim that is a
 * markdown table breaks out as a table with its markers underneath. Each claim renders on its
 * own, so a stray "**" in one cannot bleed into the next.
 */
export function AnswerMarkdown({
  text,
  className,
  tableClassName,
}: {
  text: string;
  className?: string;
  tableClassName?: string;
}) {
  const blocks: ReactNode[] = [];
  let run: ReactNode[] = [];
  const flush = () => {
    if (run.length > 0) blocks.push(<p key={blocks.length}>{run}</p>);
    run = [];
  };

  const parts = text.split(MARKER_RUN);
  for (let i = 0; i < parts.length; i += 2) {
    const markers = parts[i + 1]?.replace(/\s+/g, "") ?? "";
    const segments = splitTables(parts[i]);
    const last = segments.at(-1);
    for (const segment of segments) {
      if (segment.kind === "table") {
        flush();
        blocks.push(
          <figure key={blocks.length}>
            <MarkdownTable table={segment.table} className={tableClassName} />
            {segment === last && markers && (
              <figcaption className="mt-1">
                <Markers markers={markers} />
              </figcaption>
            )}
          </figure>,
        );
      } else {
        run.push(
          <Fragment key={`${i}:${run.length}`}>
            <InlineMarkdown text={segment.text} />
            {segment === last && markers && (
              // A word joiner keeps the markers on the line of the claim they cite.
              <>
                {"\u2060"}
                <Markers markers={markers} />
              </>
            )}{" "}
          </Fragment>,
        );
      }
    }
    if (markers && !last)
      run.push(<Markers key={`${i}:m`} markers={markers} />);
  }
  flush();

  return <div className={cn("space-y-4", className)}>{blocks}</div>;
}

function Markers({ markers }: { markers: string }) {
  return (
    <span className="ml-1 font-mono text-xs text-neutral-400">{markers}</span>
  );
}

// --- Tables -------------------------------------------------------------------------

const ALIGN_CLASS: Record<NonNullable<Align>, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

/** Compact table in the hairline style of `.markdown table`; cells are inline markdown. */
function MarkdownTable({
  table,
  className,
}: {
  table: MarkdownTableData;
  className?: string;
}) {
  const cellClass = (column: number) =>
    cn(
      "px-2 py-1.5 align-top",
      ALIGN_CLASS[table.align[column] ?? "left"],
    );
  return (
    <div className={cn("w-full overflow-x-auto text-sm", className)}>
      <table className="w-full border-collapse leading-snug">
        <thead className="border-b border-neutral-300 text-xs text-neutral-500">
          <tr>
            {table.header.map((cell, column) => (
              <th key={column} className={cn(cellClass(column), "font-normal")}>
                <InlineMarkdown text={cell} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-200">
          {table.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, column) => (
                <td key={column} className={cellClass(column)}>
                  <InlineMarkdown text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
