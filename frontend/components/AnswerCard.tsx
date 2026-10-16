import { ArrowUpRight, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { truncateHash } from "@/lib/format";
import type { AnswerEnvelope, GroundingReport } from "@/lib/types";
import { cn } from "@/lib/utils";
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
        <div className="flex flex-wrap items-center gap-3">
          <AccessSummaryBadge summary={access_summary} />
          {showAuditLink && (
            <Link
              href={`/audit?event=${encodeURIComponent(audit_id)}`}
              className="link inline-flex items-center gap-0.5 text-xs"
            >
              Audit #{truncateHash(audit_id, 8)}
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {answer.abstained ? (
          <div className="flex gap-2.5 rounded-sm bg-amber-50 px-4 py-3 text-sm text-amber-900">
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
          <p className="text-lg leading-relaxed whitespace-pre-wrap text-neutral-900">
            {answer.text}
          </p>
        )}
        <GroundingStats grounding={grounding} />
        <p className="text-xs text-neutral-400">
          {timing.total_ms} ms total · retrieval {timing.retrieval_ms} · access{" "}
          {timing.access_ms} · freshness {timing.freshness_ms} · compose{" "}
          {timing.compose_ms} · verify {timing.verify_ms}
        </p>
      </CardContent>
    </Card>
  );
}

/** Stat tiles: coverage is the highlight tile (green when grounded, ink otherwise). */
function GroundingStats({ grounding }: { grounding: GroundingReport }) {
  // [label, value, flag when positive]
  const stats: [string, number, boolean][] = [
    ["claims", grounding.claims_total, false],
    ["supported", grounding.supported, false],
    ["partial", grounding.partially_supported, false],
    ["unsupported", grounding.unsupported, false],
    ["contradicted", grounding.contradicted, true],
    ["injection flags", grounding.injection_flags, true],
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-500">
        <span className="flex items-center gap-2">
          Grounding <VerdictBadge value={grounding.verdict} />
        </span>
        <span
          className="font-mono text-neutral-400"
          title={grounding.report_hash}
        >
          report {truncateHash(grounding.report_hash)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div
          className={cn(
            "row-span-2 flex flex-col justify-between rounded-sm p-5 text-white",
            grounding.verdict === "grounded"
              ? "bg-accent-strong"
              : "bg-neutral-900",
          )}
        >
          <span className="text-5xl font-light tracking-[-0.04em] tabular-nums">
            {Math.round(grounding.coverage_ratio * 100)}
            <span className="ml-0.5 align-top text-2xl">%</span>
          </span>
          <span className="mt-10 text-sm">Claim coverage</span>
        </div>
        {stats.map(([label, value, flag]) => (
          <div key={label} className="rounded-sm bg-neutral-100 px-4 py-3.5">
            <span
              className={cn(
                "block text-3xl font-light tracking-[-0.03em] tabular-nums",
                flag && value > 0 ? "text-red-700" : "text-neutral-900",
              )}
            >
              {value}
            </span>
            <span className="mt-2 block text-xs text-neutral-500">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
