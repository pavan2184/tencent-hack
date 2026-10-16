"use client";

import { ArrowUpRight, LoaderCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { AnswerCard } from "@/components/AnswerCard";
import { CitationList } from "@/components/CitationList";
import { FreshnessReceiptCard } from "@/components/FreshnessReceiptCard";
import { PageHeader } from "@/components/PageHeader";
import { usePersona } from "@/components/PersonaProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/StateViews";
import { Button } from "@/components/ui/button";
import { ask, listQueries } from "@/lib/api";
import { canAudit } from "@/lib/roles";
import { sampleQuestionsFor } from "@/lib/sampleQuestions";
import { useApiAction, useApiQuery } from "@/lib/useApi";

const PIPELINE = [
  {
    title: "Filtered by your access",
    body: "Retrieval is narrowed to what your persona may read before any model sees evidence.",
  },
  {
    title: "Checked for freshness",
    body: "Each source is aged against its budget; critical ones are verified live.",
  },
  {
    title: "Grounded claim by claim",
    body: "Every claim is matched to cited evidence. Without support, the brain abstains.",
  },
  {
    title: "Written to the audit chain",
    body: "Every ask is hash-chained, so it can be reconstructed later.",
  },
] as const;

export default function AskPage() {
  const { me, actorId } = usePersona();
  const [question, setQuestion] = useState("");
  const [requireFresh, setRequireFresh] = useState(false);
  const asking = useApiAction(ask);
  const recent = useApiQuery("queries", listQueries);
  const samples = sampleQuestionsFor(actorId);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || asking.pending) return;
    const result = await asking.run({
      question: trimmed,
      require_fresh: requireFresh,
    });
    if (result.ok) recent.reload();
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    await submit(question);
  }

  async function askSample(sample: string) {
    setQuestion(sample);
    await submit(sample);
  }

  const envelope = asking.data;

  return (
    <div>
      <PageHeader
        title="Ask the brain"
        accent="with receipts."
        description="Answers are filtered by your access before any model sees evidence, checked for freshness, and every claim is cited."
      />

      <div className="grid gap-12 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-6">
          <form
            onSubmit={onSubmit}
            className="rounded-[28px] border border-transparent bg-neutral-100 p-2 transition-colors focus-within:border-neutral-900 focus-within:bg-white"
          >
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. What is the payment rail failover procedure?"
              rows={3}
              aria-label="Question"
              className="block w-full resize-none bg-transparent px-4 pt-3 pb-2 text-lg leading-relaxed text-neutral-900 placeholder:text-neutral-400 focus:outline-none"
            />
            <div className="flex flex-wrap items-center justify-between gap-3 pl-4">
              <label className="flex items-center gap-2 text-sm text-neutral-600">
                <input
                  type="checkbox"
                  checked={requireFresh}
                  onChange={(event) => setRequireFresh(event.target.checked)}
                  className="size-4 accent-neutral-900"
                />
                Require fresh evidence
              </label>
              <Button
                type="submit"
                variant="accent"
                disabled={!question.trim() || asking.pending}
                className="pr-4"
              >
                {asking.pending && (
                  <LoaderCircle className="size-4 animate-spin" aria-hidden />
                )}
                Ask
                <ArrowUpRight className="size-4" aria-hidden />
              </Button>
            </div>
          </form>

          {samples.length > 0 && (
            <SampleQuestions
              questions={samples}
              disabled={asking.pending}
              onPick={askSample}
            />
          )}

          {asking.error && (
            <ErrorState
              error={asking.error}
              title="The question could not be answered"
            />
          )}
          {asking.pending && !envelope && (
            <LoadingState label="Retrieving, filtering, verifying…" />
          )}
          {!envelope && !asking.pending && !asking.error && <PipelineSteps />}

          {envelope && (
            <div
              className={asking.pending ? "space-y-6 opacity-60" : "space-y-6"}
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

        <aside className="h-fit lg:sticky lg:top-28">
          <h2 className="text-xl font-medium tracking-[-0.01em] text-neutral-900">
            Recent questions
          </h2>
          {recent.error && <ErrorState error={recent.error} className="mt-3" />}
          {recent.loading && !recent.data && <LoadingState />}
          {recent.data?.length === 0 && (
            <EmptyState>No questions yet.</EmptyState>
          )}
          {recent.data && recent.data.length > 0 && (
            <ul className="mt-3 divide-y divide-neutral-300 border-y border-neutral-300">
              {recent.data.slice(0, 15).map((record) => (
                <li key={record.id}>
                  <button
                    type="button"
                    onClick={() => setQuestion(record.question)}
                    className="group flex w-full items-center justify-between gap-4 py-4 text-left"
                    title="Use this question"
                  >
                    <span className="min-w-0">
                      <span className="line-clamp-2 text-sm text-neutral-900">
                        {record.question}
                      </span>
                      <span className="mt-0.5 block text-xs text-neutral-400">
                        {record.status}
                      </span>
                    </span>
                    <span className="grid size-9 shrink-0 place-items-center rounded-full border border-neutral-300 text-neutral-900 transition-colors duration-300 group-hover:border-accent-strong group-hover:bg-accent-strong group-hover:text-white">
                      <ArrowUpRight className="size-4" aria-hidden />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

/** The persona's demo questions (seed README, "Questions to ask"); a click asks it. */
function SampleQuestions({
  questions,
  disabled,
  onPick,
}: {
  questions: readonly string[];
  disabled: boolean;
  onPick: (question: string) => void;
}) {
  return (
    <div>
      <p id="sample-questions" className="text-sm text-neutral-500">
        Try asking
      </p>
      <div
        role="group"
        aria-labelledby="sample-questions"
        className="mt-3 flex flex-wrap gap-2"
      >
        {questions.map((sample) => (
          <Button
            key={sample}
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => onPick(sample)}
            className="h-auto min-h-9 py-2 text-left text-sm font-normal whitespace-normal"
          >
            {sample}
            <ArrowUpRight className="size-3.5 shrink-0" aria-hidden />
          </Button>
        ))}
      </div>
    </div>
  );
}

/** Empty state: the governed pipeline every question runs, as numbered steps. */
function PipelineSteps() {
  return (
    <ol className="grid gap-x-8 gap-y-10 pt-6 sm:grid-cols-2">
      {PIPELINE.map((step, index) => (
        <li key={step.title}>
          <span className="grid size-12 place-items-center rounded-full bg-neutral-100 text-sm text-neutral-900 tabular-nums">
            {String(index + 1).padStart(2, "0")}
          </span>
          <h3 className="mt-5 text-lg font-medium tracking-[-0.01em] text-neutral-900">
            {step.title}
          </h3>
          <p className="mt-1 max-w-xs text-sm leading-relaxed text-neutral-500">
            {step.body}
          </p>
        </li>
      ))}
    </ol>
  );
}
