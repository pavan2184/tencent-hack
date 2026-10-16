import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnswerCitation, Claim } from "@/lib/types";
import { SnippetMarkdown } from "./Markdown";
import { EmptyState } from "./StateViews";
import { SupportBadge } from "./StatusBadge";

/** Claim → evidence: each claim with the citations that back it and their support labels. */
export function CitationList({
  claims,
  citations,
}: {
  claims: Claim[];
  citations: AnswerCitation[];
}) {
  const ordered = [...claims].sort((a, b) => a.position - b.position);
  const claimIds = new Set(ordered.map((claim) => claim.id));
  const orphans = citations.filter(
    (citation) => !claimIds.has(citation.claim_id),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Claims and citations</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {ordered.length === 0 && orphans.length === 0 && (
          <EmptyState>
            No claims were made, so there is nothing to cite.
          </EmptyState>
        )}
        {ordered.map((claim, index) => (
          <div key={claim.id} className="flex gap-4">
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-neutral-100 text-xs text-neutral-900 tabular-nums">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="min-w-0 flex-1 pt-1.5">
              <div className="text-[15px] text-neutral-900">
                <SnippetMarkdown text={claim.text} />
                {claim.kind === "inference" && (
                  <span className="ml-1.5 text-xs text-neutral-400">
                    (inference)
                  </span>
                )}
              </div>
              <EvidenceList
                citations={citations.filter((c) => c.claim_id === claim.id)}
              />
            </div>
          </div>
        ))}
        {orphans.length > 0 && (
          <div className="pl-13">
            <p className="text-xs text-neutral-500">Other evidence</p>
            <EvidenceList citations={orphans} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EvidenceList({ citations }: { citations: AnswerCitation[] }) {
  if (citations.length === 0) {
    return (
      <p className="mt-1 text-xs text-red-700">No citation for this claim.</p>
    );
  }
  return (
    <ul className="mt-3 space-y-2">
      {citations.map((citation) => (
        <li
          key={`${citation.claim_id}:${citation.evidence_id}`}
          className="rounded-sm border border-neutral-200 px-4 py-3"
        >
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <SupportBadge value={citation.support} />
            <Link
              href={`/documents/${encodeURIComponent(citation.document_id)}`}
              className="font-medium link"
            >
              {citation.title}
            </Link>
            <span className="text-neutral-500">
              {citation.source_kind} · {citation.source_id}
              {citation.provider_version &&
                ` · version ${citation.provider_version}`}{" "}
              · score {citation.score.toFixed(2)}
            </span>
            {isHttpUrl(citation.url) && (
              <a
                href={citation.url ?? undefined}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-0.5 text-neutral-500 hover:text-neutral-800"
              >
                source <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
          </div>
          {citation.quote && (
            <blockquote className="mt-2 border-l-2 border-neutral-300 pl-3 text-xs leading-relaxed text-neutral-600">
              <SnippetMarkdown text={citation.quote} tableClassName="text-xs" />
            </blockquote>
          )}
        </li>
      ))}
    </ul>
  );
}

// Citation URLs come from ingested (untrusted) documents: only link http(s).
function isHttpUrl(url: string | null): boolean {
  return url !== null && /^https?:\/\//i.test(url);
}
