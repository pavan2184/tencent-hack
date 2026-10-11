"use client";

import { X } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { getAuditEvent } from "@/lib/api";
import { parseAskPayload, type AskReconstruction } from "@/lib/auditPayload";
import { formatDateTime, humanize, truncateHash } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";
import { useApiQuery } from "@/lib/useApi";
import { ErrorState, LoadingState } from "./StateViews";
import { DecisionBadge, FreshnessBadge, VerdictBadge } from "./StatusBadge";

export function AuditEventDetail({
  eventId,
  onClose,
}: {
  eventId: string;
  onClose: () => void;
}) {
  const event = useApiQuery(`audit-event:${eventId}`, () =>
    getAuditEvent(eventId),
  );

  return (
    <Card className="h-fit">
      <CardHeader>
        <div>
          <CardTitle>
            {event.data
              ? `#${event.data.seq} · ${event.data.action}`
              : "Audit event"}
          </CardTitle>
          {event.data && (
            <CardDescription>
              {formatDateTime(event.data.occurred_at)}
            </CardDescription>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close">
          <X className="size-4" aria-hidden />
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {event.error && <ErrorState error={event.error} />}
        {event.loading && !event.data && <LoadingState />}
        {event.data && <EventBody event={event.data} />}
      </CardContent>
    </Card>
  );
}

function EventBody({ event }: { event: AuditEvent }) {
  const ask = event.action === "ask" ? parseAskPayload(event.payload) : null;
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
        <Field label="Actor">{event.actor_id}</Field>
        <Field label="Request">{event.request_id ?? "—"}</Field>
        <Field label="Subject">
          {event.subject_type
            ? `${event.subject_type}:${event.subject_id ?? ""}`
            : "—"}
        </Field>
        <Field label="Hash" mono>
          {event.hash}
        </Field>
        <Field label="Prev hash" mono>
          {event.prev_hash ?? "— (genesis)"}
        </Field>
      </dl>
      {ask && (
        <AskReconstructionView ask={ask} occurredAt={event.occurred_at} />
      )}
      <details className="text-xs">
        <summary className="cursor-pointer text-slate-500">Raw payload</summary>
        <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-slate-50 p-3 font-mono text-slate-700">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      </details>
    </>
  );
}

function Field({
  label,
  mono,
  children,
}: {
  label: string;
  mono?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd
        className={
          mono ? "font-mono break-all text-slate-700" : "text-slate-800"
        }
      >
        {children}
      </dd>
    </>
  );
}

function AskReconstructionView({
  ask,
  occurredAt,
}: {
  ask: AskReconstruction;
  occurredAt: string;
}) {
  const decisionsById = new Map(ask.decisions.map((d) => [d.document_id, d]));
  const documentIds = [
    ...new Set([
      ...ask.retrievedDocumentIds,
      ...ask.decisions.map((d) => d.document_id),
    ]),
  ];
  const cited = new Set(ask.citedDocumentIds);

  return (
    <div className="space-y-4 border-t border-slate-100 pt-4">
      <Section title="Question">
        <p className="text-sm text-slate-900">{ask.question}</p>
      </Section>

      <Section
        title={`Retrieved documents and access decisions (${documentIds.length})`}
      >
        {documentIds.length === 0 ? (
          <p className="text-xs text-slate-500">No documents were retrieved.</p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Document</TH>
                <TH>Decision</TH>
                <TH>Rule</TH>
                <TH>Cited</TH>
              </TR>
            </THead>
            <TBody>
              {documentIds.map((documentId) => {
                const decision = decisionsById.get(documentId);
                return (
                  <TR key={documentId}>
                    <TD>
                      <Link
                        href={`/documents/${encodeURIComponent(documentId)}`}
                        className="font-mono text-xs whitespace-nowrap text-sky-700 hover:underline"
                      >
                        {truncateHash(documentId, 13)}
                      </Link>
                    </TD>
                    <TD>
                      <DecisionBadge value={decision?.decision} />
                    </TD>
                    <TD className="text-xs">
                      {decision?.matched_rule ?? "—"}
                      {decision?.reason && (
                        <span className="block text-slate-400">
                          {humanize(decision.reason)}
                        </span>
                      )}
                    </TD>
                    <TD className="text-xs">
                      {cited.has(documentId) ? "yes" : "—"}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Section>

      <Section title="Freshness receipt">
        {ask.receipt ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <FreshnessBadge value={ask.receipt.overallStatus} />
            <span>
              {ask.receipt.itemCount} items · {ask.receipt.unsafeCount} omitted
              as unsafe
            </span>
            <span
              className="font-mono"
              title={ask.receipt.receiptHash ?? undefined}
            >
              {truncateHash(ask.receipt.receiptHash)}
            </span>
          </div>
        ) : (
          <p className="text-xs text-slate-500">No receipt recorded.</p>
        )}
      </Section>

      <Section title="Answer">
        {ask.abstained && (
          <p className="mb-1 text-xs font-medium text-amber-700">
            Abstained{ask.abstainReason && `: ${ask.abstainReason}`}
          </p>
        )}
        <p className="text-sm whitespace-pre-wrap text-slate-800">
          {ask.answerText ?? "—"}
        </p>
        {ask.grounding && (
          <p className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <VerdictBadge value={ask.grounding.verdict} />
            {ask.grounding.coverageRatio !== null &&
              `coverage ${Math.round(ask.grounding.coverageRatio * 100)}%`}
          </p>
        )}
      </Section>

      <Section title="Timestamps">
        <p className="text-xs text-slate-600">
          started {formatDateTime(ask.startedAt)} · completed{" "}
          {formatDateTime(ask.completedAt)} · recorded{" "}
          {formatDateTime(occurredAt)}
          {ask.queryId && ` · query ${ask.queryId}`}
        </p>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}
