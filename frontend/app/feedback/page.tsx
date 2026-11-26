"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, Category, Feedback, Page, Segment } from "@/lib/api";
import { Dialog } from "@/components/dialog";
import { ErrorState, Loading } from "@/components/states";
import { Button, EmptyState, FilterChip, Id, Meta, PageHeader, Pagination, Panel, SearchField, Select, sentimentTone, Status } from "@/components/ui";

const categories: Category[] = ["Verification friction", "Integration failures", "Notification overload", "Slow performance", "Billing confusion", "Feature discoverability", "Account access", "Import mapping", "Alert delivery", "Template permissions", "Multiple issues", "Unclear"];
const segments: Segment[] = ["Individual", "SMB", "Mid-market", "Enterprise"];
const EXTRA_KEYS = ["product_area", "sentiment", "feature", "channel", "from_date", "to_date"] as const;
const EXTRA_LABELS: Record<string, string> = { product_area: "Area", sentiment: "Sentiment", feature: "Feature", channel: "Channel", from_date: "From", to_date: "To" };
const date = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }); // UTC, matching how analytics count dates
const COLS = "lg:grid lg:grid-cols-[minmax(0,1fr)_10rem_7rem_6.5rem_6.5rem] lg:gap-x-5";

export default function FeedbackExplorer() {
  const [category, setCategory] = useState("");
  const [segment, setSegment] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<Feedback> | null>(null);
  const [selected, setSelected] = useState<Feedback | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  // Drill-down filters arrive in the URL from the analytics overview (area, sentiment, feature, channel, dates).
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [ready, setReady] = useState(false);
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  useEffect(() => {
    const url = new URLSearchParams(window.location.search);
    setCategory(url.get("category") ?? ""); setSegment(url.get("segment") ?? "");
    const q = url.get("query") ?? ""; setQuery(q); setSearch(q);
    const found: Record<string, string> = {};
    for (const key of EXTRA_KEYS) { const value = url.get(key); if (value) found[key] = value; }
    setExtra(found); setReady(true);
  }, []);
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), page_size: "15", ...extra });
    if (category) params.set("category", category);
    if (segment) params.set("segment", segment);
    if (query) params.set("query", query);
    apiGet<Page<Feedback>>(`/api/records?${params}`, controller.signal).then(result => { setData(result); setError(""); }).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [category, segment, query, page, attempt, extra, ready]);
  const refresh = () => { setPage(1); setData(null); };
  const filterCategory = (value: string) => { setCategory(value); refresh(); };
  const filterSegment = (value: string) => { setSegment(value); refresh(); };
  const submitSearch = (event: React.FormEvent) => { event.preventDefault(); setQuery(search.trim()); refresh(); };
  const changeSearch = (value: string) => { setSearch(value); if (!value && query) { setQuery(""); refresh(); } };
  const clearAll = () => { setCategory(""); setSegment(""); setSearch(""); setQuery(""); setExtra({}); refresh(); };
  const goPage = (p: number) => { setPage(p); setData(null); document.getElementById("main")?.scrollIntoView({ block: "start" }); };
  const openRecord = async (id: string) => {
    try { setSelected(await apiGet<Feedback>(`/api/records/${encodeURIComponent(id)}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load record."); }
  };
  const anyFilter = Boolean(category || segment || query || Object.keys(extra).length);

  return <>
    <PageHeader title="Feedback" lede="Every customer record behind the numbers. Search the text, narrow by category or segment, and open a record for its full context."/>

    <div className="mb-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_10rem]">
      <form onSubmit={submitSearch} role="search" className="flex gap-2">
        <SearchField value={search} onChange={changeSearch} label="Search feedback" placeholder="Search text or feature, then press Enter" className="flex-1"/>
        <Button type="submit" className="sm:hidden">Search</Button>
      </form>
      <Select aria-label="Filter by issue category" value={category} onChange={e => filterCategory(e.target.value)}><option value="">All categories</option>{categories.map(x => <option key={x}>{x}</option>)}</Select>
      <Select aria-label="Filter by customer segment" value={segment} onChange={e => filterSegment(e.target.value)}><option value="">All segments</option>{segments.map(x => <option key={x}>{x}</option>)}</Select>
    </div>
    {(Object.keys(extra).length > 0 || query) && <div className="mb-4 flex flex-wrap items-center gap-2" aria-label="Active filters">
      {query && <FilterChip label="Text" value={query} onRemove={() => { setSearch(""); setQuery(""); refresh(); }}/>}
      {Object.entries(extra).map(([key, value]) => <FilterChip key={key} label={EXTRA_LABELS[key]} value={value === "" ? "(blank)" : value}
        onRemove={() => { const next = { ...extra }; delete next[key]; setExtra(next); refresh(); }}/>)}
      <Button size="sm" variant="ghost" onClick={clearAll}>Clear all</Button>
    </div>}

    <Panel as="section" aria-label="Feedback records" className="overflow-hidden">
      <div className={`hidden border-b border-line bg-sunken/50 px-5 py-2.5 text-xs font-medium text-ink-3 ${COLS}`} aria-hidden="true">
        <span>Feedback <span className="num font-normal">{data ? `· ${data.total}` : ""}</span></span><span>Category</span><span>Segment</span><span>Sentiment</span><span className="text-right">Date</span>
      </div>
      <p className="border-b border-line px-4 py-2.5 text-xs text-ink-3 lg:hidden" aria-live="polite">{data ? `${data.total} matching records` : "Loading records…"}</p>
      {error ? <div className="p-5"><ErrorState message={error} retry={() => { setError(""); reload(); }}/></div>
        : !data ? <div className="p-5"><Loading label="Loading records…" rows={8}/></div>
        : data.items.length === 0 ? <EmptyState title="No feedback matches" action={anyFilter && <Button onClick={clearAll}>Clear all filters</Button>}>
            {anyFilter ? "Nothing fits every filter at once. Remove one to widen the results." : "There are no feedback records in this dataset yet."}</EmptyState>
        : <>
          <ul className="divide-y divide-line">{data.items.map(record => <li key={record.id}>
            <button type="button" onClick={() => { setSelected(record); openRecord(record.id); }} className={`block w-full px-4 py-3.5 text-left transition-colors duration-fast hover:bg-sunken/60 sm:px-5 ${COLS} lg:items-start`}>
              <span className="block min-w-0">
                <span className="voice line-clamp-2 text-[0.975rem] leading-6">{record.feedback_text}</span>
                <span className="mt-1 block lg:hidden"><Meta items={[<Status key="s" tone={sentimentTone(record.sentiment)}>{record.sentiment}</Status>, record.issue_category, record.customer_segment, date(record.timestamp)]}/></span>
                <Id className="mt-1 hidden lg:block">{record.id}</Id>
              </span>
              <span className="hidden pt-0.5 text-sm text-ink md:block">{record.issue_category}</span>
              <span className="hidden pt-0.5 text-sm text-ink-2 md:block">{record.customer_segment}</span>
              <span className="hidden pt-0.5 md:block"><Status tone={sentimentTone(record.sentiment)}>{record.sentiment}</Status></span>
              <span className="num hidden whitespace-nowrap pt-0.5 text-right text-sm text-ink-2 md:block">{date(record.timestamp)}</span>
            </button>
          </li>)}</ul>
          <Pagination page={data.page} pages={data.pages} total={data.total} noun="records" onPage={goPage}/>
        </>}
    </Panel>

    <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} kicker={selected && <>Feedback record · <Id>{selected.id}</Id></>} title={selected ? `${selected.issue_category} · ${selected.product_area}` : ""}
      footer={<p className="text-2xs text-ink-3">Synthetic Pulse data. Category and feature labels come with the record; Gist does not infer them.</p>}>
      {selected && <>
        <blockquote className="voice border-l-2 border-accent pl-4 text-lg leading-8">{selected.feedback_text}</blockquote>
        <dl className="mt-8 grid grid-cols-2 gap-x-6 gap-y-5 text-sm sm:grid-cols-3">
          {([["Date", date(selected.timestamp)], ["Sentiment", <Status key="s" tone={sentimentTone(selected.sentiment)}>{selected.sentiment}</Status>], ["Segment", selected.customer_segment], ["Tier", selected.subscription_tier], ["Product area", selected.product_area], ["Feature", selected.related_feature], ["Category", selected.issue_category], ["Channel", selected.feedback_channel]] as [string, React.ReactNode][]).map(([label, value]) =>
            <div key={label}><dt className="text-2xs text-ink-3">{label}</dt><dd className="mt-0.5 text-ink">{value}</dd></div>)}
        </dl>
      </>}
    </Dialog>
  </>;
}
