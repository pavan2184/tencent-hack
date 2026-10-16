"use client";

import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { requestAccess } from "@/lib/api";
import { useApiAction } from "@/lib/useApi";
import { ErrorState } from "./StateViews";

/** The API answers 202 for any id, so the confirmation never reveals whether the document
 * exists. With `documentId` the id is fixed (the not-found page) and only a reason is asked. */
export function RequestAccessForm({ documentId }: { documentId?: string }) {
  const [typedId, setTypedId] = useState("");
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const request = useApiAction(requestAccess);
  const target = (documentId ?? typedId).trim();

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitted(false);
    const result = await request.run(target, reason.trim());
    if (result.ok) {
      setSubmitted(true);
      setTypedId("");
      setReason("");
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      {documentId === undefined && (
        <div className="space-y-1">
          <Label htmlFor="request-document-id">Document id</Label>
          <Input
            id="request-document-id"
            value={typedId}
            onChange={(event) => setTypedId(event.target.value)}
            className="font-mono text-xs"
          />
        </div>
      )}
      <div className="space-y-1">
        <Label htmlFor="request-reason">Why you need it</Label>
        <Input
          id="request-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <Button
        type="submit"
        variant="outline"
        disabled={!target || !reason.trim() || request.pending}
        className="w-full"
      >
        <KeyRound className="size-4" aria-hidden />
        Request access
      </Button>
      {request.error && <ErrorState error={request.error} />}
      {submitted && (
        <p role="status" className="text-sm text-accent-strong">
          Request sent. If this document exists, its owner or an admin can
          approve it.
        </p>
      )}
    </form>
  );
}
