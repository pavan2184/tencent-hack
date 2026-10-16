"use client";

import { Check, Search, X } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { GrantEditor } from "@/components/GrantEditor";
import { PageHeader } from "@/components/PageHeader";
import { usePersona } from "@/components/PersonaProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { DecisionBadge } from "@/components/StatusBadge";
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
import { decideAccessRequest, listAccessRequests } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { canManage } from "@/lib/roles";
import { useApiAction, useApiQuery } from "@/lib/useApi";

export default function AccessPage() {
  const { me } = usePersona();
  const manager = canManage(me);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Access,"
        accent="granted and requested."
        description="Explicit grants per document, and the access-request inbox. Revocations apply to the next question."
      />
      <GrantsExplorer canEdit={manager} />
      <RequestInbox canDecide={manager} />
    </div>
  );
}

function GrantsExplorer({ canEdit }: { canEdit: boolean }) {
  const [draft, setDraft] = useState("");
  const [documentId, setDocumentId] = useState<string | null>(null);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setDocumentId(draft.trim() || null);
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Grants</CardTitle>
          <CardDescription>
            Look up the grants on a document by id.
          </CardDescription>
        </div>
        <form onSubmit={onSubmit} className="flex w-full gap-2 sm:w-auto">
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Document id"
            aria-label="Document id"
            className="min-w-0 flex-1 font-mono text-xs sm:w-80 sm:flex-none"
          />
          <Button type="submit" variant="secondary" disabled={!draft.trim()}>
            <Search className="size-4" aria-hidden />
            Load
          </Button>
        </form>
      </CardHeader>
      <CardContent>
        {documentId ? (
          <GrantEditor
            key={documentId}
            documentId={documentId}
            canEdit={canEdit}
          />
        ) : (
          <EmptyState>Enter a document id to see its grants.</EmptyState>
        )}
      </CardContent>
    </Card>
  );
}

function RequestInbox({ canDecide }: { canDecide: boolean }) {
  const requests = useApiQuery("access-requests", listAccessRequests);
  const decide = useApiAction(decideAccessRequest);
  const [notice, setNotice] = useState<string | null>(null);

  async function onDecide(requestId: string, decision: "approve" | "deny") {
    setNotice(null);
    const result = await decide.run(requestId, decision);
    if (!result.ok) return;
    // A local approval cannot widen what the source platform allows; say so plainly.
    if (result.data.effective === false) setNotice(result.data.note);
    requests.reload();
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Access requests</CardTitle>
          <CardDescription>
            Raised from the Documents page by personas who cannot see a
            document.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="px-2 py-2">
        {requests.error && (
          <ErrorState error={requests.error} className="mx-3 my-2" />
        )}
        {decide.error && (
          <ErrorState error={decide.error} className="mx-3 my-2" />
        )}
        {notice && (
          <p
            role="status"
            className="mx-3 my-2 rounded-sm bg-amber-50 px-4 py-3 text-sm text-amber-900"
          >
            {notice}
          </p>
        )}
        {requests.loading && !requests.data && (
          <div className="px-3">
            <LoadingState />
          </div>
        )}
        {requests.data?.length === 0 && (
          <div className="px-3">
            <EmptyState>No access requests.</EmptyState>
          </div>
        )}
        {requests.data && requests.data.length > 0 && (
          <Table>
            <THead>
              <TR>
                <TH>Requester</TH>
                <TH>Document</TH>
                <TH>Reason</TH>
                <TH>Requested</TH>
                <TH>Status</TH>
                {canDecide && <TH className="sr-only">Actions</TH>}
              </TR>
            </THead>
            <TBody>
              {requests.data.map((request) => (
                <TR key={request.id}>
                  <TD className="font-medium">{request.principal_id}</TD>
                  <TD>
                    <Link
                      href={`/documents/${encodeURIComponent(request.document_id)}`}
                      className="font-mono text-xs link"
                    >
                      {request.document_id}
                    </Link>
                  </TD>
                  <TD>{request.reason}</TD>
                  <TD className="text-xs whitespace-nowrap">
                    {formatDateTime(request.created_at)}
                  </TD>
                  <TD>
                    <DecisionBadge value={request.status} />
                    {request.decided_by && (
                      <span className="block text-xs text-neutral-400">
                        by {request.decided_by}
                      </span>
                    )}
                  </TD>
                  {canDecide && (
                    <TD className="text-right whitespace-nowrap">
                      {request.status === "pending" && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={decide.pending}
                            onClick={() => onDecide(request.id, "approve")}
                          >
                            <Check className="size-3.5" aria-hidden />
                            Approve
                          </Button>{" "}
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={decide.pending}
                            onClick={() => onDecide(request.id, "deny")}
                          >
                            <X className="size-3.5" aria-hidden />
                            Deny
                          </Button>
                        </>
                      )}
                    </TD>
                  )}
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
