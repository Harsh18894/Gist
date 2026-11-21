"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, FileText, MessagesSquare, Smile, Users } from "lucide-react";
import { apiGet, Stats } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";

const palette = ["bg-brand", "bg-teal-400", "bg-slate-500", "bg-amber-400", "bg-sky-400", "bg-violet-400"];

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    apiGet<Stats>("/api/stats", controller.signal).then(setStats).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);
  const cards = stats ? [
    { label: "Feedback records", value: stats.feedback_count, icon: MessagesSquare, detail: "Across all customer channels" },
    { label: "Support tickets", value: stats.support_ticket_count, icon: FileText, detail: "Synthetic Pulse support dataset" },
    { label: "Negative feedback", value: stats.negative_feedback_count, icon: Smile, detail: "Records marked negative" },
    { label: "Enterprise feedback", value: stats.enterprise_feedback_count, icon: Users, detail: "Enterprise segment records" },
  ] : [];
  return <>
    <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
      <div><p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-brand">Product intelligence / Pulse</p><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Overview</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-muted">A clear view of what customers are telling you. Every number below comes from the synthetic Pulse dataset.</p></div>
      <Link href="/feedback" className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-800">Explore feedback <ArrowRight size={16}/></Link>
    </div>
    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !stats ? <Loading/> : <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{cards.map(({ label, value, icon: Icon, detail }) => <div key={label} className="rounded-2xl border border-line bg-white p-5 shadow-panel"><div className="mb-5 flex items-center justify-between"><span className="text-sm font-medium text-muted">{label}</span><span className="rounded-lg bg-canvas p-2 text-brand"><Icon size={17}/></span></div><p className="text-3xl font-bold tracking-tight tabular-nums">{value.toLocaleString()}</p><p className="mt-2 text-xs text-muted">{detail}</p></div>)}</div>
      <div className="mt-6 grid gap-6 xl:grid-cols-[1.45fr_1fr]">
        <section className="rounded-2xl border border-line bg-white p-6 shadow-panel" aria-labelledby="areas-title"><div className="mb-7 flex items-start justify-between"><div><h2 id="areas-title" className="text-lg font-bold">Feedback by product area</h2><p className="mt-1 text-sm text-muted">Where customer conversations are concentrated</p></div><span className="rounded-full bg-canvas px-3 py-1 text-xs text-muted">All time</span></div>
          <div className="space-y-5">{stats.by_product_area.map((item, i) => <div key={item.name}><div className="mb-2 flex justify-between text-sm"><span className="font-medium">{item.name}</span><span className="font-semibold tabular-nums">{item.count}</span></div><div className="h-2.5 overflow-hidden rounded-full bg-canvas"><div className={`h-full rounded-full ${palette[i % palette.length]}`} style={{ width: `${stats.feedback_count ? item.count / stats.feedback_count * 100 : 0}%` }}/></div></div>)}</div>
        </section>
        <section className="rounded-2xl border border-line bg-white p-6 shadow-panel" aria-labelledby="themes-title"><div className="mb-6"><h2 id="themes-title" className="text-lg font-bold">Recurring themes</h2><p className="mt-1 text-sm text-muted">Counts by issue category</p></div><div className="divide-y divide-line">{stats.by_category.map((item, i) => <div key={item.name} className="flex items-center justify-between py-3.5"><div className="flex items-center gap-3"><span className={`h-2.5 w-2.5 rounded-full ${palette[i % palette.length]}`}/><span className="text-sm font-medium">{item.name}</span></div><span className="rounded-md bg-canvas px-2.5 py-1 text-xs font-bold tabular-nums">{item.count}</span></div>)}</div></section>
      </div>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-teal-100 bg-pale p-6"><div><p className="text-xs font-bold uppercase tracking-wider text-brand">Next step</p><h2 className="mt-1 text-lg font-bold">Follow the evidence behind the numbers</h2><p className="mt-1 text-sm text-muted">Search individual records and filter by customer segment or issue.</p></div><Link href="/feedback" className="inline-flex items-center gap-2 text-sm font-bold text-brand hover:underline">Open Feedback Explorer <ArrowUpRight size={16}/></Link></div>
    </>}
  </>;
}
