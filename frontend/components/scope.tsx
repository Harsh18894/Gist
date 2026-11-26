"use client";

import { useId, useState } from "react";
import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { areas, segments } from "@/lib/api";
import { Button, cx, Field, Input, Select } from "./ui";

export type Scope = { from_date: string; to_date: string; segment: string; product_area: string };
export const EMPTY_SCOPE: Scope = { from_date: "", to_date: "", segment: "", product_area: "" };
export const activeCount = (s: Scope) => Object.values(s).filter(Boolean).length;
export const invalidRange = (s: Scope) => Boolean(s.from_date && s.to_date && s.from_date > s.to_date);

/**
 * Date range, segment and product area. On phones the fields fold behind a
 * "Filters" button that shows how many are active; on wider screens they sit in one row.
 */
export function ScopeFields({ value, onChange, compact = false, className }: { value: Scope; onChange: (next: Scope) => void; compact?: boolean; className?: string }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const count = activeCount(value);
  const set = (key: keyof Scope) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange({ ...value, [key]: e.target.value });
  const bad = invalidRange(value);
  return <div className={className}>
    <div className={cx("flex items-center gap-2", compact ? "" : "sm:hidden")}>
      <Button size="md" onClick={() => setOpen(o => !o)} aria-expanded={open} aria-controls={`${id}-fields`}>
        <SlidersHorizontal size={15}/>Filters{count > 0 && <span className="num rounded-[3px] bg-accent px-1.5 text-2xs text-accent-ink">{count}</span>}
      </Button>
      {count > 0 && <Button variant="ghost" onClick={() => onChange(EMPTY_SCOPE)}>Clear</Button>}
    </div>
    <div id={`${id}-fields`} className={cx("grid grid-cols-2 items-end gap-3",
      compact ? (open ? "mt-3" : "hidden") : cx(open ? "mt-3 sm:mt-0" : "hidden", "sm:grid sm:grid-cols-[repeat(4,minmax(0,1fr))_auto]"))}>
      <Field label="From" htmlFor={`${id}-from`}><Input id={`${id}-from`} type="date" value={value.from_date} max={value.to_date || undefined} onChange={set("from_date")} aria-invalid={bad || undefined}/></Field>
      <Field label="To" htmlFor={`${id}-to`}><Input id={`${id}-to`} type="date" value={value.to_date} min={value.from_date || undefined} onChange={set("to_date")} aria-invalid={bad || undefined}/></Field>
      <Field label="Segment" htmlFor={`${id}-seg`}><Select id={`${id}-seg`} value={value.segment} onChange={set("segment")}><option value="">All segments</option>{segments.map(x => <option key={x}>{x}</option>)}</Select></Field>
      <Field label="Product area" htmlFor={`${id}-area`}><Select id={`${id}-area`} value={value.product_area} onChange={set("product_area")}><option value="">All areas</option>{areas.map(x => <option key={x}>{x}</option>)}</Select></Field>
      {!compact && <Button variant="ghost" onClick={() => onChange(EMPTY_SCOPE)} disabled={count === 0} className="col-span-2 hidden sm:col-span-1 sm:inline-flex"><RotateCcw size={14}/>Reset</Button>}
    </div>
    {bad && <p role="alert" className="mt-2 text-xs font-medium text-signal">The start date is after the end date. Change one of them to see results.</p>}
  </div>;
}
