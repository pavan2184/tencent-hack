"use client";

import { Eye, X } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { getAuditEvent, revealAuditEvent } from "@/lib/api";
import { parseAskPayload, type AskReconstruction } from "@/lib/auditPayload";
import { formatDateTime, humanize, truncateHash } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";
import { useApiAction, useApiQuery } from "@/lib/useApi";
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
  // A break-glass reveal returns the full event; keep it only for the event it was made for.
  const [revealed, setRevealed] = useState<AuditEvent | null>(null);
  const shown = revealed?.id === eventId ? revealed : event.data;

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
        <Button
          size="icon"
          variant="outline"
          onClick={onClose}
          aria-label="Close"
        >
          <X className="size-4" aria-hidden />
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {event.error && <ErrorState error={event.error} />}
        {event.loading && !event.data && <LoadingState />}
        {shown && <EventBody event={shown} onRevealed={setRevealed} />}
      </CardContent>
    </Card>
  );
}

function EventBody({
  event,
  onRevealed,
}: {
  event: AuditEvent;
  onRevealed: (event: AuditEvent) => void;
}) {
  const ask = event.action === "ask" ? parseAskPayload(event.payload) : null;
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
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
        <AskReconstructionView
          ask={ask}
          occurredAt={event.occurred_at}
          withheld={event.content_withheld === true}
          eventId={event.id}
          onRevealed={onRevealed}
        />
      )}
      <details className="text-xs">
        <summary className="cursor-pointer text-neutral-500">
          Raw payload
        </summary>
        <pre className="mt-2 max-h-96 overflow-auto rounded-sm bg-neutral-100 p-4 font-mono text-neutral-700">
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
      <dt className="text-neutral-500">{label}</dt>
      <dd
        className={
          mono ? "font-mono break-all text-neutral-700" : "text-neutral-800"
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
  withheld,
  eventId,
  onRevealed,
}: {
  ask: AskReconstruction;
  occurredAt: string;
  withheld: boolean;
  eventId: string;
  onRevealed: (event: AuditEvent) => void;
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
    <div className="space-y-6 border-t border-neutral-200 pt-6">
      <Section title="Question">
        <p className="text-sm text-neutral-900">{ask.question}</p>
      </Section>

      <Section
        title={`Retrieved documents and access decisions (${documentIds.length})`}
      >
        {documentIds.length === 0 ? (
          <p className="text-xs text-neutral-500">
            No documents were retrieved.
          </p>
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
                        className="font-mono text-xs whitespace-nowrap link"
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
                        <span className="block text-neutral-400">
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
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-600">
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
          <p className="text-xs text-neutral-500">No receipt recorded.</p>
        )}
      </Section>

      <Section title="Answer">
        {ask.abstained && (
          <p className="mb-1 text-xs font-medium text-amber-700">
            Abstained{ask.abstainReason && `: ${ask.abstainReason}`}
          </p>
        )}
        {withheld ? (
          <RevealForm eventId={eventId} onRevealed={onRevealed} />
        ) : (
          <p className="text-sm whitespace-pre-wrap text-neutral-800">
            {ask.answerText ?? "—"}
          </p>
        )}
        {ask.grounding && (
          <p className="mt-1 flex items-center gap-2 text-xs text-neutral-500">
            <VerdictBadge value={ask.grounding.verdict} />
            {ask.grounding.coverageRatio !== null &&
              `coverage ${Math.round(ask.grounding.coverageRatio * 100)}%`}
          </p>
        )}
      </Section>

      <Section title="Timestamps">
        <p className="text-xs text-neutral-600">
          started {formatDateTime(ask.startedAt)} · completed{" "}
          {formatDateTime(ask.completedAt)} · recorded{" "}
          {formatDateTime(occurredAt)}
          {ask.queryId && ` · query ${ask.queryId}`}
        </p>
      </Section>
    </div>
  );
}

function RevealForm({
  eventId,
  onRevealed,
}: {
  eventId: string;
  onRevealed: (event: AuditEvent) => void;
}) {
  const [reason, setReason] = useState("");
  const reveal = useApiAction(revealAuditEvent);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const result = await reveal.run(eventId, reason.trim());
    if (result.ok) onRevealed(result.data);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <p className="rounded-sm bg-neutral-100 px-4 py-3 text-xs leading-relaxed text-neutral-600">
        Answer withheld: you can&apos;t currently open every document it used.
        Revealing it is recorded in this audit trail with your reason.
      </p>
      <div className="flex gap-2">
        <Input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason, e.g. compliance case reference"
          aria-label="Reason for revealing the answer"
          minLength={10}
          maxLength={500}
          required
        />
        <Button
          type="submit"
          variant="outline"
          disabled={reveal.pending || reason.trim().length < 10}
        >
          <Eye className="size-4" aria-hidden />
          Reveal
        </Button>
      </div>
      {reveal.error && <ErrorState error={reveal.error} />}
    </form>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-medium text-neutral-900">{title}</h3>
      {children}
    </section>
  );
}
