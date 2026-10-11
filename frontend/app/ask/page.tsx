"use client";

import { LoaderCircle, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { AnswerCard } from "@/components/AnswerCard";
import { CitationList } from "@/components/CitationList";
import { FreshnessReceiptCard } from "@/components/FreshnessReceiptCard";
import { PageHeader } from "@/components/PageHeader";
import { usePersona } from "@/components/PersonaProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { ask, listQueries } from "@/lib/api";
import { canAudit } from "@/lib/roles";
import { useApiAction, useApiQuery } from "@/lib/useApi";

export default function AskPage() {
  const { me } = usePersona();
  const [question, setQuestion] = useState("");
  const [requireFresh, setRequireFresh] = useState(false);
  const asking = useApiAction(ask);
  const recent = useApiQuery("queries", listQueries);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || asking.pending) return;
    const result = await asking.run({
      question: trimmed,
      require_fresh: requireFresh,
    });
    if (result.ok) recent.reload();
  }

  const envelope = asking.data;

  return (
    <div>
      <PageHeader
        title="Ask the brain"
        description="Answers are filtered by your access before any model sees evidence, checked for freshness, and every claim is cited."
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_18rem]">
        <div className="space-y-5">
          <Card>
            <CardContent>
              <form onSubmit={onSubmit} className="space-y-3">
                <Textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="e.g. What is the payment rail failover procedure?"
                  rows={3}
                  aria-label="Question"
                />
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={requireFresh}
                      onChange={(event) =>
                        setRequireFresh(event.target.checked)
                      }
                      className="size-4 rounded border-slate-300"
                    />
                    Require fresh evidence
                  </label>
                  <Button
                    type="submit"
                    disabled={!question.trim() || asking.pending}
                  >
                    {asking.pending ? (
                      <LoaderCircle
                        className="size-4 animate-spin"
                        aria-hidden
                      />
                    ) : (
                      <Send className="size-4" aria-hidden />
                    )}
                    Ask
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          {asking.error && (
            <ErrorState
              error={asking.error}
              title="The question could not be answered"
            />
          )}
          {asking.pending && !envelope && (
            <LoadingState label="Retrieving, filtering, verifying…" />
          )}
          {!envelope && !asking.pending && !asking.error && (
            <EmptyState>
              Ask a question to see a governed, cited answer.
            </EmptyState>
          )}

          {envelope && (
            <div
              className={asking.pending ? "space-y-5 opacity-60" : "space-y-5"}
            >
              <AnswerCard envelope={envelope} showAuditLink={canAudit(me)} />
              <CitationList
                claims={envelope.claims}
                citations={envelope.citations}
              />
              <FreshnessReceiptCard receipt={envelope.freshness_receipt} />
            </div>
          )}
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Recent questions</CardTitle>
          </CardHeader>
          <CardContent className="py-2">
            {recent.error && <ErrorState error={recent.error} />}
            {recent.loading && !recent.data && <LoadingState />}
            {recent.data?.length === 0 && (
              <EmptyState>No questions yet.</EmptyState>
            )}
            <ul className="divide-y divide-slate-100">
              {recent.data?.slice(0, 15).map((record) => (
                <li key={record.id}>
                  <button
                    type="button"
                    onClick={() => setQuestion(record.question)}
                    className="w-full py-2 text-left text-sm text-slate-700 hover:text-slate-950"
                    title="Use this question"
                  >
                    {record.question}
                    <span className="block text-xs text-slate-400">
                      {record.status}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
