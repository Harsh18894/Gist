"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Search, X } from "lucide-react";
import { apiGet, Category, Feedback, Page, Segment } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";

const categories: Category[] = ["Verification friction", "Integration failures", "Notification overload", "Slow performance", "Billing confusion", "Feature discoverability", "Account access", "Import mapping", "Alert delivery", "Template permissions", "Multiple issues", "Unclear"];
const segments: Segment[] = ["Individual", "SMB", "Mid-market", "Enterprise"];
const date = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

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
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), page_size: "15" });
    if (category) params.set("category", category);
    if (segment) params.set("segment", segment);
    if (query) params.set("query", query);
    apiGet<Page<Feedback>>(`/api/records?${params}`, controller.signal).then(result => { setData(result); setError(""); }).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [category, segment, query, page, attempt]);
  const filterCategory = (value: string) => { setCategory(value); setPage(1); setData(null); };
  const filterSegment = (value: string) => { setSegment(value); setPage(1); setData(null); };
  const submitSearch = (event: React.FormEvent) => { event.preventDefault(); setQuery(search.trim()); setPage(1); setData(null); };
  const openRecord = async (id: string) => {
    try { setSelected(await apiGet<Feedback>(`/api/records/${encodeURIComponent(id)}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load record."); }
  };
  return <>
    <div className="mb-8"><p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-brand">Customer voice / Pulse</p><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Feedback Explorer</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-muted">Inspect the original synthetic feedback behind each theme. Search text, filter the evidence, and open a record for details.</p></div>
    <section className="overflow-hidden rounded-2xl border border-line bg-white shadow-panel" aria-label="Feedback records">
      <div className="border-b border-line p-5 sm:p-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-bold">All feedback</h2><p className="mt-1 text-sm text-muted">{data ? `${data.total} matching records` : "Loading records…"}</p></div><span className="rounded-full bg-pale px-3 py-1.5 text-xs font-semibold text-brand">Synthetic dataset</span></div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_210px_190px]"><form onSubmit={submitSearch} className="relative"><Search size={17} className="absolute left-3 top-3 text-muted"/><input aria-label="Search feedback" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search feedback or feature…" className="h-11 w-full rounded-lg border border-line bg-white pl-10 pr-20 text-sm outline-none focus:border-brand"/><button type="submit" className="absolute right-1.5 top-1.5 rounded-md bg-ink px-3 py-1.5 text-xs font-semibold text-white">Search</button></form>
          <select aria-label="Filter by issue category" value={category} onChange={e => filterCategory(e.target.value)} className="h-11 rounded-lg border border-line bg-white px-3 text-sm"><option value="">All categories</option>{categories.map(x => <option key={x}>{x}</option>)}</select>
          <select aria-label="Filter by customer segment" value={segment} onChange={e => filterSegment(e.target.value)} className="h-11 rounded-lg border border-line bg-white px-3 text-sm"><option value="">All segments</option>{segments.map(x => <option key={x}>{x}</option>)}</select></div>
      </div>
      {error ? <div className="p-5"><ErrorState message={error} retry={() => { setError(""); reload(); }}/></div> : !data ? <div className="p-5"><Loading/></div> : data.items.length === 0 ? <div className="p-14 text-center"><h3 className="font-bold">No matching feedback</h3><p className="mt-2 text-sm text-muted">Try a broader search or remove a filter.</p><button className="mt-4 text-sm font-semibold text-brand hover:underline" onClick={() => { setCategory(""); setSegment(""); setSearch(""); setQuery(""); setPage(1); }}>Clear filters</button></div> : <>
        <div className="overflow-x-auto"><table className="w-full min-w-[790px] text-left text-sm"><thead className="bg-canvas text-xs uppercase tracking-wider text-muted"><tr><th className="px-6 py-3 font-semibold">Feedback</th><th className="px-4 py-3 font-semibold">Category</th><th className="px-4 py-3 font-semibold">Segment</th><th className="px-4 py-3 font-semibold">Sentiment</th><th className="px-6 py-3 font-semibold">Date</th></tr></thead><tbody className="divide-y divide-line">{data.items.map(record => <tr key={record.id} className="transition hover:bg-canvas/70"><td className="max-w-sm px-6 py-4"><button onClick={() => openRecord(record.id)} className="block w-full text-left focus-visible:rounded"><span className="font-semibold text-brand hover:underline">{record.id}</span><span className="mt-1 block truncate text-muted">{record.feedback_text}</span></button></td><td className="px-4 py-4 font-medium">{record.issue_category}</td><td className="px-4 py-4 text-muted">{record.customer_segment}</td><td className="px-4 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${record.sentiment === "Negative" ? "bg-rose-50 text-rose-700" : record.sentiment === "Positive" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>{record.sentiment}</span></td><td className="whitespace-nowrap px-6 py-4 text-muted">{date(record.timestamp)}</td></tr>)}</tbody></table></div>
        <div className="flex items-center justify-between border-t border-line px-5 py-4 text-sm sm:px-6"><span className="text-muted">Page {data.page} of {data.pages} · {data.total} records</span><div className="flex gap-2"><button disabled={page <= 1} onClick={() => { setPage(page - 1); setData(null); }} aria-label="Previous page" className="rounded-lg border border-line p-2 disabled:opacity-40"><ArrowLeft size={16}/></button><button disabled={page >= data.pages} onClick={() => { setPage(page + 1); setData(null); }} aria-label="Next page" className="rounded-lg border border-line p-2 disabled:opacity-40"><ArrowRight size={16}/></button></div></div>
      </>}
    </section>
    {selected && <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/45 p-4" onMouseDown={e => { if (e.target === e.currentTarget) setSelected(null); }}><section role="dialog" aria-modal="true" aria-labelledby="record-title" className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl sm:p-8"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wider text-brand">Feedback record</p><h2 id="record-title" className="mt-1 text-2xl font-bold">{selected.id}</h2></div><button onClick={() => setSelected(null)} aria-label="Close record" className="rounded-lg p-2 text-muted hover:bg-canvas"><X size={20}/></button></div><p className="mt-6 rounded-xl bg-canvas p-5 text-base leading-7">“{selected.feedback_text}”</p><dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-5 text-sm">{[["Date", date(selected.timestamp)], ["Segment", selected.customer_segment], ["Tier", selected.subscription_tier], ["Product area", selected.product_area], ["Category", selected.issue_category], ["Feature", selected.related_feature], ["Channel", selected.feedback_channel], ["Sentiment", selected.sentiment]].map(([label, value]) => <div key={label}><dt className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</dt><dd className="mt-1 font-medium">{value}</dd></div>)}</dl><p className="mt-7 border-t border-line pt-4 text-xs text-muted">Synthetic Pulse data · source identifier {selected.id}</p></section></div>}
  </>;
}
