import { ScrollText, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { truncateHash } from "@/lib/format";
import type { AnswerEnvelope, GroundingReport } from "@/lib/types";
import { AccessSummaryBadge } from "./AccessSummaryBadge";
import { VerdictBadge } from "./StatusBadge";

export function AnswerCard({
  envelope,
  showAuditLink,
}: {
  envelope: AnswerEnvelope;
  showAuditLink: boolean;
}) {
  const { answer, grounding, access_summary, timing, audit_id } = envelope;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Answer</CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <AccessSummaryBadge summary={access_summary} />
          {showAuditLink && (
            <Link
              href={`/audit?event=${encodeURIComponent(audit_id)}`}
              className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:underline"
            >
              <ScrollText className="size-3.5" aria-hidden />
              Audit #{truncateHash(audit_id, 8)}
            </Link>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {answer.abstained ? (
          <div className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div>
              <p className="font-medium">
                The brain abstained rather than guess.
              </p>
              {answer.abstain_reason && <p>{answer.abstain_reason}</p>}
              {answer.text && (
                <p className="mt-1 text-amber-800">{answer.text}</p>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-800">
            {answer.text}
          </p>
        )}
        <GroundingStats grounding={grounding} />
        <p className="text-xs text-slate-400">
          {timing.total_ms} ms total · retrieval {timing.retrieval_ms} · access{" "}
          {timing.access_ms} · freshness {timing.freshness_ms} · compose{" "}
          {timing.compose_ms} · verify {timing.verify_ms}
        </p>
      </CardContent>
    </Card>
  );
}

function GroundingStats({ grounding }: { grounding: GroundingReport }) {
  const stats: [string, number][] = [
    ["claims", grounding.claims_total],
    ["supported", grounding.supported],
    ["partial", grounding.partially_supported],
    ["unsupported", grounding.unsupported],
    ["contradicted", grounding.contradicted],
    ["injection flags", grounding.injection_flags],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <span className="flex items-center gap-1.5">
        Grounding <VerdictBadge value={grounding.verdict} />
      </span>
      <span>
        coverage{" "}
        <strong className="text-slate-900">
          {Math.round(grounding.coverage_ratio * 100)}%
        </strong>
      </span>
      {stats.map(([label, value]) => (
        <span key={label}>
          {label} <strong className="text-slate-900">{value}</strong>
        </span>
      ))}
      <span className="font-mono text-slate-400" title={grounding.report_hash}>
        report {truncateHash(grounding.report_hash)}
      </span>
    </div>
  );
}
