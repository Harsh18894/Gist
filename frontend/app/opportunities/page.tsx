"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, ChevronRight, FileText, Minus } from "lucide-react";
import { apiGet, areas, OpportunityDetail, OpportunityList, OpportunitySummary } from "@/lib/api";
import { MonthBars } from "@/components/charts";
import { Dialog } from "@/components/dialog";
import { ErrorState, Loading } from "@/components/states";
import { buttonClass, Id, Meta, Notice, PageHeader, SearchField, Select, severityTone, Status, TrendMark } from "@/components/ui";

const SORTS = {
  evidence: { label: "Most evidence", key: (o: OpportunitySummary) => o.frequency.records },
  tickets: { label: "Most linked tickets", key: (o: OpportunitySummary) => o.evidence.linked_tickets },
  negative: { label: "Highest negative share", key: (o: OpportunitySummary) => o.severity_proxy.negative_share },
  recent: { label: "Most recent activity", key: (o: OpportunitySummary) => o.trend.recent_90_days },
} as const;
const CHECK_LABELS: Record<string, string> = { focus: "One product area", cohesion: "Tightly grouped", corroboration: "Ticket corroborates", evidence: "5+ records" };
const pct = (value: number) => `${Math.round(value * 100)}%`;

function Checklist({ checks, rubric }: { checks: Record<string, boolean>; rubric?: { check: string; rule: string }[] }) {
  return <ul className="space-y-2.5 text-sm">{Object.entries(checks).map(([key, ok]) => <li key={key} className="flex items-start gap-2.5">
    <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] ${ok ? "bg-accent text-accent-ink" : "border border-line-strong text-ink-3"}`} aria-hidden="true">{ok ? <Check size={11} strokeWidth={3}/> : <Minus size={11}/>}</span>
    <span><span className={ok ? "text-ink" : "text-ink-2"}>{CHECK_LABELS[key] ?? key}</span> <span className="sr-only">{ok ? "met" : "not met"}</span>
      {rubric && <span className="block text-xs text-ink-3">{rubric.find(r => r.check === key)?.rule}</span>}</span></li>)}</ul>;
}

function Dots({ points }: { points: number }) {
  return <span className="inline-flex items-center gap-1.5" title={`${points} of 4 evidence checks met`}>
    <span className="inline-flex gap-0.5" aria-hidden="true">{[0, 1, 2, 3].map(i => <span key={i} className={`h-1.5 w-3 rounded-[1px] ${i < points ? "bg-accent" : "bg-line-strong"}`}/>)}</span>
    <span className="num">{points}/4 checks</span></span>;
}

function Row({ o, onOpen }: { o: OpportunitySummary; onOpen: () => void }) {
  return <li>
    <button type="button" onClick={onOpen} className="group grid w-full gap-x-6 gap-y-3 px-4 py-4 text-left transition-colors duration-fast hover:bg-sunken/60 sm:px-5 md:grid-cols-[minmax(0,1fr)_auto]">
      <span className="min-w-0">
        <q className="voice block text-[1.0625rem] leading-7 group-hover:text-accent">{o.problem}</q>
        <Meta className="mt-1.5" items={[<Id key="id">{o.id}</Id>, Object.keys(o.areas)[0], <TrendMark key="t" trend={o.trend.label} recent={o.trend.recent_90_days} prior={o.trend.prior_90_days}/>,
          Object.keys(o.segments).slice(0, 2).join(", "), <Dots key="d" points={o.confidence.points}/>,
          o.product_context.length > 0 && <span key="doc" className="inline-flex items-center gap-1"><FileText size={12} aria-hidden="true"/>{o.product_context.map(d => d.id).join(", ")}</span>]}/>
      </span>
      <span className="flex items-center gap-5 md:justify-end">
        <dl className="num grid grid-cols-3 gap-5 text-right">
          <div><dt className="text-2xs text-ink-3">Records</dt><dd className="text-base font-medium leading-6 text-ink">{o.frequency.records}{o.frequency.also_mentioned_in ? <span className="text-xs font-normal text-ink-3"> +{o.frequency.also_mentioned_in}</span> : null}</dd></div>
          <div><dt className="text-2xs text-ink-3">Tickets</dt><dd className="text-base font-medium leading-6 text-ink">{o.evidence.linked_tickets}</dd></div>
          <div><dt className="text-2xs text-ink-3">Negative</dt><dd className="text-base font-medium leading-6 text-ink">{pct(o.severity_proxy.negative_share)}</dd></div>
        </dl>
        <ChevronRight size={16} className="hidden text-ink-3 transition-transform duration-fast group-hover:translate-x-0.5 md:block" aria-hidden="true"/>
      </span>
    </button>
  </li>;
}

function Block({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return <section className={className}><h3 className="eyebrow mb-2">{title}</h3>{children}</section>;
}

export default function Opportunities() {
  const [data, setData] = useState<OpportunityList | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [sort, setSort] = useState<keyof typeof SORTS>("evidence");
  const [area, setArea] = useState("");
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<OpportunityDetail | null>(null);
  const [opening, setOpening] = useState<OpportunitySummary | null>(null);
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  const close = useCallback(() => { setDetail(null); setOpening(null); }, []);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<OpportunityList>("/api/opportunities", controller.signal).then(r => { setData(r); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {  // deep link from Priorities and Experiments: /opportunities?open=OPP-C01
    const id = new URLSearchParams(window.location.search).get("open");
    if (data && id) open(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (data?.opportunities ?? [])
      .filter(o => !area || Object.keys(o.areas)[0] === area)
      .filter(o => !needle || `${o.title} ${o.problem}`.toLowerCase().includes(needle))
      .sort((a, b) => SORTS[sort].key(b) - SORTS[sort].key(a) || a.id.localeCompare(b.id));
  }, [data, area, filter, sort]);

  const open = async (id: string) => {
    setOpening(data?.opportunities.find(o => o.id === id) ?? null);
    try { setDetail(await apiGet<OpportunityDetail>(`/api/opportunities/${encodeURIComponent(id)}`)); }
    catch (e) { setOpening(null); setError(e instanceof Error ? e.message : "Could not load the opportunity."); }
  };
  const linked = data ? data.total_tickets - data.unlinked_tickets : 0;

  return <>
    <PageHeader title="Opportunities" lede="Each recurring problem, turned into evidence you can discuss: who is affected, how often, what support saw, and what is still unknown."
      actions={<Link href="/priorities" className={buttonClass("secondary", "md")}>Prioritize<ArrowRight size={15}/></Link>}/>

    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !data ? <Loading label="Building opportunities…" rows={8}/> : <>
      <Notice className="mb-6" title="Evidence summaries, not recommendations">
        {data.interpretation} <span className="num">{data.opportunities.length}</span> opportunities · <span className="num">{linked}</span> of <span className="num">{data.total_tickets}</span> support tickets linked · <span className="num">{data.excluded_needs_triage.length}</span> vague groups left in <Link href="/issues" className="link">Issues → Needs triage</Link>.
      </Notice>

      <div className="mb-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_11rem_13rem]">
        <SearchField value={filter} onChange={setFilter} label="Filter opportunities" placeholder="Filter by words"/>
        <Select aria-label="Product area" value={area} onChange={e => setArea(e.target.value)}><option value="">All areas</option>{areas.map(a => <option key={a}>{a}</option>)}</Select>
        <Select aria-label="Sort by" value={sort} onChange={e => setSort(e.target.value as keyof typeof SORTS)}>{Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>Sort: {v.label}</option>)}</Select>
      </div>
      <p className="mb-4 text-xs text-ink-3"><span className="num">{visible.length}</span> shown. Sorting arranges the evidence; it isn’t a priority order — <Link href="/priorities" className="link">Priorities</Link> scores them.</p>

      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        {visible.length === 0 ? <p className="px-5 py-14 text-center text-sm text-ink-2">No opportunities match these filters.</p> :
          <ul className="divide-y divide-line">{visible.map(o => <Row key={o.id} o={o} onOpen={() => open(o.id)}/>)}</ul>}
      </div>
    </>}

    <Dialog open={Boolean(detail || opening)} onClose={close} size="lg"
      kicker={(detail ?? opening) && <><Id>{(detail ?? opening)!.id}</Id> · {Object.keys((detail ?? opening)!.areas).join(", ")}{detail && <> · from sub-theme <Id>{detail.sub_theme_id}</Id></>}</>}
      title={<q className="voice">{(detail ?? opening)?.problem}</q>}
      footer={detail && <div className="flex flex-wrap gap-2">
        <Link href="/priorities" className={buttonClass("primary", "sm")}>Score in Priorities<ArrowRight size={14}/></Link>
        <Link href="/experiments" className={buttonClass("secondary", "sm")}>Experiment ideas</Link></div>}>
      {!detail ? <Loading label="Loading evidence…" rows={6}/> : <div className="space-y-8">
        <p className="-mt-2 text-xs text-ink-3">Group terms: {detail.title}</p>
        <div className="grid gap-6 border-y border-line py-5 sm:grid-cols-3 sm:divide-x sm:divide-line [&>*]:sm:pl-6 [&>*:first-child]:sm:pl-0">
          <Block title="Frequency"><p className="num font-serif text-[1.75rem] leading-8">{detail.frequency.records}</p>
            <p className="mt-1 text-xs text-ink-2">records mainly about this ({pct(detail.frequency.share_of_feedback)} of feedback) · {detail.evidence.distinct_wordings} distinct wordings{detail.evidence.also_mentioned_in ? ` · ${detail.evidence.also_mentioned_in} more also mention it` : ""}</p></Block>
          <Block title="Severity proxy"><p className="num font-serif text-[1.75rem] leading-8">{pct(detail.severity_proxy.negative_share)} <span className="font-sans text-xs text-ink-3">negative</span></p>
            <p className="mt-1 text-xs text-ink-2">Tickets: {Object.entries(detail.severity_proxy.tickets_by_severity).map(([k, v]) => `${v} ${k}`).join(", ") || "none linked"}</p>
            <p className="mt-1 text-2xs text-ink-3">{detail.severity_proxy.note}</p></Block>
          <Block title="Over time"><div className="mb-2"><TrendMark trend={detail.trend.label} recent={detail.trend.recent_90_days} prior={detail.trend.prior_90_days}/></div>
            <MonthBars months={detail.trend.months} counts={detail.trend.monthly_counts}/></Block>
        </div>

        <div className="grid gap-8 sm:grid-cols-2">
          <Block title="Who is affected"><ul className="divide-y divide-line text-sm">{Object.entries(detail.segments).map(([k, v]) => <li key={k} className="flex justify-between py-1.5"><span className="text-ink-2">{k}</span><span className="num font-medium">{v}</span></li>)}</ul></Block>
          <Block title="Evidence checklist"><p className="mb-3 text-xs text-ink-3">A transparent checklist, not a validated confidence score.</p><Checklist checks={detail.confidence.checks} rubric={detail.confidence_rubric}/></Block>
        </div>

        <Block title="Customers in their own words">
          <ul className="space-y-3">{detail.quotes.map(q => <li key={q.id}><blockquote className="voice border-l-2 border-line-strong pl-4 text-[0.975rem] leading-6">{q.text}</blockquote><Id className="ml-4">{q.id}</Id></li>)}</ul>
        </Block>

        <Block title="Product context">
          {detail.product_context.length === 0 ? <p className="text-sm text-ink-2">No product document closely matches this problem.</p> :
            <ul className="divide-y divide-line text-sm">{detail.product_context.map(d => <li key={d.id} className="py-2.5">
              <p className="text-ink">{d.title}</p><Meta className="mt-0.5" items={[d.kind.replace("_", " "), d.published, <Id key="id">{d.id}</Id>]}/>
              {d.kind === "release_note" && <p className="mt-1 text-xs text-ink-2">{d.records_before} records before this release, {d.records_after} on or after it. Timing only, not cause.</p>}</li>)}</ul>}
        </Block>

        <div className="grid gap-8 sm:grid-cols-2">
          <Block title="Assumptions"><ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-2 marker:text-ink-3">{detail.assumptions.map(a => <li key={a}>{a}</li>)}</ul></Block>
          <Block title="Unknowns"><ul className="list-disc space-y-1.5 pl-4 text-sm text-ink-2 marker:text-ink-3">{detail.unknowns.map(u => <li key={u}>{u}</li>)}</ul></Block>
        </div>

        <details className="group border-t border-line pt-4" open>
          <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden"><ChevronRight size={14} className="text-ink-3 transition-transform group-open:rotate-90"/>Linked support tickets <span className="num text-ink-3">({detail.evidence.linked_tickets.length})</span></summary>
          {detail.evidence.linked_tickets.length === 0 ? <p className="mt-2 text-sm text-ink-2">No ticket was similar enough to link.</p> :
            <ul className="mt-1 divide-y divide-line text-sm">{detail.evidence.linked_tickets.map(t => <li key={t.id} className="py-2.5">
              <p className="text-ink">{t.subject}</p>
              <Meta className="mt-0.5" items={[<Id key="id">{t.id}</Id>, <Status key="s" tone={severityTone(t.severity)}>{t.severity}</Status>, t.status, <span key="sim" className="num">similarity {t.similarity.toFixed(2)}</span>]}/></li>)}</ul>}
          <Link href="/tickets" className="link mt-2 inline-block text-xs">Open all support tickets</Link>
        </details>
        <details className="group border-t border-line pt-4">
          <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden"><ChevronRight size={14} className="text-ink-3 transition-transform group-open:rotate-90"/>All supporting feedback <span className="num text-ink-3">({detail.evidence.feedback.length})</span></summary>
          <ul className="mt-1 divide-y divide-line">{detail.evidence.feedback.map(f => <li key={f.id} className="py-2.5"><p className="voice text-[0.975rem] leading-6">{f.text}</p><Link href={`/evidence?q=${encodeURIComponent(f.id)}`} className="hover:underline" aria-label={`${f.id}: see where this record is used`}><Id>{f.id}</Id></Link></li>)}</ul>
        </details>
      </div>}
    </Dialog>
  </>;
}
