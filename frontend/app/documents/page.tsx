"use client";

import { Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { DocumentTable } from "@/components/DocumentTable";
import { PageHeader } from "@/components/PageHeader";
import { RequestAccessForm } from "@/components/RequestAccessForm";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { UploadForm } from "@/components/UploadForm";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { listDocuments, listSources } from "@/lib/api";
import { useApiQuery } from "@/lib/useApi";

const PAGE_SIZE = 50;

export default function DocumentsPage() {
  const [draft, setDraft] = useState("");
  const [filters, setFilters] = useState({ q: "", source_id: "", offset: 0 });
  const sources = useApiQuery("sources", listSources);
  const documents = useApiQuery(`documents:${JSON.stringify(filters)}`, () =>
    listDocuments({ ...filters, limit: PAGE_SIZE }),
  );

  function onSearch(event: FormEvent) {
    event.preventDefault();
    setFilters((current) => ({ ...current, q: draft.trim(), offset: 0 }));
  }

  const rows = documents.data;

  return (
    <div>
      <PageHeader
        title="Documents"
        description="Only documents your persona may read are listed."
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
        <Card>
          <CardHeader>
            <form onSubmit={onSearch} className="flex w-full flex-wrap gap-2">
              <Input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Search titles and content"
                aria-label="Search documents"
                className="min-w-48 flex-1"
              />
              <NativeSelect
                value={filters.source_id}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    source_id: event.target.value,
                    offset: 0,
                  }))
                }
                aria-label="Filter by source"
                className="w-auto"
              >
                <option value="">All sources</option>
                {sources.data?.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name}
                  </option>
                ))}
              </NativeSelect>
              <Button type="submit" variant="secondary">
                <Search className="size-4" aria-hidden />
                Search
              </Button>
            </form>
          </CardHeader>
          <CardContent className="px-2 py-2">
            {documents.error && (
              <ErrorState error={documents.error} className="mx-3 my-2" />
            )}
            {documents.loading && !rows && (
              <div className="px-3">
                <LoadingState />
              </div>
            )}
            {rows?.length === 0 && (
              <div className="px-3">
                <EmptyState>No documents match.</EmptyState>
              </div>
            )}
            {rows && rows.length > 0 && <DocumentTable documents={rows} />}
            {rows && (filters.offset > 0 || rows.length === PAGE_SIZE) && (
              <div className="flex justify-end gap-2 px-3 py-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={filters.offset === 0}
                  onClick={() =>
                    setFilters((current) => ({
                      ...current,
                      offset: Math.max(0, current.offset - PAGE_SIZE),
                    }))
                  }
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={rows.length < PAGE_SIZE}
                  onClick={() =>
                    setFilters((current) => ({
                      ...current,
                      offset: current.offset + PAGE_SIZE,
                    }))
                  }
                >
                  Next
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Upload</CardTitle>
                <CardDescription>
                  You become the owner. Size and daily caps apply.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <UploadForm onUploaded={documents.reload} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Request access</CardTitle>
                <CardDescription>
                  Ask an owner or manager for a document by id.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <RequestAccessForm />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
