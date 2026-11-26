"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Check, Copy, CornerDownLeft, History, PencilLine, SlidersHorizontal, Square } from "lucide-react";
import { ApiError, apiGet, apiPost, AskResult, RagStatus, SearchHit, SourceDetail, UsageSummary } from "@/lib/api";
import { Dialog } from "@/components/dialog";
import { activeCount, EMPTY_SCOPE, invalidRange, Scope, ScopeFields } from "@/components/scope";
import { ErrorState, Loading } from "@/components/states";
import { Button, cx, Id, Kbd, Meta, Notice, PageHeader, Segmented, Tag } from "@/components/ui";

const EXAMPLES = [
  "What are customers saying about CRM sync?",
  "What did Pulse release on 2025-04-05?",
  "Which product area owns the shared templates PRD?",
  "Why do enterprise admins struggle with SSO?",
];
const DRAFT_KEY = "gist-ask-draft";
const RECENT_KEY = "gist-ask-recent";
const MAX = 500;
/** Indexed chunks start with their own title ("Feedback V2-FB-0005. …"); the row already shows it. */
const snippetText = (hit: SearchHit) => hit.snippet.startsWith(`${hit.title}. `) ? hit.snippet.slice(hit.title.length + 2) : hit.snippet;
const kindLabel = (kind: string) => kind.replaceAll("_", " ").replace(/^\w/, c => c.toUpperCase());

const store = {
  get(key: string, session = false): string | null { try { return (session ? sessionStorage : localStorage).getItem(key); } catch { return null; } },
  set(key: string, value: string, session = false) { try { (session ? sessionStorage : localStorage).setItem(key, value); } catch { /* storage unavailable */ } },
};

const STATUS_COPY: Record<AskResult["status"], { title: string; body: string }> = {
  answered: { title: "Answer", body: "Written from the sources below. Each claim cites the source it came from." },
  partial: { title: "Partial answer", body: "The sources cover only part of this question. The answer says what is missing; check the cited sources before relying on it." },
  sources_only: { title: "Most relevant sources", body: "Find-sources mode ranks the indexed evidence for your question. It does not write an answer, so nothing here is generated. Open a source to read it in full." },
  insufficient_evidence: { title: "Not enough evidence", body: "Gist didn’t find sources that support an answer, so it won’t guess. Try naming a feature, area or date, or widen the filters." },
};

/** Turns "[V2-FB-0005; V2-TK-0012]" markers into numbered buttons that open the source. */
function AnswerText({ text, order, onOpen }: { text: string; order: Map<string, number>; onOpen: (id: string) => void }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return <p className="whitespace-pre-wrap text-base leading-7 text-ink">{parts.map((part, i) => {
    const match = part.match(/^\[([^\]]+)\]$/);
    const ids = match ? match[1].split(/[;,]/).map(s => s.trim()).filter(Boolean) : [];
    if (!match || !ids.length || !ids.every(id => order.has(id))) return <Fragment key={i}>{part}</Fragment>;
    return <span key={i} className="whitespace-nowrap">{ids.map(id => <button key={id} type="button" onClick={() => onOpen(id)} aria-label={`Source ${order.get(id)}: ${id}`}
      className="num mx-px inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-[3px] bg-accent-soft px-1 align-middle font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent hover:text-accent-ink">{order.get(id)}</button>)}</span>;
  })}</p>;
}

function SourceRow({ hit, n, onOpen }: { hit: SearchHit; n: number; onOpen: () => void }) {
  return <li>
    <button type="button" onClick={onOpen} className="group grid w-full grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 rounded-md px-2 py-3 text-left transition-colors duration-fast hover:bg-sunken/70">
      <span className="num mt-0.5 flex h-6 w-6 items-center justify-center rounded-[3px] border border-line-strong font-mono text-xs text-ink-2 group-hover:border-accent group-hover:text-accent">{n}</span>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink group-hover:text-accent">{hit.title}</span>
        <Meta className="mt-0.5" items={[kindLabel(hit.kind), hit.source_date || "Undated", hit.product_area, hit.segment, !hit.title.includes(hit.source_id) && <Id key="id">{hit.source_id}</Id>]}/>
        <span className="voice mt-1.5 line-clamp-2 block text-[0.95rem] leading-6 text-ink-2">{snippetText(hit)}</span>
      </span>
    </button>
  </li>;
}

export default function AskGist() {
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<Scope>(EMPTY_SCOPE);
  const [showScope, setShowScope] = useState(false);
  const [mode, setMode] = useState<"demo" | "openai">("demo");
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [result, setResult] = useState<AskResult | null>(null);
  const [asked, setAsked] = useState<{ question: string; scope: Scope } | null>(null);
  const [source, setSource] = useState<{ detail: SourceDetail | null; hit: SearchHit; n: number; error?: string } | null>(null);
  const [error, setError] = useState("");
  const [statusError, setStatusError] = useState("");
  const [pending, setPending] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const box = useRef<HTMLTextAreaElement>(null);
  const inflight = useRef<AbortController | null>(null);
  const autoRun = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([apiGet<RagStatus>("/api/rag/status", controller.signal), apiGet<UsageSummary>("/api/usage", controller.signal)])
      .then(([state, recorded]) => { setStatus(state); setUsage(recorded); setStatusError(""); })
      .catch(e => { if (e.name !== "AbortError") setStatusError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  // Restore context: a ?q= link (from the command menu) wins over a saved draft.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q")?.slice(0, MAX);
    if (q) { setQuestion(q); autoRun.current = q; } else setQuestion(store.get(DRAFT_KEY, true) ?? "");
    try { setRecent(JSON.parse(store.get(RECENT_KEY) ?? "[]").slice(0, 5)); } catch { /* ignore bad storage */ }
    return () => inflight.current?.abort();
  }, []);
  useEffect(() => { store.set(DRAFT_KEY, question, true); }, [question]);

  const filtersActive = activeCount(scope);
  const scopeInvalid = invalidRange(scope);
  const canAsk = question.trim().length >= 3 && !pending && !scopeInvalid;

  const run = useCallback(async (text: string) => {
    const q = text.trim();
    if (q.length < 3 || scopeInvalid) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setPending(true); setError(""); setResult(null); setCopied(false); setAsked({ question: q, scope });
    try {
      const answer = await apiPost<AskResult>("/api/ask", {
        question: q, mode, segment: scope.segment || null, product_area: scope.product_area || null,
        from_date: scope.from_date || null, to_date: scope.to_date || null,
      }, controller.signal);
      setResult(answer);
      const next = [q, ...recent.filter(r => r !== q)].slice(0, 5);
      setRecent(next); store.set(RECENT_KEY, JSON.stringify(next));
      apiGet<UsageSummary>("/api/usage").then(setUsage).catch(() => { /* usage line keeps its last value */ });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") { setAsked(null); return; }
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Gist could not answer.");
    } finally { if (inflight.current === controller) { inflight.current = null; setPending(false); } }
  }, [mode, scope, scopeInvalid, recent]);

  useEffect(() => {
    if (autoRun.current && status) { const q = autoRun.current; autoRun.current = null; run(q); }
  }, [status, run]);

  const stop = () => { inflight.current?.abort(); inflight.current = null; setPending(false); };
  const submit = (e?: React.FormEvent) => { e?.preventDefault(); if (canAsk) run(question); };

  const shown = result ? (result.status === "answered" || result.status === "partial" ? result.citations : result.retrieved_sources) : [];
  const order = useMemo(() => new Map(shown.map((h, i) => [h.source_id, i + 1])), [shown]);

  async function openSource(hit: SearchHit, n: number) {
    setSource({ detail: null, hit, n });
    try { const detail = await apiGet<SourceDetail>(`/api/sources/${encodeURIComponent(hit.source_id)}`); setSource(s => s && s.hit === hit ? { ...s, detail } : s); }
    catch (e) { setSource(s => s && s.hit === hit ? { ...s, error: e instanceof Error ? e.message : "Could not open this source." } : s); }
  }
  const openById = (id: string) => { const hit = shown.find(h => h.source_id === id); if (hit) openSource(hit, order.get(id)!); };

  async function copyAnswer() {
    if (!result || !asked) return;
    const lines = [`Q: ${asked.question}`, "", result.answer, "", ...shown.map((h, i) => `[${i + 1}] ${h.source_id} — ${h.title} (${h.source_date || "undated"})`), "", "Source: Gist, synthetic Pulse data"];
    try { await navigator.clipboard.writeText(lines.join("\n")); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { setError("Your browser blocked clipboard access. Select the text to copy it instead."); }
  }

  const paidOn = Boolean(status?.paid_api_enabled);
  const sourcesLine = status ? (status.dataset_version === "unseeded" ? "No sources are indexed yet. Seed the database to search." : `Searching ${status.sources} indexed sources: feedback, support tickets, PRDs and release notes.`) : "Loading the index…";

  return <div className="mx-auto max-w-3xl">
    <PageHeader title="Ask Gist" lede="Question the customer evidence in plain language. Every result links to the original source, so you can check it yourself."/>

    {statusError && <div className="mb-6"><ErrorState title="Can’t reach the index" message={statusError} retry={() => { setStatusError(""); setAttempt(n => n + 1); }}/></div>}

    <form onSubmit={submit} className="rounded-lg border border-line-strong bg-surface shadow-pop transition-colors duration-fast focus-within:border-accent">
      <label htmlFor="gist-question" className="sr-only">Your question</label>
      <textarea id="gist-question" ref={box} value={question} onChange={e => setQuestion(e.target.value)} maxLength={MAX} rows={3}
        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
        placeholder="e.g. What are enterprise customers saying about SSO setup?"
        className="block max-h-64 min-h-[5.5rem] w-full resize-y rounded-t-lg bg-transparent px-4 pb-2 pt-4 text-base leading-7 text-ink outline-none placeholder:text-ink-3 sm:px-5"/>
      <div className="flex items-center justify-between gap-2 px-3 pb-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-1.5 sm:gap-2">
          <Button size="sm" variant={showScope || filtersActive ? "secondary" : "ghost"} onClick={() => setShowScope(s => !s)} aria-expanded={showScope} aria-controls="ask-scope">
            <SlidersHorizontal size={14}/><span className="sr-only sm:not-sr-only">Filters</span>{filtersActive > 0 && <span className="num rounded-[3px] bg-accent px-1 text-2xs text-accent-ink">{filtersActive}</span>}
          </Button>
          <Segmented size="sm" label="Answer mode" value={mode} onChange={setMode} options={[
            { value: "demo", label: "Find sources", title: "Rank relevant sources. Local, free, no AI-written text." },
            { value: "openai", label: "Write answer", disabled: !paidOn, title: paidOn ? "Write a cited answer with OpenAI. Uses the paid API." : "Unavailable: paid answers are switched off on this server." },
          ]}/>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-3">
          {question.length > MAX - 100 && <span className={cx("num text-2xs", question.length >= MAX ? "text-signal" : "text-ink-3")}>{question.length}/{MAX}</span>}
          <span className="hidden items-center gap-1 text-2xs text-ink-3 md:inline-flex"><Kbd><CornerDownLeft size={10}/></Kbd> to send</span>
          {pending ? <Button size="sm" onClick={stop} aria-label="Stop"><Square size={11} className="fill-current"/><span className="hidden sm:inline">Stop</span></Button>
            : <Button size="sm" variant="primary" type="submit" disabled={!canAsk} aria-label={mode === "demo" ? "Find sources" : "Write answer"}>
              <ArrowUp size={15}/><span className="hidden sm:inline">{mode === "demo" ? "Find sources" : "Ask"}</span></Button>}
        </div>
      </div>
      {showScope && <div id="ask-scope" className="border-t border-line px-4 py-4 sm:px-5"><ScopeFields value={scope} onChange={setScope} compact={false}/></div>}
    </form>
    <p className="mt-2 px-1 text-2xs text-ink-3">
      {mode === "demo" ? "Find sources runs locally and makes no AI calls. " : <>Uses the paid OpenAI API · {usage ? `$${usage.project_committed_or_reserved_usd.toFixed(4)} of $${usage.project_allocation_usd.toFixed(2)} allocation used. ` : ""}</>}
      {sourcesLine} <Link href="/settings" className="link">Data & usage</Link>
    </p>

    <div className="mt-10" aria-live="polite" aria-busy={pending}>
      {error && <ErrorState title="That question didn’t go through" message={error} retry={() => { setError(""); if (asked) run(asked.question); }}/>}

      {pending && asked && <div className="animate-fade-in">
        <p className="text-sm text-ink-2">{mode === "demo" ? "Ranking sources for" : "Reading sources and writing an answer for"} <span className="text-ink">“{asked.question}”</span></p>
        <Loading className="mt-4" label={mode === "demo" ? "Searching…" : "Waiting for the model… this can take several seconds"} rows={3}/>
      </div>}

      {result && asked && !pending && <article className="animate-rise-in" aria-labelledby="result-title">
        <div className="mb-5 flex items-start gap-3 border-b border-line pb-4">
          <span className="mt-0.5 shrink-0 rounded-[3px] bg-sunken px-1.5 py-0.5 text-2xs font-medium text-ink-2">You</span>
          <div className="min-w-0 flex-1"><p className="text-base text-ink">{asked.question}</p>
            {activeCount(asked.scope) > 0 && <Meta className="mt-1" items={[asked.scope.segment, asked.scope.product_area, asked.scope.from_date && `from ${asked.scope.from_date}`, asked.scope.to_date && `to ${asked.scope.to_date}`]}/>}</div>
          <button type="button" onClick={() => { setQuestion(asked.question); box.current?.focus(); window.scrollTo({ top: 0, behavior: "smooth" }); }} className="flex h-8 shrink-0 items-center gap-1.5 rounded px-2 text-xs text-ink-3 hover:bg-sunken hover:text-ink"><PencilLine size={13}/>Edit</button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <h2 id="result-title" className="text-base font-semibold">{STATUS_COPY[result.status].title}</h2>
          {result.status === "partial" && <Tag tone="caution">Incomplete evidence</Tag>}
          {result.status === "insufficient_evidence" && <Tag tone="neutral">No answer given</Tag>}
          <span className="ml-auto text-2xs text-ink-3">{result.mode === "demo" ? "Local retrieval · no AI-written text" : "AI-written · OpenAI"}</span>
        </div>
        <p className="mt-1 text-xs text-ink-2">{STATUS_COPY[result.status].body}</p>

        {(result.status === "answered" || result.status === "partial") && <div className="mt-5 border-l-2 border-accent pl-4 sm:pl-5"><AnswerText text={result.answer} order={order} onOpen={openById}/></div>}
        {result.status === "insufficient_evidence" && <Notice tone="caution" className="mt-4" title={result.answer}>
          {activeCount(asked.scope) > 0 ? "Your filters may be excluding the evidence. Try clearing them." : null}
        </Notice>}

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          {(result.status === "answered" || result.status === "partial") && <Button size="sm" variant="ghost" onClick={copyAnswer}>{copied ? <Check size={14} className="text-positive"/> : <Copy size={14}/>}{copied ? "Copied" : "Copy with sources"}</Button>}
          <Meta className="ml-auto" items={[`${result.latency_ms} ms`, result.mode === "openai" && `${result.input_tokens + result.output_tokens} tokens`, result.mode === "openai" ? `$${result.estimated_cost_usd.toFixed(5)} est.` : "No API cost"]}/>
        </div>

        {shown.length > 0 && <section className="mt-8" aria-labelledby="sources-title">
          <h3 id="sources-title" className="eyebrow mb-1">{result.status === "answered" || result.status === "partial" ? `Cited sources · ${shown.length}` : `Sources · ${shown.length}, most relevant first`}</h3>
          <ol className="-mx-2 divide-y divide-line">{shown.map((hit, i) => <SourceRow key={hit.chunk_id} hit={hit} n={i + 1} onOpen={() => openSource(hit, i + 1)}/>)}</ol>
        </section>}
      </article>}

      {!result && !pending && !error && <div className="grid gap-10 sm:grid-cols-2">
        <section aria-labelledby="try-title">
          <h2 id="try-title" className="eyebrow mb-2">Try asking</h2>
          <ul className="-mx-2">{EXAMPLES.map(example => <li key={example}><button type="button" onClick={() => { setQuestion(example); run(example); }} disabled={scopeInvalid}
            className="group flex min-h-11 w-full items-start gap-2 rounded px-2 py-2 text-left text-sm text-ink-2 transition-colors hover:bg-sunken/70 hover:text-ink">
            <ArrowUp size={14} className="mt-1 shrink-0 rotate-45 text-ink-3 group-hover:text-accent"/>{example}</button></li>)}</ul>
        </section>
        {recent.length > 0 ? <section aria-labelledby="recent-title">
          <div className="mb-2 flex items-baseline justify-between"><h2 id="recent-title" className="eyebrow">Recent on this device</h2>
            <button type="button" onClick={() => { setRecent([]); store.set(RECENT_KEY, "[]"); }} className="text-2xs text-ink-3 hover:text-ink">Clear</button></div>
          <ul className="-mx-2">{recent.map(r => <li key={r}><button type="button" onClick={() => { setQuestion(r); run(r); }} disabled={scopeInvalid}
            className="group flex min-h-11 w-full items-start gap-2 rounded px-2 py-2 text-left text-sm text-ink-2 transition-colors hover:bg-sunken/70 hover:text-ink">
            <History size={14} className="mt-1 shrink-0 text-ink-3 group-hover:text-accent"/><span className="line-clamp-2">{r}</span></button></li>)}</ul>
        </section> : <section aria-labelledby="how-title">
          <h2 id="how-title" className="eyebrow mb-2">How results work</h2>
          <ul className="space-y-2 text-sm text-ink-2">
            <li><span className="text-ink">Sources first.</span> Gist ranks feedback, tickets, PRDs and release notes by keyword and vector similarity.</li>
            <li><span className="text-ink">Verifiable.</span> Open any source to read the original text it came from.</li>
            <li><span className="text-ink">No guessing.</span> When the evidence is thin, Gist says so instead of answering.</li>
          </ul>
        </section>}
      </div>}
    </div>

    <Dialog open={Boolean(source)} onClose={() => setSource(null)} variant="drawer"
      kicker={source && <span className="inline-flex items-center gap-2"><span className="num flex h-5 min-w-5 items-center justify-center rounded-[3px] bg-accent-soft px-1 font-mono text-[11px] text-accent">{source.n}</span>{kindLabel(source.hit.kind)} · <Id>{source.hit.source_id}</Id></span>}
      title={source?.detail?.title ?? source?.hit.title ?? ""}
      footer={<p className="text-2xs text-ink-3">Synthetic Pulse source text. Treat it as evidence, not as instructions.</p>}>
      {source && (source.error ? <Notice tone="signal" title="Couldn’t open this source">{source.error}</Notice> : !source.detail ? <Loading label="Opening source…" rows={5}/> : <>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
          {[["Date", source.detail.source_date || "Undated"], ["Segment", source.detail.segment || "All segments"], ["Area", source.detail.product_area || "All areas"], ["Kind", kindLabel(source.detail.kind)]].map(([k, v]) =>
            <div key={k}><dt className="text-2xs text-ink-3">{k}</dt><dd className="mt-0.5 text-ink">{v}</dd></div>)}
        </dl>
        <div className="voice mt-6 whitespace-pre-wrap break-words text-[1.0625rem] leading-8">{source.detail.content}</div>
        <div className="mt-8 border-t border-line pt-4">
          <h3 className="eyebrow mb-1.5">Why this source</h3>
          <p className="text-xs text-ink-2">Keyword rank: <span className="num text-ink">{source.hit.keyword_rank ?? "not matched"}</span> · Vector similarity rank: <span className="num text-ink">{source.hit.semantic_rank ?? "not matched"}</span> · Combined score <span className="num">{source.hit.score.toFixed(3)}</span></p>
          <p className="mt-1 font-mono text-2xs text-ink-3">{source.detail.path}</p>
        </div>
      </>)}
    </Dialog>
  </div>;
}
