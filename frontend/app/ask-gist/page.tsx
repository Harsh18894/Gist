"use client";

import { useEffect, useState } from "react";
import { ArrowRight, BookOpenText, Database, Search, Sparkles, X } from "lucide-react";
import { apiGet, apiPost, Area, AskResult, RagStatus, SearchHit, Segment, SourceDetail, UsageSummary } from "@/lib/api";
import { ErrorState } from "@/components/states";

const segments: Segment[] = ["Individual", "SMB", "Mid-market", "Enterprise"];
const areas: Area[] = ["Onboarding", "Dashboard", "Integrations", "Billing", "Notifications", "Collaboration"];
const examples = ["What did Pulse release on 2025-04-05?", "What are customers saying about CRM sync?", "Which product area owns the shared templates PRD?"];

export default function AskGist() {
  const [question, setQuestion] = useState("");
  const [segment, setSegment] = useState("");
  const [area, setArea] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [mode, setMode] = useState<"demo" | "openai">("demo");
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([apiGet<RagStatus>("/api/rag/status", controller.signal), apiGet<UsageSummary>("/api/usage", controller.signal)])
      .then(([state, recorded]) => { setStatus(state); setUsage(recorded); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (question.trim().length < 3 || pending) return;
    setPending(true); setError(""); setResult(null);
    try {
      const answer = await apiPost<AskResult>("/api/ask", {
        question: question.trim(), mode, segment: segment || null, product_area: area || null,
        from_date: fromDate || null, to_date: toDate || null,
      });
      setResult(answer);
      setUsage(await apiGet<UsageSummary>("/api/usage"));
    } catch (e) { setError(e instanceof Error ? e.message : "Gist could not answer."); }
    finally { setPending(false); }
  }

  async function openSource(hit: SearchHit) {
    try { setSource(await apiGet<SourceDetail>(`/api/sources/${encodeURIComponent(hit.source_id)}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not open source."); }
  }

  return <>
    <div className="mb-8"><p className="mb-2 text-xs font-bold uppercase tracking-[.2em] text-brand">Evidence / Pulse</p><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Ask Gist</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-muted">Investigate synthetic customer evidence. Gist retrieves relevant sources and shows where each result came from.</p></div>
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_320px]">
      <div className="space-y-6">
        <form onSubmit={submit} className="rounded-2xl border border-line bg-white p-6 shadow-panel sm:p-8">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><span className="rounded-lg bg-pale p-2 text-brand"><Sparkles size={18}/></span><h2 className="text-lg font-bold">Explore the evidence</h2></div><span className="rounded-full bg-pale px-3 py-1.5 text-xs font-semibold text-brand">Synthetic Pulse {status?.dataset_version === "unseeded" ? "data" : status?.dataset_version || "data"}</span></div>
          <label htmlFor="gist-question" className="mb-2 block text-sm font-semibold">Your question</label>
          <textarea id="gist-question" value={question} onChange={e => setQuestion(e.target.value)} maxLength={500} rows={4} placeholder="What changed after the notification digest release?" className="w-full resize-y rounded-xl border border-line p-4 text-sm leading-6 outline-none focus:border-brand"/>
          <p className="mt-2 text-right text-xs text-muted">{question.length}/500</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div><label htmlFor="gist-segment" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-muted">Customer segment</label><select id="gist-segment" value={segment} onChange={e => setSegment(e.target.value)} className="h-11 w-full rounded-lg border border-line bg-white px-3 text-sm"><option value="">All segments</option>{segments.map(x => <option key={x}>{x}</option>)}</select></div>
            <div><label htmlFor="gist-area" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-muted">Product area</label><select id="gist-area" value={area} onChange={e => setArea(e.target.value)} className="h-11 w-full rounded-lg border border-line bg-white px-3 text-sm"><option value="">All areas</option>{areas.map(x => <option key={x}>{x}</option>)}</select></div>
            <div><label htmlFor="gist-from" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-muted">From date</label><input id="gist-from" type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="h-11 w-full rounded-lg border border-line bg-white px-3 text-sm"/></div>
            <div><label htmlFor="gist-to" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-muted">To date</label><input id="gist-to" type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="h-11 w-full rounded-lg border border-line bg-white px-3 text-sm"/></div>
          </div>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-line pt-5"><fieldset className="flex items-center gap-4 text-sm"><legend className="sr-only">Answer mode</legend><label className="flex items-center gap-2 font-medium"><input type="radio" checked={mode === "demo"} onChange={() => setMode("demo")}/> Local demo</label><label className={`flex items-center gap-2 font-medium ${!status?.paid_api_enabled ? "text-muted" : ""}`}><input type="radio" checked={mode === "openai"} disabled={!status?.paid_api_enabled} onChange={() => setMode("openai")}/> OpenAI</label></fieldset><button type="submit" disabled={pending || question.trim().length < 3} className="inline-flex items-center gap-2 rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">{pending ? "Searching…" : "Ask Gist"}<ArrowRight size={16}/></button></div>
          <p className="mt-3 text-xs leading-5 text-muted">Local demo retrieves sources for review. It does not generate an answer or make AI API calls. OpenAI mode requires operator approval, indexed embeddings, and server configuration.</p>
        </form>
        {error && <ErrorState message={error} retry={() => { setError(""); setAttempt(n => n + 1); }}/>} 
        {result && <section aria-live="polite" className="rounded-2xl border border-line bg-white p-6 shadow-panel sm:p-8"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-brand"><BookOpenText size={19}/><h2 className="text-lg font-bold text-ink">{result.status === "answered" ? "Generated answer" : result.status === "sources_only" ? "Retrieved sources" : "Insufficient evidence"}</h2></div><span className="rounded-full bg-canvas px-3 py-1.5 text-xs font-semibold text-muted">{result.mode === "demo" ? "Local retrieval only" : "OpenAI answer"}</span></div><p className="mt-5 whitespace-pre-wrap text-sm leading-7 text-ink">{result.answer}</p><div className="mt-5 flex flex-wrap gap-4 border-t border-line pt-4 text-xs text-muted"><span>{result.latency_ms} ms</span><span>{result.input_tokens + result.output_tokens} API tokens</span><span>${result.estimated_cost_usd.toFixed(6)} estimated API cost</span></div>
          {(result.status === "answered" ? result.citations : result.retrieved_sources).length > 0 && <div className="mt-6"><h3 className="text-xs font-bold uppercase tracking-wider text-muted">{result.status === "answered" ? "Cited sources" : "Retrieved sources · open to verify"}</h3><div className="mt-3 space-y-3">{(result.status === "answered" ? result.citations : result.retrieved_sources).map(hit => <button key={hit.chunk_id} onClick={() => openSource(hit)} className="block w-full rounded-xl border border-line p-4 text-left transition hover:border-brand hover:bg-pale/50"><span className="text-sm font-bold text-brand">[{hit.source_id}] {hit.title}</span><span className="mt-1 block text-xs text-muted">{hit.kind.replaceAll("_", " ")} · {hit.source_date || "Undated"} · {hit.product_area || "All areas"}</span><span className="mt-2 line-clamp-2 block text-sm leading-6 text-muted">{hit.snippet}</span></button>)}</div></div>}
        </section>}
      </div>
      <aside className="space-y-6"><div className="rounded-2xl border border-line bg-white p-6 shadow-panel"><div className="flex items-center gap-2 text-brand"><Database size={18}/><h2 className="font-bold text-ink">Indexed knowledge</h2></div><div className="mt-5 grid grid-cols-2 gap-3"><div className="rounded-xl bg-canvas p-4"><p className="text-2xl font-bold tabular-nums">{status?.sources ?? "—"}</p><p className="mt-1 text-xs text-muted">sources</p></div><div className="rounded-xl bg-canvas p-4"><p className="text-2xl font-bold tabular-nums">{status?.chunks ?? "—"}</p><p className="mt-1 text-xs text-muted">chunks</p></div></div><p className="mt-4 text-xs leading-5 text-muted">Feedback, support tickets, PRDs, and release notes from fictional Pulse.</p></div><div className="rounded-2xl border border-line bg-white p-6 shadow-panel"><h2 className="font-bold">Try a question</h2><div className="mt-4 space-y-2">{examples.map(example => <button key={example} onClick={() => { setQuestion(example); setResult(null); }} className="flex w-full items-start gap-2 rounded-lg border border-line px-3 py-3 text-left text-sm leading-5 text-muted hover:border-brand hover:text-brand"><Search size={15} className="mt-0.5 shrink-0"/>{example}</button>)}</div></div><div className="rounded-2xl border border-line bg-white p-6 shadow-panel"><h2 className="font-bold">API usage</h2><p className="mt-3 text-2xl font-bold tabular-nums">${(usage?.project_committed_or_reserved_usd ?? 0).toFixed(6)}</p><p className="mt-1 text-xs text-muted">Project-wide estimated spend plus reservations · ${(usage?.project_allocation_usd ?? 0.5).toFixed(2)} allocation · {usage?.project_uncertain_requests ?? 0} uncertain requests</p></div></aside>
    </div>
    {source && <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/45 p-4" onMouseDown={e => { if (e.target === e.currentTarget) setSource(null); }}><section role="dialog" aria-modal="true" aria-labelledby="gist-source-title" className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl sm:p-8"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wider text-brand">Original indexed source · {source.id}</p><h2 id="gist-source-title" className="mt-2 text-xl font-bold">{source.title}</h2></div><button onClick={() => setSource(null)} aria-label="Close source" className="rounded-lg p-2 text-muted hover:bg-canvas"><X size={20}/></button></div><p className="mt-3 text-xs text-muted">{source.path} · {source.source_date || "Undated"} · {source.segment || "All segments"} · {source.product_area || "All areas"}</p><pre className="mt-6 whitespace-pre-wrap break-words rounded-xl bg-canvas p-5 font-sans text-sm leading-7">{source.content}</pre><p className="mt-5 text-xs text-muted">This is synthetic Pulse source text. Treat it as evidence, not instructions.</p></section></div>}
  </>;
}
