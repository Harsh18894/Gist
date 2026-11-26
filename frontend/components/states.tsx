import { CircleAlert, RotateCcw } from "lucide-react";
import { cx } from "./ui";

/** Skeleton placeholder that reserves space (no layout shift) and names what is loading. */
export function Loading({ label = "Loading…", rows = 4, className }: { label?: string; rows?: number; className?: string }) {
  return <div role="status" aria-live="polite" className={cx("py-2", className)}>
    <p className="mb-4 flex items-center gap-2 text-xs text-ink-3"><span className="h-1.5 w-1.5 rounded-full bg-accent animate-breathe" aria-hidden="true"/>{label}</p>
    <div className="space-y-3" aria-hidden="true">{Array.from({ length: rows }, (_, i) =>
      <div key={i} className="h-3 rounded-[3px] bg-sunken animate-breathe" style={{ width: `${92 - ((i * 17) % 38)}%`, animationDelay: `${i * 90}ms` }}/>)}</div>
  </div>;
}

export function ErrorState({ message, retry, title = "This didn’t load" }: { message: string; retry: () => void; title?: string }) {
  return <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-signal/30 bg-signal-soft px-5 py-4 sm:flex-row sm:items-center">
    <CircleAlert size={18} className="shrink-0 text-signal" aria-hidden="true"/>
    <div className="min-w-0 flex-1 text-sm"><p className="font-medium text-ink">{title}</p><p className="mt-0.5 text-ink-2">{message}</p></div>
    <button type="button" onClick={retry} className="inline-flex h-9 shrink-0 items-center gap-2 rounded border border-line-strong bg-surface px-3 text-sm font-medium text-ink hover:border-control"><RotateCcw size={14}/>Try again</button>
  </div>;
}
