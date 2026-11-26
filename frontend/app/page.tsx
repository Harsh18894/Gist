"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CalendarRange, FileText, MessagesSquare, RotateCcw, ShieldAlert, TrendingDown } from "lucide-react";
import { AnalyticsReleases, AnalyticsRepeated, AnalyticsSummary, AnalyticsTrends, apiGet, areas, query, segments, TrendMetric } from "@/lib/api";
import { BarList, MonthlyColumns } from "@/components/charts";
import { ErrorState, Loading } from "@/components/states";

type Filters = { from_date: string; to_date: string; segment: string; product_area: string };
const EMPTY: Filters = { from_date: "", to_date: "", segment: "", product_area: "" };
const METRICS: { value: TrendMetric; label: string; unit: string }[] = [
  { value: "feedback", label: "All feedback", unit: "feedback records" },
  { value: "negative_feedback", label: "Negative feedback", unit: "negative records" },
  { value: "tickets", label: "Support tickets", unit: "tickets" },
];
const percent = (value: number | null) => value === null ? "—" : `${Math.round(value * 100)}%`;
const longDate = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

function monthBounds(month: string, filters: Filters): { from_date: string; to_date: string } {
  const [year, m] = month.split("-").map(Number);
  const last = new Date(Date.UTC(year, m, 0)).getUTCDate();
  const start = `${month}-01`, end = `${month}-${String(last).padStart(2, "0")}`;
  return { from_date: filters.from_date && filters.from_date > start ? filters.from_date : start,
           to_date: filters.to_date && filters.to_date < end ? filters.to_date : end };
}

function Panel({ title, subtitle, children, id }: { title: string; subtitle?: string; children: React.ReactNode; id: string }) {
  return <section aria-labelledby={id} className="rounded-2xl border border-line bg-white p-6 shadow-panel">
    <h2 id={id} className="text-lg font-bold">{title}</h2>
    {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
    <div className="mt-5">{children}</div>
  </section>;
}

function Change({ before, after, href }: { before: number; after: number; href: { before: string; after: string } }) {
  return <span className="tabular-nums">
    <Link href={href.before} className="text-brand hover:underline">{before}</Link>
    <span className="mx-1.5 text-muted" aria-hidden="true">→</span><span className="sr-only"> before, then </span>
    <Link href={href.after} className="font-semibold text-brand hover:underline">{after}</Link>
  </span>;
}

export default function ProductIntelligence() {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [metric, setMetric] = useState<TrendMetric>("feedback");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trends, setTrends] = useState<AnalyticsTrends | null>(null);
  const [releases, setReleases] = useState<AnalyticsReleases | null>(null);
  const [repeated, setRepeated] = useState<AnalyticsRepeated | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  const scope = useMemo(() => query(filters), [filters]);
  const invalidRange = Boolean(filters.from_date && filters.to_date && filters.from_date > filters.to_date);

  useEffect(() => {
    if (invalidRange) return;
    const controller = new AbortController();
    Promise.all([
      apiGet<AnalyticsSummary>(`/api/analytics/summary${scope}`, controller.signal),
      apiGet<AnalyticsReleases>(`/api/analytics/releases${scope}`, controller.signal),
      apiGet<AnalyticsRepeated>(`/api/analytics/repeated${scope}`, controller.signal),
    ]).then(([s, r, p]) => { setSummary(s); setReleases(r); setRepeated(p); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [scope, attempt, invalidRange]);

  useEffect(() => {
    if (invalidRange) return;
    const controller = new AbortController();
    apiGet<AnalyticsTrends>(`/api/analytics/trends${query({ ...filters, metric })}`, controller.signal)
      .then(setTrends).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [filters, metric, attempt, invalidRange]);

  const feedbackHref = (extra: Record<string, string> = {}) => `/feedback${query({ ...filters, ...extra })}`;
  const ticketsHref = (extra: Record<string, string> = {}) => `/tickets${query({ ...filters, ...extra })}`;
  const set = (key: keyof Filters) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setFilters(f => ({ ...f, [key]: event.target.value }));
  const metricInfo = METRICS.find(m => m.value === metric)!;
  const highSeverity = summary?.tickets_by_severity.find(s => s.name === "High")?.count ?? 0;
  const quality = summary?.data_quality;

  return <>
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div><p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-brand">Product intelligence / Pulse</p>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Overview</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">What customers are telling you, measured. Every number is counted from the synthetic Pulse dataset — select any figure to see the records behind it.</p></div>
    </div>

    <form aria-label="Filters" onSubmit={e => e.preventDefault()} className="mb-6 flex flex-wrap items-end gap-3 rounded-2xl border border-line bg-white p-4 shadow-panel">
      <label className="text-xs font-semibold uppercase tracking-wider text-muted">From<input type="date" value={filters.from_date} onChange={set("from_date")} className="mt-1.5 block h-10 rounded-lg border border-line px-3 text-sm normal-case tracking-normal text-ink"/></label>
      <label className="text-xs font-semibold uppercase tracking-wider text-muted">To<input type="date" value={filters.to_date} onChange={set("to_date")} className="mt-1.5 block h-10 rounded-lg border border-line px-3 text-sm normal-case tracking-normal text-ink"/></label>
      <label className="text-xs font-semibold uppercase tracking-wider text-muted">Segment<select value={filters.segment} onChange={set("segment")} className="mt-1.5 block h-10 rounded-lg border border-line bg-white px-3 text-sm normal-case tracking-normal text-ink"><option value="">All segments</option>{segments.map(x => <option key={x}>{x}</option>)}</select></label>
      <label className="text-xs font-semibold uppercase tracking-wider text-muted">Product area<select value={filters.product_area} onChange={set("product_area")} className="mt-1.5 block h-10 rounded-lg border border-line bg-white px-3 text-sm normal-case tracking-normal text-ink"><option value="">All areas</option>{areas.map(x => <option key={x}>{x}</option>)}</select></label>
      <button type="button" onClick={() => setFilters(EMPTY)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-muted hover:text-ink"><RotateCcw size={15}/>Reset</button>
      <span className="ml-auto rounded-full bg-pale px-3 py-1.5 text-xs font-semibold text-brand">Synthetic Pulse data</span>
      {invalidRange && <p role="alert" className="w-full text-sm text-rose-700">“From” must be on or before “To”.</p>}
    </form>

    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !summary ? <Loading/> : <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[{ label: "Feedback records", value: String(summary.feedback_count), href: feedbackHref(), icon: MessagesSquare, detail: summary.date_range.first ? `${longDate(summary.date_range.first)} – ${longDate(summary.date_range.last!)}` : "No records in range" },
          { label: "Negative share", value: percent(summary.negative_share), href: feedbackHref({ sentiment: "Negative" }), icon: TrendingDown, detail: `${summary.negative_feedback_count} negative records` },
          { label: "Support tickets", value: String(summary.ticket_count), href: ticketsHref(), icon: FileText, detail: "Tickets in the same filters" },
          { label: "High-severity tickets", value: String(highSeverity), href: ticketsHref({ severity: "High" }), icon: ShieldAlert, detail: "Severity recorded on the ticket" }]
          .map(({ label, value, href, icon: Icon, detail }) => <Link key={label} href={href} className="rounded-2xl border border-line bg-white p-5 shadow-panel transition hover:border-brand">
            <div className="mb-4 flex items-center justify-between"><span className="text-sm font-medium text-muted">{label}</span><span className="rounded-lg bg-canvas p-2 text-brand"><Icon size={17}/></span></div>
            <div className="text-3xl font-bold tabular-nums">{value}</div><p className="mt-2 text-xs text-muted">{detail}</p></Link>)}
      </div>

      <Panel id="trend-title" title={`${metricInfo.label} by month`} subtitle="Counted per calendar month; months with no records show zero. Select a month to open its records.">
        <div className="mb-3 flex flex-wrap gap-2" role="radiogroup" aria-label="Trend metric">{METRICS.map(m =>
          <button key={m.value} type="button" role="radio" aria-checked={metric === m.value} onClick={() => setMetric(m.value)}
            className={`rounded-full px-3 py-1.5 text-xs font-semibold ${metric === m.value ? "bg-brand text-white" : "border border-line text-muted hover:text-ink"}`}>{m.label}</button>)}</div>
        {!trends ? <Loading label="Loading trend…"/> : <MonthlyColumns months={trends.months} values={trends.series[0] ? trends.months.map((_, i) => trends.series.reduce((sum, s) => sum + s.counts[i], 0)) : trends.months.map(() => 0)}
          unit={metricInfo.unit} ariaLabel={`${metricInfo.label} per month, ${trends.total} in total.`}
          hrefFor={month => metric === "tickets" ? ticketsHref(monthBounds(month, filters))
            : feedbackHref({ ...monthBounds(month, filters), ...(metric === "negative_feedback" ? { sentiment: "Negative" } : {}) })}/>}
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel id="category-title" title="Issue categories" subtitle="Feedback by recorded category">
          <BarList label="Feedback by issue category" items={summary.by_category} total={summary.feedback_count} hrefFor={name => feedbackHref({ category: name })}/>
        </Panel>
        <div className="space-y-6">
          <Panel id="segment-title" title="Customer segments">
            <BarList label="Feedback by segment" items={summary.by_segment} total={summary.feedback_count} hrefFor={name => feedbackHref({ segment: name })}/>
          </Panel>
          <Panel id="area-title" title="Product areas">
            <BarList label="Feedback by product area" items={summary.by_area} total={summary.feedback_count} hrefFor={name => feedbackHref({ product_area: name })}/>
          </Panel>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel id="severity-title" title="Ticket severity">
          <BarList label="Tickets by severity" items={summary.tickets_by_severity} total={summary.ticket_count} hrefFor={name => ticketsHref({ severity: name })}/>
        </Panel>
        <Panel id="status-title" title="Ticket status">
          <BarList label="Tickets by status" items={summary.tickets_by_status} total={summary.ticket_count} hrefFor={name => ticketsHref({ status: name })}/>
        </Panel>
      </div>

      {releases && <Panel id="release-title" title="Release timeline" subtitle={`Feedback and tickets in each release's product area, ${releases.window_days} days before vs. ${releases.window_days} days from the release date. ${releases.interpretation}`}>
        <div className="mb-4 flex items-start gap-2 rounded-lg bg-canvas p-3 text-xs leading-5 text-muted"><CalendarRange size={15} className="mt-0.5 shrink-0 text-brand"/>A change after a release shows timing only. Reports can rise or fall for reasons unrelated to the release.</div>
        {releases.releases.length === 0 ? <p className="text-sm text-muted">No releases match these filters.</p> : <div className="relative overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
          <thead className="text-xs uppercase tracking-wider text-muted"><tr><th className="py-2 pr-4 font-semibold">Release</th><th className="py-2 pr-4 font-semibold">Area</th><th className="py-2 pr-4 font-semibold">Feedback (before → after)</th><th className="py-2 pr-4 font-semibold">Negative</th><th className="py-2 font-semibold">Tickets</th></tr></thead>
          <tbody className="divide-y divide-line">{releases.releases.map(r => {
            const window = (w: typeof r.before, extra: Record<string, string> = {}) => ({ ...filters, product_area: r.product_area ?? "", from_date: w.from_date, to_date: w.to_date, ...extra });
            return <tr key={r.id}><td className="py-3 pr-4"><div className="font-medium">{r.title.replace(/^Pulse release \d+:\s*/, "")}</div><div className="text-xs text-muted">{longDate(r.published)} · {r.id}</div></td>
              <td className="py-3 pr-4 text-muted">{r.product_area ?? "(missing)"}</td>
              <td className="py-3 pr-4"><Change before={r.before.feedback} after={r.after.feedback} href={{ before: `/feedback${query(window(r.before))}`, after: `/feedback${query(window(r.after))}` }}/></td>
              <td className="py-3 pr-4"><Change before={r.before.negative_feedback} after={r.after.negative_feedback} href={{ before: `/feedback${query(window(r.before, { sentiment: "Negative" }))}`, after: `/feedback${query(window(r.after, { sentiment: "Negative" }))}` }}/></td>
              <td className="py-3"><Change before={r.before.tickets} after={r.after.tickets} href={{ before: `/tickets${query(window(r.before))}`, after: `/tickets${query(window(r.after))}` }}/></td></tr>;
          })}</tbody></table></div>}
      </Panel>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        {repeated && <Panel id="repeated-title" title="Repeated complaints" subtitle="Negative or mixed feedback repeated word for word, and the features with the most negative reports.">
          <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted">Top negative features</h3>
          <BarList label="Negative feedback by feature" items={repeated.top_negative_features.map(f => ({ name: f.feature, detail: f.category, count: f.count }))}
            total={summary.negative_feedback_count} hrefFor={(_name, index) => { const f = repeated.top_negative_features[index]; return feedbackHref({ feature: f.feature, category: f.category, sentiment: "Negative" }); }}/>
          <h3 className="mb-2 mt-6 text-xs font-bold uppercase tracking-wider text-muted">Repeated word for word</h3>
          {repeated.repeated_texts.length === 0 ? <p className="text-sm text-muted">No exact repeats in these filters.</p> :
            <ul className="divide-y divide-line">{repeated.repeated_texts.map(r => <li key={r.text} className="flex items-start justify-between gap-4 py-3 text-sm">
              <span className="leading-6">“{r.text}”</span>
              <Link href={feedbackHref({ query: r.text.slice(0, 200) })} className="shrink-0 font-semibold tabular-nums text-brand hover:underline">{r.count}×</Link></li>)}</ul>}
          <p className="mt-3 text-xs text-muted">{repeated.note}</p>
        </Panel>}
        {quality && <Panel id="quality-title" title="Data quality" subtitle="Records that analytics count but cannot attribute precisely.">
          <ul className="divide-y divide-line text-sm">{[
            { label: "No specific feature", value: quality.unspecified_feature, href: feedbackHref({ feature: "unspecified" }) },
            { label: "Category “Unclear”", value: quality.unclear_category, href: feedbackHref({ category: "Unclear" }) },
            { label: "Category “Multiple issues”", value: quality.multiple_issues, href: feedbackHref({ category: "Multiple issues" }) },
            { label: "Missing segment", value: quality.missing_segment, href: null },
            { label: "Missing product area", value: quality.missing_area, href: null }].map(q =>
            <li key={q.label} className="flex items-center justify-between py-3"><span className="flex items-center gap-2">{q.value > 0 && <AlertTriangle size={14} className="text-amber-600" aria-label="Needs attention"/>}{q.label}</span>
              {q.href && q.value > 0 ? <Link href={q.href} className="font-semibold tabular-nums text-brand hover:underline">{q.value}</Link> : <span className="font-semibold tabular-nums">{q.value}</span>}</li>)}</ul>
          <p className="mt-3 text-xs leading-5 text-muted">Category and feature labels come with the synthetic records; Gist does not infer them.</p>
        </Panel>}
      </div>
    </div>}
  </>;
}
