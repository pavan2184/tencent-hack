import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Answer, claim and quote text is lifted from ingested (untrusted) documents, so it renders as
// inline emphasis only: block structure is flattened into the surrounding text, links show as
// plain text and images are dropped (an image URL would fetch on render).
const INLINE_ELEMENTS = ["strong", "em", "del", "code"];

/** Inline markdown for text that sits inside an existing paragraph. */
export function InlineMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={INLINE_ELEMENTS}
      unwrapDisallowed
    >
      {text.replace(/\s+/g, " ").trim()}
    </ReactMarkdown>
  );
}
