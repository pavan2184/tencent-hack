"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { usePersona } from "@/components/PersonaProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { getSourceStatus, listSources, syncSource } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { canManage } from "@/lib/roles";
import { useApiAction, useApiQuery } from "@/lib/useApi";

const checkpointTones: Record<string, BadgeTone> = {
  ready: "success",
  polling: "info",
  degraded: "warning",
  paused: "neutral",
};

export default function SourcesPage() {
  const { me } = usePersona();
  const sources = useApiQuery("sources", listSources);
  const sync = useApiAction(syncSource);
  const [queued, setQueued] = useState<Record<string, string>>({});
  const [statusFor, setStatusFor] = useState<string | null>(null);

  async function onSync(sourceId: string) {
    const result = await sync.run(sourceId, "delta");
    if (result.ok) {
      setQueued((current) => ({ ...current, [sourceId]: result.data.run_id }));
      sources.reload();
    }
  }

  const manager = canManage(me);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sources"
        accent="feeding the brain."
        description="Connected systems feeding the brain, and where each one's sync checkpoint stands."
      />

      <Card>
        <CardContent className="px-2 py-2">
          {sources.error && (
            <ErrorState error={sources.error} className="mx-3 my-2" />
          )}
          {sync.error && (
            <ErrorState
              error={sync.error}
              title="Sync not started"
              className="mx-3 my-2"
            />
          )}
          {sources.loading && !sources.data && (
            <div className="px-3">
              <LoadingState />
            </div>
          )}
          {sources.data?.length === 0 && (
            <div className="px-3">
              <EmptyState>
                No sources yet. Run `make seed` to load the demo corpus.
              </EmptyState>
            </div>
          )}
          {sources.data && sources.data.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Source</TH>
                  <TH>Kind</TH>
                  <TH>Pages</TH>
                  <TH>Last sync</TH>
                  <TH>Checkpoint</TH>
                  <TH className="sr-only">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {sources.data.map((source) => (
                  <TR key={source.id}>
                    <TD>
                      <p className="font-medium text-neutral-900">
                        {source.name}
                      </p>
                      <p className="font-mono text-xs text-neutral-400">
                        {source.id}
                      </p>
                    </TD>
                    <TD>{source.kind}</TD>
                    <TD>{source.page_count ?? "—"}</TD>
                    <TD className="text-xs whitespace-nowrap">
                      {formatDateTime(source.last_sync_at)}
                      {queued[source.id] && (
                        <span className="block text-accent-strong">
                          queued run {queued[source.id]}
                        </span>
                      )}
                    </TD>
                    <TD>
                      {source.checkpoint_status ? (
                        <Badge
                          dot
                          tone={
                            checkpointTones[source.checkpoint_status] ??
                            "neutral"
                          }
                        >
                          {source.checkpoint_status}
                        </Badge>
                      ) : (
                        <span className="text-neutral-400">—</span>
                      )}
                    </TD>
                    <TD className="text-right whitespace-nowrap">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setStatusFor(source.id)}
                      >
                        Status
                      </Button>
                      {manager && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={sync.pending}
                          onClick={() => onSync(source.id)}
                        >
                          <RefreshCw className="size-3.5" aria-hidden />
                          Sync now
                        </Button>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {statusFor && <SourceStatusCard sourceId={statusFor} />}
    </div>
  );
}

function SourceStatusCard({ sourceId }: { sourceId: string }) {
  const status = useApiQuery(`source-status:${sourceId}`, () =>
    getSourceStatus(sourceId),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Status · {sourceId}</CardTitle>
        <Button
          size="sm"
          variant="ghost"
          onClick={status.reload}
          disabled={status.loading}
        >
          <RefreshCw className="size-3.5" aria-hidden />
          Refresh
        </Button>
      </CardHeader>
      <CardContent>
        {status.error && <ErrorState error={status.error} />}
        {status.loading && !status.data && <LoadingState />}
        {status.data && (
          <pre className="overflow-x-auto rounded-sm bg-neutral-100 p-4 font-mono text-xs text-neutral-700">
            {JSON.stringify(status.data, null, 2)}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}
