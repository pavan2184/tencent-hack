import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnswerCitation, Claim } from "@/lib/types";
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
      <CardContent className="space-y-4">
        {ordered.length === 0 && orphans.length === 0 && (
          <EmptyState>
            No claims were made, so there is nothing to cite.
          </EmptyState>
        )}
        {ordered.map((claim, index) => (
          <div key={claim.id}>
            <p className="text-sm text-slate-900">
              <span className="mr-1.5 font-mono text-xs text-slate-400">
                C{index + 1}
              </span>
              {claim.text}
              {claim.kind === "inference" && (
                <span className="ml-1.5 text-xs text-slate-400">
                  (inference)
                </span>
              )}
            </p>
            <EvidenceList
              citations={citations.filter((c) => c.claim_id === claim.id)}
            />
          </div>
        ))}
        {orphans.length > 0 && (
          <div>
            <p className="text-xs font-medium text-slate-500">Other evidence</p>
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
      <p className="mt-1 ml-6 text-xs text-red-600">
        No citation for this claim.
      </p>
    );
  }
  return (
    <ul className="mt-2 ml-6 space-y-2">
      {citations.map((citation) => (
        <li
          key={`${citation.claim_id}:${citation.evidence_id}`}
          className="rounded-md border border-slate-200 px-3 py-2"
        >
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <SupportBadge value={citation.support} />
            <Link
              href={`/documents/${encodeURIComponent(citation.document_id)}`}
              className="font-medium text-sky-700 hover:underline"
            >
              {citation.title}
            </Link>
            <span className="text-slate-500">
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
                className="inline-flex items-center gap-0.5 text-slate-500 hover:text-slate-800"
              >
                source <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
          </div>
          {citation.quote && (
            <blockquote className="mt-1.5 border-l-2 border-slate-200 pl-2 text-xs text-slate-600">
              {citation.quote}
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
