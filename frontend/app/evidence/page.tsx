"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { apiGet, areas, EvidenceItem, EvidencePage, query, segments, SourceDetail } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { Button, EmptyState, Field, Id, Meta, Notice, PageHeader, Pagination, Panel, SearchField, Select, Status } from "@/components/ui";

const KINDS: Record<string, string> = { feedback: "Feedback", support_ticket: "Support ticket", prd: "PRD", release_note: "Release note" };
const ROLE: Record<string, string> = {
  opportunity_evidence: "main evidence", secondary_mention: "also mentioned", linked_ticket: "linked ticket", product_context: "product context",
};
const tone = (status: string) => ["opportunity_evidence", "linked_ticket", "product_context"].includes(status) ? "accent" as const
  : status === "needs_triage" ? "caution" as const : "neutral" as const;
const PAGE_SIZE = 20;
type Filters = { q: string; kind: string; product_area: string; segment: string; status: string };
const EMPTY: Filters = { q: "", kind: "", product_area: "", segment: "", status: "" };

function SourceText({ id }: { id: string }) {
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    apiGet<SourceDetail>(`/api/sources/${encodeURIComponent(id)}`, controller.signal).then(setSource)
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [id]);
  if (error) return <p className="text-sm text-signal">{error}</p>;
  if (!source) return <Loading label="Loading the original text…" rows={2}/>;
  return <p className="voice max-w-prose whitespace-pre-wrap text-[0.975rem] leading-7">{source.content}</p>;
}

function Row({ item }: { item: EvidenceItem }) {
  const [open, setOpen] = useState(false);
  const opportunities = Array.from(new Set(item.used_in.map(u => u.opportunity_id)));
  return <li>
    <details className="group" onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3.5 transition-colors duration-fast hover:bg-sunken/60 sm:px-5 [&::-webkit-details-marker]:hidden">
        <ChevronDown size={16} className="mt-1 shrink-0 text-ink-3 transition-transform duration-fast group-open:rotate-180" aria-hidden="true"/>
        <span className="min-w-0 flex-1">
          <span className={item.kind === "feedback" ? "voice block text-[0.975rem] leading-6 text-ink" : "block text-sm font-medium text-ink"}>
            {item.kind === "feedback" ? item.snippet : item.title}</span>
          <Meta className="mt-1" items={[<Status key="s" tone={tone(item.status)}>{item.status_label}</Status>, KINDS[item.kind], item.segment, item.product_area, item.date]}/>
        </span>
        <Id className="mt-0.5 hidden sm:block">{item.id}</Id>
      </summary>
      <div className="space-y-4 px-4 pb-5 pl-11 sm:px-5 sm:pl-12">
        {open && <SourceText id={item.id}/>}
        <div>
          <p className="text-xs font-semibold text-ink-2">Where Gist uses this</p>
          {opportunities.length === 0 ? <p className="mt-1 text-xs text-ink-3">{item.status_label}. It supports no opportunity.</p> :
            <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">{opportunities.map(o => <li key={o}>
              <Link href={`/opportunities?open=${encodeURIComponent(o)}`} className="font-medium text-accent hover:underline">{o}</Link>
              <span className="text-ink-3"> · {Array.from(new Set(item.used_in.filter(u => u.opportunity_id === o).map(u => ROLE[u.role] ?? u.role))).join(", ")}</span></li>)}</ul>}
        </div>
        <Id className="sm:hidden">{item.id}</Id>
      </div>
    </details>
  </li>;
}

export default function EvidenceExplorer() {
  const [filters, setFilters] = useState<Filters | null>(null);
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<EvidencePage | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(n => n + 1), []);

  useEffect(() => {  // deep links: /evidence?q=V2-FB-0012 or ?status=needs_triage
    const url = new URLSearchParams(window.location.search);
    const found = { ...EMPTY };
    (Object.keys(EMPTY) as (keyof Filters)[]).forEach(k => { found[k] = url.get(k) ?? ""; });
    setFilters(found);
    setText(found.q);
  }, []);

  useEffect(() => {  // debounce typing into the search filter
    if (!filters || text === filters.q) return;
    const timer = setTimeout(() => { setFilters(f => f && { ...f, q: text }); setPage(1); }, 300);
    return () => clearTimeout(timer);
  }, [text, filters]);

  useEffect(() => {
    if (!filters) return;
    const controller = new AbortController();
    apiGet<EvidencePage>(`/api/evidence${query({ ...filters, page, page_size: PAGE_SIZE })}`, controller.signal)
      .then(r => { setData(r); setError(""); }).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [filters, page, attempt]);

  const set = (key: keyof Filters, value: string) => { setFilters(f => f && { ...f, [key]: value }); setPage(1); };
  const clear = () => { setFilters(EMPTY); setText(""); setPage(1); };
  const active = filters ? Object.values(filters).some(Boolean) : false;
  const counts = data?.status_counts ?? {};

  return <>
    <PageHeader title="Evidence explorer" lede="Search every source Gist has indexed (feedback, support tickets, PRDs and release notes) and see where each one is used."/>

    <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_1.4fr]">
      <SearchField value={text} onChange={setText} label="Search sources" placeholder="Words or a record ID"/>
      <Field label="Kind" htmlFor="ev-kind"><Select id="ev-kind" value={filters?.kind ?? ""} onChange={e => set("kind", e.target.value)}>
        <option value="">All kinds</option>{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
      <Field label="Area" htmlFor="ev-area"><Select id="ev-area" value={filters?.product_area ?? ""} onChange={e => set("product_area", e.target.value)}>
        <option value="">All areas</option>{areas.map(a => <option key={a}>{a}</option>)}</Select></Field>
      <Field label="Segment" htmlFor="ev-seg"><Select id="ev-seg" value={filters?.segment ?? ""} onChange={e => set("segment", e.target.value)}>
        <option value="">All segments</option>{segments.map(s => <option key={s}>{s}</option>)}</Select></Field>
      <Field label="How it's used" htmlFor="ev-status"><Select id="ev-status" value={filters?.status ?? ""} onChange={e => set("status", e.target.value)}>
        <option value="">Any use</option>{data && Object.entries(data.status_labels).map(([k, v]) => <option key={k} value={k}>{v}{counts[k] !== undefined ? ` (${counts[k]})` : ""}</option>)}</Select></Field>
    </div>

    {data && <Notice className="mb-5">{data.note} Feedback in vague groups or not grouped at all is still searchable here, so nothing is hidden by the grouping.</Notice>}

    <Panel as="section" aria-label="Sources" className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-line bg-sunken/50 px-4 py-2 text-xs text-ink-3 sm:px-5">
        <p aria-live="polite">{data ? `${data.total} ${active ? "matching " : ""}source${data.total === 1 ? "" : "s"}` : "Loading sources…"}</p>
        {active && <Button size="sm" variant="ghost" onClick={clear}>Clear all</Button>}
      </div>
      {error ? <div className="p-5"><ErrorState message={error} retry={() => { setError(""); reload(); }}/></div>
        : !data ? <div className="p-5"><Loading label="Loading sources…" rows={8}/></div>
        : data.items.length === 0 ? <EmptyState title="No sources match" action={active && <Button onClick={clear}>Clear all filters</Button>}>
            Try fewer words, or remove a filter to widen the results.</EmptyState>
        : <>
          <ul className="divide-y divide-line">{data.items.map(item => <Row key={item.id} item={item}/>)}</ul>
          <Pagination page={data.page} pages={Math.ceil(data.total / data.page_size)} total={data.total} noun="sources"
            onPage={p => { setPage(p); document.getElementById("main")?.scrollIntoView({ block: "start" }); }}/>
        </>}
    </Panel>
  </>;
}
