"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, X } from "lucide-react";
import { apiGet, Page, query, Ticket } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";

const KEYS = ["severity", "status", "category", "segment", "product_area", "from_date", "to_date"] as const;
const LABELS: Record<string, string> = { severity: "Severity", status: "Status", category: "Category", segment: "Segment", product_area: "Area", from_date: "From", to_date: "To" };
const day = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }); // UTC, matching how analytics count dates

export default function SupportTickets() {
  const [filters, setFilters] = useState<Record<string, string> | null>(null);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<Ticket> | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(n => n + 1), []);

  useEffect(() => {
    const url = new URLSearchParams(window.location.search);
    const found: Record<string, string> = {};
    for (const key of KEYS) { const value = url.get(key); if (value) found[key] = value; }
    setFilters(found);
  }, []);

  useEffect(() => {
    if (!filters) return;
    const controller = new AbortController();
    apiGet<Page<Ticket>>(`/api/tickets${query({ ...filters, page, page_size: 15 })}`, controller.signal)
      .then(result => { setData(result); setError(""); }).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [filters, page, attempt]);

  const remove = (key: string) => { const next = { ...filters }; delete next[key]; setFilters(next); setPage(1); setData(null); };

  return <>
    <div className="mb-8"><p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-brand">Customer voice / Pulse</p>
      <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Support Tickets</h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">The synthetic support conversations behind the ticket figures on the Overview.</p></div>
    <section aria-label="Support tickets" className="overflow-hidden rounded-2xl border border-line bg-white shadow-panel">
      <div className="border-b border-line p-5 sm:p-6">
        <h2 className="text-lg font-bold">Tickets</h2><p className="mt-1 text-sm text-muted">{data ? `${data.total} matching tickets` : "Loading…"}</p>
        {filters && Object.keys(filters).length > 0 && <div className="mt-4 flex flex-wrap items-center gap-2" aria-label="Active filters">
          {Object.entries(filters).map(([key, value]) => <button key={key} type="button" onClick={() => remove(key)} aria-label={`Remove filter ${LABELS[key]}: ${value}`}
            className="inline-flex items-center gap-1.5 rounded-full bg-pale px-3 py-1 text-xs font-semibold text-brand hover:bg-teal-100">{LABELS[key]}: {value}<X size={12}/></button>)}
          <button type="button" onClick={() => { setFilters({}); setPage(1); setData(null); }} className="text-xs font-semibold text-muted hover:text-ink">Clear all</button>
        </div>}
      </div>
      {error ? <div className="p-5"><ErrorState message={error} retry={() => { setError(""); reload(); }}/></div> : !data ? <div className="p-5"><Loading/></div>
        : data.items.length === 0 ? <div className="p-14 text-center"><h3 className="font-bold">No matching tickets</h3><p className="mt-1 text-sm text-muted">Remove a filter to widen the results.</p></div> : <>
        <ul className="divide-y divide-line">{data.items.map(t => <li key={t.id} className="px-5 py-4 sm:px-6">
          <details>
            <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-3">
              <span><span className="font-semibold">{t.subject}</span><span className="ml-2 text-xs text-muted">{t.id}</span></span>
              <span className="flex flex-wrap gap-2 text-xs"><span className="rounded-full bg-canvas px-2.5 py-1">{t.severity}</span><span className="rounded-full bg-canvas px-2.5 py-1">{t.status}</span>
                <span className="rounded-full bg-canvas px-2.5 py-1">{t.customer_segment}</span><span className="rounded-full bg-canvas px-2.5 py-1">{t.product_area}</span><span className="text-muted">{day(t.timestamp)}</span></span>
            </summary>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink">{t.description}</p>
            <p className="mt-2 text-xs text-muted">{t.issue_category} · {t.related_feature}</p>
          </details>
        </li>)}</ul>
        <div className="flex items-center justify-between border-t border-line px-5 py-4 text-sm sm:px-6"><span className="text-muted">Page {data.page} of {data.pages} · {data.total} tickets</span>
          <div className="flex gap-2"><button disabled={page <= 1} onClick={() => setPage(p => p - 1)} aria-label="Previous page" className="rounded-lg border border-line p-2 disabled:opacity-40"><ArrowLeft size={16}/></button>
            <button disabled={page >= data.pages} onClick={() => setPage(p => p + 1)} aria-label="Next page" className="rounded-lg border border-line p-2 disabled:opacity-40"><ArrowRight size={16}/></button></div></div>
      </>}
    </section>
  </>;
}
