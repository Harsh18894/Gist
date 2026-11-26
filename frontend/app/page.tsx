"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CalendarRange, TriangleAlert } from "lucide-react";
import { AnalyticsReleases, AnalyticsRepeated, AnalyticsSummary, AnalyticsTrends, apiGet, query, TrendMetric } from "@/lib/api";
import { BarList, MonthlyColumns } from "@/components/charts";
import { EMPTY_SCOPE, invalidRange as isInvalid, Scope, ScopeFields } from "@/components/scope";
import { ErrorState, Loading } from "@/components/states";
import { Figure, Id, PageHeader, Panel, Section, Segmented } from "@/components/ui";

const METRICS: { value: TrendMetric; label: string; unit: string; title: string }[] = [
  { value: "feedback", label: "Feedback", unit: "feedback records", title: "Feedback per month" },
  { value: "negative_feedback", label: "Negative", unit: "negative records", title: "Negative feedback per month" },
  { value: "tickets", label: "Tickets", unit: "tickets", title: "Support tickets per month" },
];
const percent = (value: number | null) => value === null ? "—" : `${Math.round(value * 100)}%`;
const longDate = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

function monthBounds(month: string, filters: Scope): { from_date: string; to_date: string } {
  const [year, m] = month.split("-").map(Number);
  const last = new Date(Date.UTC(year, m, 0)).getUTCDate();
  const start = `${month}-01`, end = `${month}-${String(last).padStart(2, "0")}`;
  return { from_date: filters.from_date && filters.from_date > start ? filters.from_date : start,
           to_date: filters.to_date && filters.to_date < end ? filters.to_date : end };
}

function Change({ before, after, href, label }: { before: number; after: number; href: { before: string; after: string }; label: string }) {
  const delta = after - before;
  return <span className="num inline-flex items-baseline gap-1.5 whitespace-nowrap">
    <span className="sr-only">{label}: </span>
    <Link href={href.before} className="link text-ink-2">{before}</Link>
    <span className="text-ink-3" aria-hidden="true">→</span><span className="sr-only"> before, then </span>
    <Link href={href.after} className="link font-medium">{after}</Link>
    {delta !== 0 && <span className={`text-2xs ${delta > 0 ? "text-signal" : "text-ink-3"}`}>{delta > 0 ? "+" : "−"}{Math.abs(delta)}</span>}
  </span>;
}

function NextStep({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="group mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-accent">{children}<ArrowRight size={13} className="transition-transform duration-fast group-hover:translate-x-0.5"/></Link>;
}

export default function ProductIntelligence() {
  const [filters, setFilters] = useState<Scope>(EMPTY_SCOPE);
  const [metric, setMetric] = useState<TrendMetric>("feedback");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [trends, setTrends] = useState<AnalyticsTrends | null>(null);
  const [releases, setReleases] = useState<AnalyticsReleases | null>(null);
  const [repeated, setRepeated] = useState<AnalyticsRepeated | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  const scope = useMemo(() => query(filters), [filters]);
  const invalidRange = isInvalid(filters);

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
  const metricInfo = METRICS.find(m => m.value === metric)!;
  const highSeverity = summary?.tickets_by_severity.find(s => s.name === "High")?.count ?? 0;
  const quality = summary?.data_quality;
  const topCategory = summary?.by_category.find(c => c.name !== "Multiple issues" && c.name !== "Unclear");

  const lede = summary && summary.feedback_count > 0 && summary.date_range.first
    ? <>{summary.feedback_count} feedback records from {longDate(summary.date_range.first)} to {longDate(summary.date_range.last!)}. <span className="text-ink">{percent(summary.negative_share)} are negative</span>{topCategory ? <>; the most common problem is <span className="text-ink">{topCategory.name.toLowerCase()}</span>.</> : "."} Select any figure to see the records behind it.</>
    : "What customers are telling you, counted from the data. Select any figure to see the records behind it.";

  return <>
    <PageHeader title="Overview" lede={lede}/>

    <form aria-label="Filters" onSubmit={e => e.preventDefault()} className="mb-8"><ScopeFields value={filters} onChange={setFilters}/></form>

    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !summary ? <Loading label="Counting records…" rows={6}/> : <div className="space-y-12">
      <Panel className="grid grid-cols-2 divide-line px-5 py-4 lg:grid-cols-4 lg:divide-x [&>*]:py-2 lg:[&>*]:px-6 lg:[&>*:first-child]:pl-0">
        <Figure label="Feedback records" value={summary.feedback_count} href={feedbackHref()} detail={summary.date_range.first ? `${longDate(summary.date_range.first)} – ${longDate(summary.date_range.last!)}` : "No records in range"}/>
        <Figure label="Negative share" value={percent(summary.negative_share)} href={feedbackHref({ sentiment: "Negative" })} detail={`${summary.negative_feedback_count} negative records`}/>
        <Figure label="Support tickets" value={summary.ticket_count} href={ticketsHref()} detail="Within the same filters"/>
        <Figure label="High-severity tickets" value={highSeverity} href={ticketsHref({ severity: "High" })} detail="As recorded on the ticket" tone={highSeverity > 0 ? "signal" : undefined}/>
      </Panel>

      <Panel as="section" aria-labelledby="trend-title" className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div><h2 id="trend-title" className="text-base font-semibold">{metricInfo.title}</h2>
            <p className="mt-0.5 text-xs text-ink-3">Calendar months; empty months show zero. Select a month to open its records.</p></div>
          <Segmented label="Trend metric" value={metric} onChange={setMetric} options={METRICS.map(m => ({ value: m.value, label: m.label }))}/>
        </div>
        {!trends ? <Loading label="Loading trend…" rows={3}/> : <MonthlyColumns months={trends.months} values={trends.series[0] ? trends.months.map((_, i) => trends.series.reduce((sum, s) => sum + s.counts[i], 0)) : trends.months.map(() => 0)}
          unit={metricInfo.unit} ariaLabel={`${metricInfo.title}, ${trends.total} in total.`}
          hrefFor={month => metric === "tickets" ? ticketsHref(monthBounds(month, filters))
            : feedbackHref({ ...monthBounds(month, filters), ...(metric === "negative_feedback" ? { sentiment: "Negative" } : {}) })}/>}
      </Panel>

      <div className="grid gap-x-12 gap-y-12 xl:grid-cols-2">
        <Section id="category-title" title="What customers raise" description="Feedback by recorded issue category">
          <BarList label="Feedback by issue category" items={summary.by_category} total={summary.feedback_count} hrefFor={name => feedbackHref({ category: name })}/>
          <NextStep href="/issues">See these grouped into recurring issues</NextStep>
        </Section>
        <div className="space-y-12">
          <Section id="segment-title" title="Who is saying it" description="Feedback by customer segment">
            <BarList label="Feedback by segment" items={summary.by_segment} total={summary.feedback_count} hrefFor={name => feedbackHref({ segment: name })}/>
          </Section>
          <Section id="area-title" title="Where in the product" description="Feedback by product area">
            <BarList label="Feedback by product area" items={summary.by_area} total={summary.feedback_count} hrefFor={name => feedbackHref({ product_area: name })}/>
          </Section>
        </div>
      </div>

      <div className="grid gap-x-12 gap-y-12 md:grid-cols-2">
        <Section id="severity-title" title="Ticket severity">
          <BarList label="Tickets by severity" items={summary.tickets_by_severity} total={summary.ticket_count} hrefFor={name => ticketsHref({ severity: name })}/>
        </Section>
        <Section id="status-title" title="Ticket status">
          <BarList label="Tickets by status" items={summary.tickets_by_status} total={summary.ticket_count} hrefFor={name => ticketsHref({ status: name })}/>
        </Section>
      </div>

      {releases && <Section id="release-title" title="Around each release" description={`Feedback and tickets in the release’s product area, ${releases.window_days} days before vs. ${releases.window_days} days from the release date.`}>
        <p className="mb-4 flex items-start gap-2 text-xs text-ink-2"><CalendarRange size={14} className="mt-0.5 shrink-0 text-caution" aria-hidden="true"/><span><span className="font-medium text-ink">Association, not causation.</span> {releases.interpretation} Reports can rise or fall for reasons unrelated to a release.</span></p>
        {releases.releases.length === 0 ? <p className="py-6 text-sm text-ink-2">No releases fall within these filters.</p> : <>
          <table className="hidden w-full text-left text-sm md:table">
            <thead className="text-xs text-ink-3"><tr className="border-b border-line"><th className="py-2 pr-4 font-medium">Release</th><th className="py-2 pr-4 font-medium">Area</th><th className="py-2 pr-4 font-medium">Feedback <span className="font-normal">before → after</span></th><th className="py-2 pr-4 font-medium">Negative</th><th className="py-2 font-medium">Tickets</th></tr></thead>
            <tbody className="divide-y divide-line">{releases.releases.map(r => {
              const window = (w: typeof r.before, extra: Record<string, string> = {}) => ({ ...filters, product_area: r.product_area ?? "", from_date: w.from_date, to_date: w.to_date, ...extra });
              return <tr key={r.id} className="align-top"><td className="py-3 pr-4"><div className="text-ink">{r.title.replace(/^Pulse release \d+:\s*/, "")}</div><div className="mt-0.5 text-xs text-ink-3">{longDate(r.published)} · <Id>{r.id}</Id></div></td>
                <td className="py-3 pr-4 text-ink-2">{r.product_area ?? "(missing)"}</td>
                <td className="py-3 pr-4"><Change label="Feedback" before={r.before.feedback} after={r.after.feedback} href={{ before: `/feedback${query(window(r.before))}`, after: `/feedback${query(window(r.after))}` }}/></td>
                <td className="py-3 pr-4"><Change label="Negative" before={r.before.negative_feedback} after={r.after.negative_feedback} href={{ before: `/feedback${query(window(r.before, { sentiment: "Negative" }))}`, after: `/feedback${query(window(r.after, { sentiment: "Negative" }))}` }}/></td>
                <td className="py-3"><Change label="Tickets" before={r.before.tickets} after={r.after.tickets} href={{ before: `/tickets${query(window(r.before))}`, after: `/tickets${query(window(r.after))}` }}/></td></tr>;
            })}</tbody></table>
          <ul className="divide-y divide-line md:hidden">{releases.releases.map(r => {
            const window = (w: typeof r.before, extra: Record<string, string> = {}) => ({ ...filters, product_area: r.product_area ?? "", from_date: w.from_date, to_date: w.to_date, ...extra });
            return <li key={r.id} className="py-3">
              <p className="text-sm text-ink">{r.title.replace(/^Pulse release \d+:\s*/, "")}</p>
              <p className="mt-0.5 text-xs text-ink-3">{longDate(r.published)} · {r.product_area ?? "(missing area)"} · <Id>{r.id}</Id></p>
              <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-ink-3">Feedback</dt><dd><Change label="Feedback" before={r.before.feedback} after={r.after.feedback} href={{ before: `/feedback${query(window(r.before))}`, after: `/feedback${query(window(r.after))}` }}/></dd></div>
                <div><dt className="text-ink-3">Negative</dt><dd><Change label="Negative" before={r.before.negative_feedback} after={r.after.negative_feedback} href={{ before: `/feedback${query(window(r.before, { sentiment: "Negative" }))}`, after: `/feedback${query(window(r.after, { sentiment: "Negative" }))}` }}/></dd></div>
                <div><dt className="text-ink-3">Tickets</dt><dd><Change label="Tickets" before={r.before.tickets} after={r.after.tickets} href={{ before: `/tickets${query(window(r.before))}`, after: `/tickets${query(window(r.after))}` }}/></dd></div>
              </dl></li>;
          })}</ul>
        </>}
      </Section>}

      <div className="grid gap-x-12 gap-y-12 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        {repeated && <Section id="repeated-title" title="Repeated complaints" description="Features with the most negative reports, and negative or mixed feedback repeated word for word">
          <BarList label="Negative feedback by feature" items={repeated.top_negative_features.map(f => ({ name: f.feature, detail: f.category, count: f.count }))}
            total={summary.negative_feedback_count} hrefFor={(_name, index) => { const f = repeated.top_negative_features[index]; return feedbackHref({ feature: f.feature, category: f.category, sentiment: "Negative" }); }}/>
          <h3 className="eyebrow mb-1 mt-8">Repeated word for word</h3>
          {repeated.repeated_texts.length === 0 ? <p className="py-3 text-sm text-ink-2">No exact repeats within these filters.</p> :
            <ul className="divide-y divide-line">{repeated.repeated_texts.map(r => <li key={r.text} className="flex items-start justify-between gap-4 py-3">
              <q className="voice text-[0.975rem] leading-6">{r.text}</q>
              <Link href={feedbackHref({ query: r.text.slice(0, 200) })} className="link num shrink-0 text-sm font-medium" aria-label={`Repeated ${r.count} times. Open records.`}>{r.count}×</Link></li>)}</ul>}
          <p className="mt-3 text-2xs text-ink-3">{repeated.note}</p>
        </Section>}
        {quality && <Section id="quality-title" title="Data quality" description="Records counted above that can’t be attributed precisely">
          <ul className="divide-y divide-line text-sm">{[
            { label: "No specific feature", value: quality.unspecified_feature, href: feedbackHref({ feature: "unspecified" }) },
            { label: "Category “Unclear”", value: quality.unclear_category, href: feedbackHref({ category: "Unclear" }) },
            { label: "Category “Multiple issues”", value: quality.multiple_issues, href: feedbackHref({ category: "Multiple issues" }) },
            { label: "Missing segment", value: quality.missing_segment, href: null },
            { label: "Missing product area", value: quality.missing_area, href: null }].map(q =>
            <li key={q.label} className="flex min-h-11 items-center justify-between gap-3 py-2"><span className="flex items-center gap-2 text-ink-2">
              {q.value > 0 ? <TriangleAlert size={14} className="text-caution" aria-label="Needs attention"/> : <span className="w-[14px]" aria-hidden="true"/>}{q.label}</span>
              {q.href && q.value > 0 ? <Link href={q.href} className="link num font-medium">{q.value}</Link> : <span className="num font-medium text-ink">{q.value}</span>}</li>)}</ul>
          <p className="mt-3 text-2xs text-ink-3">Category and feature labels arrive with the synthetic records; Gist does not infer them.</p>
        </Section>}
      </div>
    </div>}
  </>;
}
