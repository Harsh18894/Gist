"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

// Single-series charts: one hue (brand), no legend box (the title names the series),
// recessive grid, 4px rounded data-ends square at the baseline, bars capped at 24px.
const SERIES = "#176c63";
const GRID = "#e5e9ed";
const MUTED = "#667487";

const monthLabel = (month: string) =>
  new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
const monthLong = (month: string) =>
  new Date(`${month}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

function niceMax(value: number): number {
  // Four even steps from zero, each step 1, 2, 2.5 or 5 x 10^k.
  if (value <= 4) return 4;
  const raw = value / 4;
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(x => x * power).find(x => x >= raw) ?? raw;
  return step * 4;
}

function columnPath(x: number, y: number, width: number, height: number, radius: number): string {
  const r = Math.min(radius, width / 2, height);
  const bottom = y + height;
  return `M${x},${bottom} V${y + r} Q${x},${y} ${x + r},${y} H${x + width - r} Q${x + width},${y} ${x + width},${y + r} V${bottom} Z`;
}

export function MonthlyColumns({ months, values, unit, hrefFor, ariaLabel }: {
  months: string[]; values: number[]; unit: string; hrefFor: (month: string) => string; ariaLabel: string;
}) {
  const router = useRouter();
  const [active, setActive] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const width = 720, height = 220, left = 34, right = 8, top = 10, bottom = 26;
  const plotW = width - left - right, plotH = height - top - bottom;
  const max = niceMax(Math.max(0, ...values));
  const band = months.length ? plotW / months.length : plotW;
  const barW = Math.min(24, band * 0.62);
  const ticks = [0, max / 2, max];
  const step = months.length > 14 ? 2 : 1;
  if (!months.length) return <p className="py-10 text-center text-sm text-muted">No records match these filters.</p>;
  return <div>
    <div className="mb-2 flex justify-end">
      <button type="button" onClick={() => setTable(t => !t)} aria-pressed={table}
        className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-ink">{table ? "Show chart" : "Show table"}</button>
    </div>
    {table ? <div className="max-h-72 overflow-y-auto"><table className="w-full text-left text-sm">
      <thead className="text-xs uppercase tracking-wider text-muted"><tr><th className="py-2 font-semibold">Month</th><th className="py-2 text-right font-semibold">{unit}</th></tr></thead>
      <tbody className="divide-y divide-line">{months.map((month, i) => <tr key={month}><td className="py-2">{monthLong(month)}</td>
        <td className="py-2 text-right tabular-nums"><Link href={hrefFor(month)} className="font-semibold text-brand hover:underline">{values[i]}</Link></td></tr>)}</tbody>
    </table></div> : <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={ariaLabel}>
        {ticks.map(tick => { const y = top + plotH - (tick / max) * plotH; return <g key={tick}>
          <line x1={left} x2={width - right} y1={y} y2={y} stroke={GRID} strokeWidth={1}/>
          <text x={left - 6} y={y + 4} textAnchor="end" fontSize={11} fill={MUTED}>{Math.round(tick)}</text></g>; })}
        {months.map((month, i) => {
          const value = values[i];
          const h = (value / max) * plotH;
          const x = left + i * band + (band - barW) / 2;
          const y = top + plotH - h;
          return <g key={month}>
            {value > 0 && <path d={columnPath(x, y, barW, h, 4)} fill={SERIES} opacity={active === null || active === i ? 1 : 0.45}/>}
            {i % step === 0 && <text x={left + i * band + band / 2} y={height - 8} textAnchor="middle" fontSize={11} fill={MUTED}>{monthLabel(month)}</text>}
            <rect x={left + i * band} y={top} width={band} height={plotH} fill="transparent" tabIndex={0} role="button"
              aria-label={`${monthLong(month)}: ${value} ${unit}. Open records.`} className="cursor-pointer outline-none focus-visible:stroke-brand"
              onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(i)} onBlur={() => setActive(null)}
              onClick={() => router.push(hrefFor(month))} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); router.push(hrefFor(month)); } }}/>
          </g>;
        })}
      </svg>
      {active !== null && <div role="tooltip" className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-panel"
        style={{ left: `${((left + active * band + band / 2) / width) * 100}%` }}>
        <div className="font-semibold text-ink">{monthLong(months[active])}</div>
        <div className="text-muted"><span className="font-semibold tabular-nums text-ink">{values[active]}</span> {unit} · click to open</div>
      </div>}
    </div>}
  </div>;
}

export function BarList({ items, total, hrefFor, label }: {
  items: { name: string; count: number; detail?: string }[]; total: number;
  hrefFor: (name: string, index: number) => string; label: string;
}) {
  const max = Math.max(1, ...items.map(item => item.count));
  if (!items.length) return <p className="py-6 text-center text-sm text-muted">No records match these filters.</p>;
  return <ul className="space-y-3" aria-label={label}>{items.map((item, index) => {
    const share = total ? Math.round((item.count / total) * 100) : 0;
    return <li key={`${item.name}|${item.detail ?? ""}`}>
      <Link href={hrefFor(item.name, index)} title={`${item.name}${item.detail ? ` (${item.detail})` : ""}: ${item.count} (${share}%). Open records.`}
        className="group grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_3.5rem] items-center gap-3 rounded-md text-sm">
        <span className="min-w-0"><span className="block truncate text-ink group-hover:text-brand group-hover:underline">{item.name}</span>
          {item.detail && <span className="block truncate text-xs text-muted">{item.detail}</span>}</span>
        <span className="h-2.5 rounded-r-[4px] bg-canvas" aria-hidden="true">
          <span className="block h-2.5 rounded-r-[4px]" style={{ width: `${(item.count / max) * 100}%`, background: SERIES }}/>
        </span>
        <span className="text-right tabular-nums"><span className="font-semibold text-ink">{item.count}</span> <span className="text-xs text-muted">{share}%</span></span>
      </Link>
    </li>;
  })}</ul>;
}
