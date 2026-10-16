"use client";

import { Ban, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, NativeSelect } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { addGrant, listGrants, revokeGrant } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { Effect, SubjectType } from "@/lib/types";
import { useApiAction, useApiQuery } from "@/lib/useApi";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "./StateViews";
import { DecisionBadge } from "./StatusBadge";

const SUBJECT_TYPES: SubjectType[] = ["principal", "group", "role"];

/** Lists a document's grants (revoked ones struck through); `canEdit` shows add/revoke controls. */
export function GrantEditor({
  documentId,
  canEdit,
}: {
  documentId: string;
  canEdit: boolean;
}) {
  const grants = useApiQuery(`grants:${documentId}`, () =>
    listGrants(documentId),
  );
  const add = useApiAction(addGrant);
  const revoke = useApiAction(revokeGrant);
  const [subjectType, setSubjectType] = useState<SubjectType>("principal");
  const [subjectId, setSubjectId] = useState("");
  const [effect, setEffect] = useState<Effect>("allow");

  async function onAdd(event: FormEvent) {
    event.preventDefault();
    const result = await add.run({
      document_id: documentId,
      subject_type: subjectType,
      subject_id: subjectId.trim(),
      effect,
    });
    if (result.ok) {
      setSubjectId("");
      grants.reload();
    }
  }

  async function onRevoke(grantId: string) {
    const result = await revoke.run(grantId);
    if (result.ok) grants.reload();
  }

  const mutationError = add.error ?? revoke.error;

  return (
    <div className="space-y-3">
      {grants.error && <ErrorState error={grants.error} />}
      {grants.loading && !grants.data && <LoadingState />}
      {grants.data?.length === 0 && (
        <EmptyState>No explicit grants on this document.</EmptyState>
      )}
      {grants.data && grants.data.length > 0 && (
        <Table>
          <THead>
            <TR>
              <TH>Subject</TH>
              <TH>Effect</TH>
              <TH>Granted</TH>
              <TH>Revoked</TH>
              {canEdit && <TH className="sr-only">Actions</TH>}
            </TR>
          </THead>
          <TBody>
            {grants.data.map((grant) => {
              const revoked = grant.revoked_at !== null;
              return (
                <TR
                  key={grant.id}
                  className={cn(revoked && "text-neutral-400 line-through")}
                >
                  <TD>
                    <span className="text-xs text-neutral-400">
                      {grant.subject_type}
                    </span>{" "}
                    <span className="font-medium">{grant.subject_id}</span>
                  </TD>
                  <TD>
                    <DecisionBadge value={grant.effect} />
                  </TD>
                  <TD className="text-xs">
                    {formatDateTime(grant.granted_at)}
                    <span className="block text-neutral-400">
                      by {grant.granted_by}
                    </span>
                  </TD>
                  <TD className="text-xs">
                    {formatDateTime(grant.revoked_at)}
                  </TD>
                  {canEdit && (
                    <TD className="text-right">
                      {!revoked && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revoke.pending}
                          onClick={() => onRevoke(grant.id)}
                        >
                          <Ban className="size-3.5" aria-hidden />
                          Revoke
                        </Button>
                      )}
                    </TD>
                  )}
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}

      {canEdit && (
        <form onSubmit={onAdd} className="flex flex-wrap gap-2">
          <NativeSelect
            value={subjectType}
            onChange={(event) =>
              setSubjectType(event.target.value as SubjectType)
            }
            aria-label="Subject type"
            className="w-auto"
          >
            {SUBJECT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </NativeSelect>
          <Input
            value={subjectId}
            onChange={(event) => setSubjectId(event.target.value)}
            placeholder={
              subjectType === "principal"
                ? "e.g. jordan.lim"
                : "e.g. leadership"
            }
            aria-label="Subject id"
            className="min-w-40 flex-1"
          />
          <NativeSelect
            value={effect}
            onChange={(event) => setEffect(event.target.value as Effect)}
            aria-label="Effect"
            className="w-auto"
          >
            <option value="allow">allow</option>
            <option value="deny">deny</option>
          </NativeSelect>
          <Button
            type="submit"
            variant="secondary"
            disabled={!subjectId.trim() || add.pending}
          >
            <Plus className="size-4" aria-hidden />
            Add grant
          </Button>
        </form>
      )}
      {mutationError && <ErrorState error={mutationError} />}
    </div>
  );
}
