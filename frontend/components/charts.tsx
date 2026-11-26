"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Segmented } from "./ui";

// Single-series charts: one hue (accent), no legend (the title names the series),
// recessive grid, 4px rounded data-ends square at the baseline, bars capped at 28px.
// Colours are theme tokens, so light and dark are each designed, not inverted.

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

/** Measures its container so the chart is drawn at real pixel size (labels stay legible on phones). */
function useWidth(): [(el: HTMLDivElement | null) => void, number] {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!node) return;
    setWidth(Math.round(node.getBoundingClientRect().width));
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return [setNode, width];
}

export function MonthlyColumns({ months, values, unit, hrefFor, ariaLabel }: {
  months: string[]; values: number[]; unit: string; hrefFor: (month: string) => string; ariaLabel: string;
}) {
  const router = useRouter();
  const [active, setActive] = useState<number | null>(null);
  const [view, setView] = useState<"chart" | "table">("chart");
  const [box, measured] = useWidth();
  const width = Math.max(280, measured || 720);
  const height = width < 520 ? 200 : 240, left = 32, right = 4, top = 12, bottom = 26;
  const plotW = width - left - right, plotH = height - top - bottom;
  const max = niceMax(Math.max(0, ...values));
  const band = months.length ? plotW / months.length : plotW;
  const barW = Math.min(28, band * 0.6);
  const ticks = [0, max / 2, max];
  const labelEvery = Math.max(1, Math.ceil(36 / band));
  const peak = values.length ? values.indexOf(Math.max(...values)) : -1;

  if (!months.length) return <p className="py-12 text-center text-sm text-ink-2">No records match these filters.</p>;
  return <div ref={box}>
    {view === "table" ? <div className="max-h-80 overflow-y-auto"><table className="w-full text-left text-sm">
      <thead className="sticky top-0 bg-surface text-xs text-ink-3"><tr><th className="py-2 font-medium">Month</th><th className="py-2 text-right font-medium">{unit[0].toUpperCase() + unit.slice(1)}</th></tr></thead>
      <tbody className="divide-y divide-line">{months.map((month, i) => <tr key={month}><td className="py-2 text-ink-2">{monthLong(month)}</td>
        <td className="num py-2 text-right"><Link href={hrefFor(month)} className="link font-medium">{values[i]}</Link></td></tr>)}</tbody>
    </table></div> : <div className="relative">
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block" role="img" aria-label={ariaLabel}>
        {ticks.map(tick => { const y = top + plotH - (tick / max) * plotH; return <g key={tick}>
          <line x1={left} x2={width - right} y1={y} y2={y} className={tick === 0 ? "stroke-line-strong" : "stroke-line"} strokeWidth={1} strokeDasharray={tick === 0 ? undefined : "2 3"}/>
          <text x={left - 8} y={y + 4} textAnchor="end" fontSize={11} className="num fill-ink-3">{Math.round(tick)}</text></g>; })}
        {months.map((month, i) => {
          const value = values[i];
          const h = (value / max) * plotH;
          const x = left + i * band + (band - barW) / 2;
          const y = top + plotH - h;
          const dim = active !== null && active !== i;
          return <g key={month}>
            {value > 0 && <path d={columnPath(x, y, barW, h, 4)} className="fill-accent transition-opacity duration-fast" opacity={dim ? 0.35 : 1}/>}
            {i === peak && active === null && value > 0 && <text x={x + barW / 2} y={y - 5} textAnchor="middle" fontSize={11} className="num fill-ink-2">{value}</text>}
            {i % labelEvery === 0 && <text x={left + i * band + band / 2} y={height - 8} textAnchor="middle" fontSize={11} className="fill-ink-3">{monthLabel(month)}</text>}
            <rect x={left + i * band} y={top} width={band} height={plotH} fill="transparent" tabIndex={0} role="button"
              aria-label={`${monthLong(month)}: ${value} ${unit}. Open records.`} className="cursor-pointer outline-none"
              onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(i)} onBlur={() => setActive(null)}
              onClick={() => router.push(hrefFor(month))} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); router.push(hrefFor(month)); } }}/>
            {active === i && <rect x={left + i * band + 1} y={top} width={band - 2} height={plotH} rx={3} fill="none" className="stroke-accent/40" strokeWidth={1} pointerEvents="none"/>}
          </g>;
        })}
      </svg>
      {active !== null && <div role="tooltip" className="pointer-events-none absolute top-0 z-10 whitespace-nowrap rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-pop"
        style={{ left: `clamp(0px, ${left + active * band + band / 2}px - 70px, ${width - 150}px)` }}>
        <div className="font-medium text-ink">{monthLong(months[active])}</div>
        <div className="text-ink-2"><span className="num font-medium text-ink">{values[active]}</span> {unit}</div>
        <div className="mt-0.5 text-ink-3">Select to open records</div>
      </div>}
    </div>}
    <div className="mt-3 flex justify-end">
      <Segmented size="sm" label="Display as" value={view} onChange={setView} options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]}/>
    </div>
  </div>;
}

/** Ranked horizontal bars. Each row opens the records it counts. */
export function BarList({ items, total, hrefFor, label }: {
  items: { name: string; count: number; detail?: string }[]; total: number;
  hrefFor: (name: string, index: number) => string; label: string;
}) {
  const max = Math.max(1, ...items.map(item => item.count));
  if (!items.length) return <p className="py-6 text-center text-sm text-ink-2">No records match these filters.</p>;
  return <ul className="-mx-2" aria-label={label}>{items.map((item, index) => {
    const share = total ? Math.round((item.count / total) * 100) : 0;
    return <li key={`${item.name}|${item.detail ?? ""}`}>
      <Link href={hrefFor(item.name, index)} aria-label={`${item.name}${item.detail ? ` (${item.detail})` : ""}: ${item.count}, ${share}%. Open records.`}
        className="group grid min-h-10 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded px-2 py-1.5 transition-colors duration-fast hover:bg-sunken/70 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_4.5rem]">
        <span className="min-w-0"><span className="block truncate text-sm text-ink">{item.name}</span>
          {item.detail && <span className="block truncate text-2xs text-ink-3">{item.detail}</span>}</span>
        <span className="num text-right text-sm sm:order-last"><span className="font-medium text-ink">{item.count}</span> <span className="inline-block w-8 text-2xs text-ink-3">{share}%</span></span>
        <span className="col-span-2 h-2 sm:col-span-1" aria-hidden="true">
          <span className="block h-2 rounded-r-[4px] bg-accent transition-opacity duration-fast group-hover:opacity-80" style={{ width: `${Math.max(1.5, (item.count / max) * 100)}%` }}/>
        </span>
      </Link>
    </li>;
  })}</ul>;
}

/** Compact month sparkbars for detail views. */
export function MonthBars({ months, counts }: { months: string[]; counts: number[] }) {
  const max = Math.max(1, ...counts);
  const short = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
  if (!months.length) return null;
  return <div>
    <div className="flex h-14 items-end gap-[2px]" role="img" aria-label={`Records per month: ${months.map((m, i) => `${short(m)} ${counts[i]}`).join(", ")}`}>
      {counts.map((c, i) => <div key={months[i]} title={`${short(months[i])}: ${c}`} className="flex-1 rounded-t-[3px] bg-accent" style={{ height: `${(c / max) * 100}%`, minHeight: c ? 3 : 0 }}/>)}
    </div>
    <div className="mt-1 flex justify-between border-t border-line-strong pt-1 text-2xs text-ink-3"><span>{short(months[0])}</span><span>{short(months[months.length - 1])}</span></div>
  </div>;
}
