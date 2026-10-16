import type { ReactNode } from "react";

/** Two-tone display headline: `title` in ink, then `accent` on its own line in soft grey. */
export function PageHeader({
  title,
  accent,
  description,
  actions,
}: {
  title: string;
  accent?: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-12 grid gap-6 md:mb-16 lg:grid-cols-[1fr_minmax(0,22rem)] lg:items-end">
      <h1 className="text-5xl leading-[0.98] font-medium tracking-[-0.035em] text-balance text-neutral-900 sm:text-6xl lg:text-7xl">
        {title}
        {accent && <span className="block text-neutral-400">{accent}</span>}
      </h1>
      {(description || actions) && (
        <div className="space-y-4 lg:pb-2">
          {description && (
            <p className="text-sm leading-relaxed text-neutral-500">
              {description}
            </p>
          )}
          {actions}
        </div>
      )}
    </div>
  );
}
