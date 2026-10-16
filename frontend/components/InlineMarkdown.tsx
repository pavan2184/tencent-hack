import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { rowLikeCells } from "@/lib/markdown";

// Answer, claim and quote text is lifted from ingested (untrusted) documents, so it renders as
// inline emphasis only: block structure is flattened into the surrounding text, links show as
// plain text and images are dropped (an image URL would fetch on render). Whole tables are
// handled by the block renderers in ./Markdown.
const INLINE_ELEMENTS = ["strong", "em", "del", "code"];

/** Inline markdown for text that sits inside an existing paragraph. */
export function InlineMarkdown({ text }: { text: string }) {
  // Source line breaks and their indentation flow as one line.
  const flat = text.replace(/\s+/g, " ").trim();
  // A lone table row or a timeline line ("**date** | Source — …"): show cells, not pipes.
  const cells = rowLikeCells(flat);
  if (!cells) return <Inline text={flat} />;
  return (
    <>
      {cells.map((cell, index) => (
        <Fragment key={index}>
          {index > 0 && <span className="text-neutral-400"> · </span>}
          <Inline text={cell} />
        </Fragment>
      ))}
    </>
  );
}

function Inline({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={INLINE_ELEMENTS}
      unwrapDisallowed
      components={{ code: InlineCode }}
    >
      {text}
    </ReactMarkdown>
  );
}

function InlineCode({ children }: { children?: ReactNode }) {
  return (
    <code className="rounded-sm bg-neutral-100 px-1 py-px font-mono text-[0.85em]">
      {children}
    </code>
  );
}
