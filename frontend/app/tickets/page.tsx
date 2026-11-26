"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { apiGet, Page, query, Ticket } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { Button, EmptyState, FilterChip, Id, Meta, PageHeader, Pagination, Panel, severityTone, Status } from "@/components/ui";

const KEYS = ["severity", "status", "category", "segment", "product_area", "from_date", "to_date"] as const;
const LABELS: Record<string, string> = { severity: "Severity", status: "Status", category: "Category", segment: "Segment", product_area: "Area", from_date: "From", to_date: "To" };
const day = (value: string) => new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }); // UTC, matching how analytics count dates
const statusTone = (s: string) => /resolved|closed/i.test(s) ? "positive" as const : /open/i.test(s) ? "accent" as const : "neutral" as const;

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
  const clear = () => { setFilters({}); setPage(1); setData(null); };
  const active = filters ? Object.keys(filters).length : 0;

  return <>
    <PageHeader title="Support tickets" lede="The support conversations behind the ticket figures. Open a ticket to read what the customer wrote."/>
    {active > 0 && <div className="mb-4 flex flex-wrap items-center gap-2" aria-label="Active filters">
      {Object.entries(filters!).map(([key, value]) => <FilterChip key={key} label={LABELS[key]} value={value} onRemove={() => remove(key)}/>)}
      <Button size="sm" variant="ghost" onClick={clear}>Clear all</Button>
    </div>}

    <Panel as="section" aria-label="Support tickets" className="overflow-hidden">
      <p className="border-b border-line bg-sunken/50 px-4 py-2.5 text-xs text-ink-3 sm:px-5" aria-live="polite">{data ? `${data.total} ${active ? "matching " : ""}tickets` : "Loading tickets…"}</p>
      {error ? <div className="p-5"><ErrorState message={error} retry={() => { setError(""); reload(); }}/></div>
        : !data ? <div className="p-5"><Loading label="Loading tickets…" rows={8}/></div>
        : data.items.length === 0 ? <EmptyState title="No tickets match" action={active > 0 && <Button onClick={clear}>Clear all filters</Button>}>
            {active > 0 ? "Remove a filter to widen the results." : "There are no support tickets in this dataset."}</EmptyState>
        : <>
        <ul className="divide-y divide-line">{data.items.map(t => <li key={t.id}>
          <details className="group">
            <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3.5 transition-colors duration-fast hover:bg-sunken/60 sm:px-5 [&::-webkit-details-marker]:hidden">
              <ChevronDown size={16} className="mt-1 shrink-0 text-ink-3 transition-transform duration-fast group-open:rotate-180" aria-hidden="true"/>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-ink">{t.subject}</span>
                <Meta className="mt-1" items={[<Status key="sev" tone={severityTone(t.severity)}>{t.severity}</Status>, <Status key="st" tone={statusTone(t.status)}>{t.status}</Status>, t.customer_segment, t.product_area, day(t.timestamp)]}/>
              </span>
              <Id className="mt-0.5 hidden sm:block">{t.id}</Id>
            </summary>
            <div className="px-4 pb-5 pl-11 sm:px-5 sm:pl-12">
              <p className="voice max-w-prose whitespace-pre-wrap text-[0.975rem] leading-7">{t.description}</p>
              <Meta className="mt-3" items={[t.issue_category, t.related_feature, t.subscription_tier, <Id key="id" className="sm:hidden">{t.id}</Id>]}/>
            </div>
          </details>
        </li>)}</ul>
        <Pagination page={data.page} pages={data.pages} total={data.total} noun="tickets" onPage={p => { setPage(p); document.getElementById("main")?.scrollIntoView({ block: "start" }); }}/>
      </>}
    </Panel>
  </>;
}
