"use client";

import { ArrowLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/input";
import { getDocument, setClassification, verifyDocument } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { canManage } from "@/lib/roles";
import {
  CLASSIFICATIONS,
  type Classification,
  type DocumentDetail,
} from "@/lib/types";
import { useApiAction, useApiQuery } from "@/lib/useApi";
import { GrantEditor } from "./GrantEditor";
import { usePersona } from "./PersonaProvider";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";
import { ClassificationBadge, FreshnessBadge } from "./StatusBadge";

export function DocumentDetailView({ id }: { id: string }) {
  const { me } = usePersona();
  const document = useApiQuery(`document:${id}`, () => getDocument(id));

  // Denied and nonexistent documents are byte-identical 404s; render them identically too.
  if (document.error?.status === 404) return <NotFound />;
  if (document.error) return <ErrorState error={document.error} />;
  if (!document.data) return <LoadingState />;

  const doc = document.data;
  const manager = canManage(me);
  const owner = me !== null && doc.owner_principal_id === me.id;

  return (
    <div className="space-y-5">
      <div>
        <BackLink />
        <h1 className="mt-2 text-xl font-semibold text-slate-900">
          {doc.title}
        </h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <ClassificationBadge value={doc.classification} />
          <FreshnessBadge
            value={doc.freshness?.freshness_status ?? doc.freshness_status}
          />
          <span>
            {doc.source_kind} · {doc.source_id} · {doc.slug}
          </span>
          <span>· {doc.evidence_class} evidence</span>
          {doc.owner_principal_id && (
            <span>· owner {doc.owner_principal_id}</span>
          )}
          <span className="font-mono">· id {doc.id}</span>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Compiled truth</CardTitle>
            </CardHeader>
            <CardContent>
              {doc.compiled_truth.trim() ? (
                <div className="markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {doc.compiled_truth}
                  </ReactMarkdown>
                </div>
              ) : (
                <EmptyState>No compiled truth yet{ingestNote(doc)}.</EmptyState>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              <Timeline timeline={doc.timeline} />
            </CardContent>
          </Card>
          {(manager || owner) && (
            <Card>
              <CardHeader>
                <CardTitle>Grants</CardTitle>
              </CardHeader>
              <CardContent>
                <GrantEditor documentId={doc.id} canEdit />
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-5">
          <FreshnessPanel
            doc={doc}
            canVerify={manager}
            onVerified={document.reload}
          />
          <ClassificationPanel
            doc={doc}
            canEdit={manager || owner}
            onChanged={document.reload}
          />
        </div>
      </div>
    </div>
  );
}

function ingestNote(doc: DocumentDetail): string {
  return doc.ingest_status ? ` (ingest ${humanize(doc.ingest_status)})` : "";
}

function BackLink() {
  return (
    <Link
      href="/documents"
      className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900"
    >
      <ArrowLeft className="size-4" aria-hidden />
      Documents
    </Link>
  );
}

function NotFound() {
  return (
    <div className="space-y-3">
      <BackLink />
      <Card>
        <CardContent>
          <h1 className="text-lg font-semibold text-slate-900">Not found</h1>
          <p className="mt-1 text-sm text-slate-500">
            There is no document at this address.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Timeline({ timeline }: { timeline: DocumentDetail["timeline"] }) {
  if (typeof timeline === "string") {
    return timeline.trim() ? (
      <div className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{timeline}</ReactMarkdown>
      </div>
    ) : (
      <EmptyState>No timeline entries.</EmptyState>
    );
  }
  if (timeline.length === 0)
    return <EmptyState>No timeline entries.</EmptyState>;
  return (
    <ol className="space-y-2 border-l border-slate-200 pl-4 text-sm">
      {timeline.map((entry, index) => (
        <li key={`${entry.date ?? ""}:${index}`}>
          <p className="text-xs text-slate-400">
            {entry.date ?? "undated"}
            {entry.source && ` · ${entry.source}`}
          </p>
          {entry.summary && <p className="text-slate-800">{entry.summary}</p>}
          {entry.detail && (
            <p className="text-xs text-slate-500">{entry.detail}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

function FreshnessPanel({
  doc,
  canVerify,
  onVerified,
}: {
  doc: DocumentDetail;
  canVerify: boolean;
  onVerified: () => void;
}) {
  const verify = useApiAction(verifyDocument);
  const freshness = doc.freshness;

  async function onVerify() {
    const result = await verify.run(doc.id);
    if (result.ok) onVerified();
  }

  const rows: [string, string][] = [
    ["Provider version", doc.provider_version ?? "—"],
    ["Provider modified", formatDateTime(doc.provider_modified_at)],
    ["Indexed", formatDateTime(freshness?.indexed_at)],
    ["Searchable", formatDateTime(freshness?.searchable_at)],
    ["Last verified", formatDateTime(freshness?.last_verified_at)],
    [
      "Verification",
      freshness?.verification_result
        ? humanize(freshness.verification_result)
        : "—",
    ],
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Freshness</CardTitle>
        <FreshnessBadge
          value={freshness?.freshness_status ?? doc.freshness_status}
        />
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-slate-500">{label}</dt>
              <dd className="text-slate-800">{value}</dd>
            </div>
          ))}
        </dl>
        {canVerify && (
          <Button
            size="sm"
            variant="outline"
            onClick={onVerify}
            disabled={verify.pending}
            className="w-full"
          >
            <RefreshCw
              className={verify.pending ? "size-3.5 animate-spin" : "size-3.5"}
              aria-hidden
            />
            Verify now
          </Button>
        )}
        {verify.data && !verify.pending && (
          <p className="text-xs text-slate-600">
            Live check: {humanize(verify.data.verification_result)} →{" "}
            {humanize(verify.data.freshness_status)}
          </p>
        )}
        {verify.error && <ErrorState error={verify.error} />}
      </CardContent>
    </Card>
  );
}

function ClassificationPanel({
  doc,
  canEdit,
  onChanged,
}: {
  doc: DocumentDetail;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const update = useApiAction(setClassification);

  async function onChange(value: Classification) {
    const result = await update.run(doc.id, value);
    if (result.ok) onChanged();
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Classification</CardTitle>
          <CardDescription>
            Confidential and restricted documents need explicit grants.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {canEdit ? (
          <NativeSelect
            value={doc.classification}
            onChange={(event) => onChange(event.target.value as Classification)}
            disabled={update.pending}
            aria-label="Classification"
          >
            {CLASSIFICATIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        ) : (
          <ClassificationBadge value={doc.classification} />
        )}
        {update.error && <ErrorState error={update.error} />}
      </CardContent>
    </Card>
  );
}
