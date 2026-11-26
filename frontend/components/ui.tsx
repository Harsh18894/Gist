"use client";

import Link from "next/link";
import { forwardRef, useCallback, useEffect, useRef, useState } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, ChevronLeft, ChevronRight, CircleAlert, Info, Plus, Search, TriangleAlert, X } from "lucide-react";

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/* ---------- Page structure ---------- */

export function PageHeader({ title, lede, actions, children }: { title: string; lede?: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode }) {
  return <header className="mb-8 sm:mb-10">
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 max-w-3xl">
        <h1 className="font-serif text-xl font-medium text-ink sm:text-2xl" style={{ fontVariationSettings: '"opsz" 48' }}>{title}</h1>
        {lede && <p className="mt-2 max-w-2xl text-sm text-ink-2 sm:text-base sm:leading-7">{lede}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
    {children}
  </header>;
}

/** A titled region separated by spacing and a hairline, not a card. */
export function Section({ id, title, description, actions, children, className }: {
  id: string; title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return <section aria-labelledby={id} className={cx("min-w-0", className)}>
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line pb-3">
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-ink-3">{description}</p>}
      </div>
      {actions}
    </div>
    {children}
  </section>;
}

/** A raised surface for primary data modules and interactive tools. */
export function Panel({ children, className, as: Tag = "div", ...rest }: { children: React.ReactNode; className?: string; as?: "div" | "section" | "article" | "form" } & React.HTMLAttributes<HTMLElement>) {
  return <Tag className={cx("rounded-lg border border-line bg-surface", className)} {...rest}>{children}</Tag>;
}

/* ---------- Actions ---------- */

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";
const buttonBase = "inline-flex shrink-0 select-none items-center justify-center gap-2 rounded font-medium transition-colors duration-fast ease-out disabled:pointer-events-none disabled:opacity-45";
const buttonVariant: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent/90 active:bg-accent/80",
  secondary: "border border-line-strong bg-surface text-ink hover:border-control hover:bg-sunken/60 active:bg-sunken",
  ghost: "text-ink-2 hover:bg-sunken hover:text-ink active:bg-line",
};
const buttonSize: Record<Size, string> = { sm: "h-8 px-3 text-xs", md: "h-10 px-4 text-sm" };
export const buttonClass = (variant: Variant = "secondary", size: Size = "md", extra?: string) => cx(buttonBase, buttonVariant[variant], buttonSize[size], extra);

export const Button = forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }>(
  function Button({ variant = "secondary", size = "md", className, type = "button", ...rest }, ref) {
    return <button ref={ref} type={type} className={buttonClass(variant, size, className)} {...rest}/>;
  });

export function IconButton({ label, children, className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button type="button" aria-label={label} title={label} className={cx("inline-flex h-10 w-10 shrink-0 items-center justify-center rounded text-ink-2 transition-colors duration-fast hover:bg-sunken hover:text-ink", className)} {...rest}>{children}</button>;
}

/* ---------- Form controls ---------- */

const controlBase = "h-10 w-full min-w-0 rounded border border-control/70 bg-surface px-3 text-sm text-ink transition-colors duration-fast placeholder:text-ink-3 hover:border-control focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-0";

export function Field({ label, htmlFor, children, hint, className }: { label: string; htmlFor: string; children: React.ReactNode; hint?: string; className?: string }) {
  return <div className={cx("min-w-0", className)}>
    <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-medium text-ink-2">{label}</label>
    {children}
    {hint && <p className="mt-1 text-2xs text-ink-3">{hint}</p>}
  </div>;
}

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx(controlBase, "cursor-pointer appearance-none bg-no-repeat pr-8", className)}
    style={{ backgroundImage: "linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%)", backgroundPosition: "calc(100% - 16px) 52%, calc(100% - 11px) 52%", backgroundSize: "5px 5px, 5px 5px" }}
    {...rest}>{children}</select>;
}

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(controlBase, className)} {...rest}/>;
});

/** Search input with a leading icon and a clear button. Submits via the enclosing form, or filters live. */
export const SearchField = forwardRef<HTMLInputElement, { value: string; onChange: (value: string) => void; label: string; placeholder?: string; className?: string; shortcut?: string }>(
  function SearchField({ value, onChange, label, placeholder, className, shortcut }, ref) {
    return <div className={cx("relative min-w-0", className)}>
      <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" aria-hidden="true"/>
      <input ref={ref} type="search" aria-label={label} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className={cx(controlBase, "pl-9 pr-9 [&::-webkit-search-cancel-button]:hidden")}/>
      {value ? <button type="button" onClick={() => onChange("")} aria-label="Clear search" className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-ink-3 hover:bg-sunken hover:text-ink"><X size={14}/></button>
        : shortcut && <Kbd className="absolute right-2.5 top-1/2 hidden -translate-y-1/2 sm:inline-flex">{shortcut}</Kbd>}
    </div>;
  });

/** Single-choice control rendered as a joined row; arrow keys move the selection. */
export function Segmented<T extends string>({ value, onChange, options, label, size = "md" }: {
  value: T; onChange: (value: T) => void; options: { value: T; label: string; disabled?: boolean; title?: string }[]; label: string; size?: Size;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (from: number, step: number) => {
    for (let i = 1; i <= options.length; i++) {
      const next = (from + step * i + options.length) % options.length;
      if (!options[next].disabled) { onChange(options[next].value); refs.current[next]?.focus(); return; }
    }
  };
  return <div role="radiogroup" aria-label={label} className="inline-flex max-w-full rounded border border-line-strong bg-sunken/60 p-0.5 scroll-x">
    {options.map((o, i) => {
      const on = o.value === value;
      return <button key={o.value} ref={el => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} disabled={o.disabled} title={o.title}
        onClick={() => onChange(o.value)} onKeyDown={e => {
          if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); move(i, 1); }
          if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); move(i, -1); }
        }}
        className={cx("whitespace-nowrap rounded-[3px] font-medium transition-colors duration-fast disabled:cursor-not-allowed disabled:opacity-45",
          size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3 text-sm",
          on ? "bg-surface text-ink shadow-pop" : "text-ink-2 hover:text-ink")}>{o.label}</button>;
    })}
  </div>;
}

/* ---------- Small display pieces ---------- */

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <kbd className={cx("inline-flex h-5 min-w-5 items-center justify-center rounded-[3px] border border-line-strong bg-surface px-1 font-mono text-[11px] text-ink-3", className)}>{children}</kbd>;
}

/** Record identifiers are mono so they read as references, not prose. */
export function Id({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[0.8em] tracking-tight text-ink-3", className)}>{children}</span>;
}

/**
 * A dot-separated metadata line. Falsy items are skipped. Separators sit in a
 * clipped gutter, so a wrapped line never starts with a stray dot.
 */
export function Meta({ items, className }: { items: React.ReactNode[]; className?: string }) {
  const shown = items.filter(i => i !== null && i !== undefined && i !== false && i !== "");
  return <span className={cx("block overflow-hidden text-xs text-ink-3", className)}>
    <span className="-ml-4 flex flex-wrap items-center gap-y-0.5">
      {shown.map((item, i) => <span key={i} className="inline-flex items-center before:inline-block before:w-4 before:text-center before:text-line-strong before:content-['·']">{item}</span>)}
    </span>
  </span>;
}

type Tone = "neutral" | "accent" | "signal" | "caution" | "positive";
const toneText: Record<Tone, string> = { neutral: "text-ink-2", accent: "text-accent", signal: "text-signal", caution: "text-caution", positive: "text-positive" };
const toneDot: Record<Tone, string> = { neutral: "bg-ink-3", accent: "bg-accent", signal: "bg-signal", caution: "bg-caution", positive: "bg-positive" };
const toneSoft: Record<Tone, string> = { neutral: "bg-sunken text-ink-2", accent: "bg-accent-soft text-accent", signal: "bg-signal-soft text-signal", caution: "bg-caution-soft text-caution", positive: "bg-positive-soft text-positive" };

/** A status marked by a shape and a word, never colour alone. */
export function Status({ tone = "neutral", children, className }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium", toneText[tone], className)}>
    <span aria-hidden="true" className={cx("h-1.5 w-1.5 shrink-0 rounded-full", toneDot[tone])}/>{children}</span>;
}

/** A compact label on a tinted ground. Use sparingly: one per item at most. */
export function Tag({ tone = "neutral", children, className }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-[3px] px-1.5 py-0.5 text-2xs font-medium", toneSoft[tone], className)}>{children}</span>;
}

export const sentimentTone = (s: string): Tone => s === "Negative" ? "signal" : s === "Positive" ? "positive" : s === "Mixed" ? "caution" : "neutral";
export const severityTone = (s: string): Tone => /^(high|critical|urgent)$/i.test(s) ? "signal" : /^medium$/i.test(s) ? "caution" : "neutral";

export type TrendLabel = "new" | "rising" | "falling" | "steady";
const TREND: Record<TrendLabel, { label: string; icon: typeof ArrowRight; tone: Tone }> = {
  new: { label: "New", icon: Plus, tone: "accent" }, rising: { label: "Rising", icon: ArrowUpRight, tone: "signal" },
  falling: { label: "Falling", icon: ArrowDownRight, tone: "neutral" }, steady: { label: "Steady", icon: ArrowRight, tone: "neutral" },
};
export function TrendMark({ trend, recent, prior }: { trend: TrendLabel; recent: number; prior: number }) {
  const { label, icon: Icon, tone } = TREND[trend];
  return <span title={`${recent} in the last 90 days, ${prior} in the 90 days before`} className={cx("inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium", toneText[tone])}>
    <Icon size={13} aria-hidden="true" strokeWidth={2.25}/>{label}<span className="sr-only">: {recent} in the last 90 days versus {prior} before</span></span>;
}

/** A headline figure. With href, the figure opens the records behind it. */
export function Figure({ label, value, detail, href, tone }: { label: string; value: React.ReactNode; detail?: React.ReactNode; href?: string; tone?: "signal" }) {
  const body = <>
    <span className="block text-xs text-ink-2">{label}</span>
    <span className={cx("num mt-1 block font-serif text-[2rem] leading-10 tracking-tight", tone === "signal" ? "text-signal" : "text-ink")} style={{ fontVariationSettings: '"opsz" 60' }}>{value}</span>
    {detail && <span className="mt-0.5 block text-2xs text-ink-3">{detail}</span>}
  </>;
  return href ? <Link href={href} className="group block rounded py-1 transition-colors duration-fast">
    {body}<span className="mt-1 inline-flex items-center gap-1 text-2xs font-medium text-accent opacity-80 group-hover:opacity-100">See records <ArrowRight size={11} className="transition-transform duration-fast group-hover:translate-x-0.5"/></span></Link>
    : <div className="py-1">{body}</div>;
}

/* ---------- Feedback & states ---------- */

const noticeIcon = { info: Info, caution: TriangleAlert, signal: CircleAlert } as const;
export function Notice({ tone = "info", title, children, className, action }: { tone?: keyof typeof noticeIcon; title?: React.ReactNode; children?: React.ReactNode; className?: string; action?: React.ReactNode }) {
  const Icon = noticeIcon[tone];
  const color = tone === "info" ? "border-line bg-surface text-ink-2" : tone === "caution" ? "border-caution/30 bg-caution-soft text-ink" : "border-signal/30 bg-signal-soft text-ink";
  const iconColor = tone === "info" ? "text-accent" : tone === "caution" ? "text-caution" : "text-signal";
  return <div role={tone === "signal" ? "alert" : undefined} className={cx("flex gap-3 rounded-md border px-4 py-3 text-xs leading-5", color, className)}>
    <Icon size={16} className={cx("mt-0.5 shrink-0", iconColor)} aria-hidden="true"/>
    <div className="min-w-0 flex-1">{title && <p className="font-medium text-ink">{title}</p>}{children && <div className={title ? "mt-0.5" : ""}>{children}</div>}</div>
    {action}
  </div>;
}

export function EmptyState({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return <div className="px-6 py-14 text-center">
    <p className="font-serif text-lg text-ink">{title}</p>
    {children && <p className="mx-auto mt-1.5 max-w-sm text-sm text-ink-2">{children}</p>}
    {action && <div className="mt-5 flex justify-center gap-2">{action}</div>}
  </div>;
}

/** Removable filter token. */
export function FilterChip({ label, value, onRemove }: { label: string; value: string; onRemove: () => void }) {
  return <button type="button" onClick={onRemove} aria-label={`Remove filter ${label}: ${value}`}
    className="group inline-flex h-7 items-center gap-1.5 rounded border border-line-strong bg-surface pl-2 pr-1 text-xs text-ink transition-colors duration-fast hover:border-control">
    <span className="text-ink-3">{label}</span><span className="max-w-[16rem] truncate font-medium">{value}</span>
    <span className="flex h-5 w-5 items-center justify-center rounded-[3px] text-ink-3 group-hover:bg-sunken group-hover:text-ink"><X size={12}/></span>
  </button>;
}

export function Pagination({ page, pages, total, noun, onPage }: { page: number; pages: number; total: number; noun: string; onPage: (page: number) => void }) {
  return <nav aria-label="Pagination" className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-ink-2 sm:px-5">
    <span className="num">Page {page} of {Math.max(1, pages)} <span className="text-ink-3">· {total} {noun}</span></span>
    <div className="flex gap-1">
      <IconButton label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)} className="disabled:opacity-35"><ChevronLeft size={18}/></IconButton>
      <IconButton label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)} className="disabled:opacity-35"><ChevronRight size={18}/></IconButton>
    </div>
  </nav>;
}

/** Announces short confirmations ("Saved") to sighted and screen-reader users, then fades. */
export function useFlash(timeout = 3200): [React.ReactNode, (message: string, tone?: "ok" | "error") => void] {
  const [state, setState] = useState<{ message: string; tone: "ok" | "error"; key: number } | null>(null);
  const show = useCallback((message: string, tone: "ok" | "error" = "ok") => setState({ message, tone, key: Date.now() }), []);
  useEffect(() => { if (!state || state.tone === "error") return; const t = setTimeout(() => setState(null), timeout); return () => clearTimeout(t); }, [state, timeout]);
  const node = <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex justify-center px-4 lg:bottom-6">
    {state && <div key={state.key} className={cx("pointer-events-auto flex items-center gap-3 rounded-md px-4 py-2.5 text-sm shadow-overlay animate-rise-in",
      state.tone === "ok" ? "bg-ink text-paper" : "bg-signal text-surface")}>
      {state.message}
      {state.tone === "error" && <button type="button" onClick={() => setState(null)} aria-label="Dismiss" className="-mr-1 rounded p-1 hover:bg-black/10"><X size={14}/></button>}
    </div>}
  </div>;
  return [node, show];
}

export function useMediaQuery(query: string): boolean {
  const [match, setMatch] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query);
    setMatch(m.matches);
    const on = () => setMatch(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}
