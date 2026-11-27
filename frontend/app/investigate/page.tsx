"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { apiGet, apiPost, CitedItem, Investigation, InvestigationList, InvestigationReportBlock } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { FeedbackButtons } from "@/components/feedback";
import { Button, cx, Id, Input, Meta, Notice, PageHeader, Panel, Section, Segmented, Status, Tag } from "@/components/ui";

const EXAMPLES = [
  "Why did onboarding activation drop in October?",
  "Why did activation drop in February?",
  "Why did onboarding activation drop last month?",
  "Why did CRM sync failures rise in July?",
  "Are urgent alerts arriving late recently?",
  "Why is the portfolio dashboard slow in May?",
];
const KIND: Record<string, string> = { observed: "What changed", data_quality: "Data quality", timing: "Timing (not cause)", customer_voice: "What customers said" };
const stepTone = (s: string) => s === "ok" ? "positive" as const : s === "timeout" || s === "error" ? "signal" as const : "caution" as const;
const TYPE: Record<string, string> = { product_change: "Product change", segment_mix: "Mix shift (who was measured)", data_quality: "Data quality",
  volume_or_seasonality: "Volume or seasonality", unclear: "Unclear" };
const confTone = (c: string) => c === "high" ? "accent" as const : c === "medium" ? "caution" as const : "neutral" as const;

function Cites({ ids }: { ids: string[] }) {
  return <span className="ml-1.5 whitespace-nowrap">{ids.map(i => <a key={i} href={`#trace-${i}`} className="mr-1 font-mono text-[0.75em] text-accent hover:underline">{i}</a>)}</span>;
}

function CitedList({ title, items }: { title: string; items: CitedItem[] }) {
  if (!items?.length) return null;
  return <div><h4 className="text-xs font-semibold uppercase tracking-wide text-ink-3">{title}</h4>
    <ul className="mt-2 space-y-1.5 text-sm leading-6 text-ink">{items.map((c, i) => <li key={i}>{c.text}<Cites ids={c.evidence}/></li>)}</ul></div>;
}

function AiReport({ block, id }: { block: InvestigationReportBlock; id: string }) {
  const cost = block.usage.reduce((a, u) => a + (u.estimated_cost_usd ?? 0), 0);
  const meta = <Meta className="mt-1" items={[`prompt ${block.prompt_version}`, block.usage[0]?.model, `${block.usage.length} model calls`, `$${cost.toFixed(4)}`]}/>;
  if (!block.report) return <Notice tone="caution" title={block.status === "failed_checks" ? "AI report withheld: it failed Gist's checks" : "AI report unavailable"}>
    {(block.problems ?? []).join("; ")}. The measured findings below are unaffected.{meta}</Notice>;
  const r = block.report;
  return <section aria-labelledby="ai-report" className="rounded-lg border border-dashed border-accent/50 p-4 sm:p-5">
    <div className="flex flex-wrap items-center gap-2"><h2 id="ai-report" className="text-base font-semibold text-ink">AI report</h2><Tag tone="caution">Not validated</Tag></div>
    {meta}
    <p className="mt-3 text-sm leading-6 text-ink">{r.summary}</p>
    <div className="mt-5 space-y-6">
      <CitedList title="Observed changes" items={r.observed_changes}/>
      <div><h4 className="text-xs font-semibold uppercase tracking-wide text-ink-3">Possible explanations, most likely first</h4>
        <ol className="mt-2 space-y-3">{r.possible_explanations.map((e, i) => <li key={i} className="border-l-2 border-line pl-3">
          <Meta items={[<span key="t" className="font-medium text-ink-2">{TYPE[e.type] ?? e.type}</span>, <Status key="c" tone={confTone(e.confidence)}>{e.confidence} confidence</Status>]}/>
          <p className="mt-1 text-sm leading-6 text-ink">{e.text}<Cites ids={e.evidence}/></p>
          <p className="mt-0.5 text-xs text-ink-2">Why this confidence: {e.confidence_reason}</p>
          {e.conflicting && <p className="mt-0.5 text-xs text-ink-2">Against it: {e.conflicting}</p>}
        </li>)}</ol></div>
      <CitedList title="Conflicting evidence" items={r.conflicting_evidence}/>
      <CitedList title="Ruled out" items={r.ruled_out}/>
      <CitedList title="Data quality" items={r.data_quality}/>
      {r.suggested_experiments?.length > 0 && <div><h4 className="text-xs font-semibold uppercase tracking-wide text-ink-3">Suggested experiments or checks</h4>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-ink">{r.suggested_experiments.map(x => <li key={x}>{x}</li>)}</ul></div>}
      {r.limitations?.length > 0 && <p className="text-xs text-ink-3">Limitations noted by the model: {r.limitations.join(" ")}</p>}
    </div>
    <div className="mt-4"><FeedbackButtons targetType="investigation" targetId={id}/></div>
    <p className="mt-4 text-2xs text-ink-3">Gist checked this report before showing it: every claim cites a step that ran, every number appears in the tool results, and certainty language is rejected. It is still a model's reading of the evidence, not a confirmed cause.</p>
  </section>;
}

const runTone = (s: string) => s === "completed" ? "positive" as const : s === "rejected" ? "signal" as const : "caution" as const;

function Report({ run }: { run: Investigation }) {
  const steps = new Map(run.trace.map(t => [t.step, t]));
  const groups = Object.keys(KIND).map(k => [k, run.findings.filter(f => f.kind === k)] as const).filter(([, f]) => f.length);
  const limits = run.findings.filter(f => f.kind === "limitation");
  return <div className="space-y-10">
    <Panel className="p-4 sm:p-5">
      <p className="font-serif text-lg text-ink">{run.question}</p>
      <Meta className="mt-2" items={[<Status key="s" tone={runTone(run.status)}>{run.status}</Status>, `planner: ${run.planner}`,
        run.plan.window?.label, run.plan.window?.baseline && `baseline ${run.plan.window.baseline[0]} to ${run.plan.window.baseline[1]}`,
        `cost $${run.cost_usd.toFixed(2)}`, <Id key="id">{run.id}</Id>]}/>
      {run.plan.notes?.map(n => <p key={n} className="mt-2 text-xs text-ink-3">{n}</p>)}
    </Panel>

    {run.report && <AiReport block={run.report} id={run.id}/>}

    {run.checks.length > 0 && <div className="space-y-2">{run.checks.map((c, i) =>
      <Notice key={i} tone={c.kind === "plan_rejected" || c.kind === "tracking_gap" ? "signal" : "caution"} title={c.kind.replace(/_/g, " ")}>
        {c.message}{c.step && <> <Id>({c.step})</Id></>}</Notice>)}</div>}

    {groups.length > 0 && <Section id="findings" title="Measured findings" description="Each statement comes from one tool step (its ID is shown), computed without AI. These are what was measured, not explanations.">
      <div className="space-y-6">{groups.map(([kind, items]) => <div key={kind}>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-3">{KIND[kind]}</h3>
        <ul className="mt-2 space-y-2">{items.map((f, i) => <li key={i} className="flex gap-3 text-sm leading-6">
          <Id className="mt-0.5 w-6 shrink-0">{f.step}</Id>
          <span className={f.kind === "customer_voice" && f.text.startsWith("“") ? "voice text-[0.975rem] text-ink" : "text-ink"}>{f.text}</span></li>)}</ul>
      </div>)}</div>
    </Section>}

    <Section id="plan" title="Plan and trace" description="Validated before anything ran. Every step is a read-only tool from a fixed list, run in order under time and size limits.">
      <ol className="divide-y divide-line rounded-lg border border-line bg-surface">{run.trace.map(t => <li key={t.step} id={`trace-${t.step}`} className="scroll-mt-20 px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-medium text-ink"><Id className="mr-2">{t.step}</Id>{t.tool}</span>
          <Meta items={[<Status key="s" tone={stepTone(t.status)}>{t.status.replace(/_/g, " ")}</Status>, `${t.duration_ms} ms`, t.result_sha256 && <Id key="h">#{t.result_sha256}</Id>]}/>
        </div>
        <p className="mt-1 text-xs text-ink-2">{t.purpose}{t.error && <span className="text-signal"> · {t.error}</span>}</p>
        <details className="mt-1.5">
          <summary className="cursor-pointer text-2xs font-medium text-accent">Arguments and raw result</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded bg-sunken p-3 font-mono text-[11px] leading-4 text-ink-2">{JSON.stringify({ args: t.args, result: run.results[t.step] ?? null }, null, 1)}</pre>
        </details>
      </li>)}</ol>
      {run.trace.length === 0 && <p className="text-sm text-ink-2">No step ran: the plan was rejected by the validator.</p>}
    </Section>

    {limits.length > 0 && <Section id="limits" title="Limitations"><ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">{limits.map(l => <li key={l.text}>{l.text}</li>)}</ul></Section>}
  </div>;
}

export default function Investigate() {
  const [question, setQuestion] = useState("");
  const [planner, setPlanner] = useState<"rules" | "model">("rules");
  const [run, setRun] = useState<Investigation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<InvestigationList | null>(null);
  const [historyError, setHistoryError] = useState("");

  const loadHistory = useCallback(() => {
    apiGet<InvestigationList>("/api/investigations").then(h => { setHistory(h); setHistoryError(""); }).catch(e => setHistoryError(e.message));
  }, []);
  useEffect(loadHistory, [loadHistory]);

  useEffect(() => {  // deep link from the Evaluation page: /investigate?id=INV-…
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) open(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (q: string) => {
    const text = q.trim();
    if (text.length < 3) return;
    setQuestion(text); setBusy(true); setError("");
    try { setRun(await apiPost<Investigation>("/api/investigations", { question: text, planner })); loadHistory(); }
    catch (e) { setError(e instanceof Error ? e.message : "The investigation failed."); }
    finally { setBusy(false); }
  };
  const open = async (id: string) => {
    setBusy(true); setError("");
    try { const r = await apiGet<Investigation>(`/api/investigations/${encodeURIComponent(id)}`); setRun(r); setQuestion(r.question); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load that investigation."); }
    finally { setBusy(false); }
  };

  return <>
    <PageHeader title="Investigate" lede="Ask why a product metric changed. Gist writes a short plan, runs read-only tools over the product-events data and feedback, and reports what each step found, with every number traceable."/>

    <form onSubmit={e => { e.preventDefault(); submit(question); }} className="mb-3 flex flex-col gap-2 sm:flex-row">
      <label htmlFor="inv-q" className="sr-only">Question</label>
      <Input id="inv-q" value={question} onChange={e => setQuestion(e.target.value)} maxLength={500} placeholder="e.g. Why did onboarding activation drop in October?" className="flex-1"/>
      <Button type="submit" variant="primary" disabled={busy || question.trim().length < 3}>{busy ? "Investigating…" : "Investigate"}</Button>
    </form>
    <div className="mb-8 flex flex-wrap gap-1.5" aria-label="Example questions">
      {EXAMPLES.map(q => <button key={q} type="button" onClick={() => submit(q)} disabled={busy}
        className="rounded border border-line-strong bg-surface px-2.5 py-1 text-xs text-ink-2 transition-colors duration-fast hover:border-control hover:text-ink disabled:opacity-45">{q}</button>)}
    </div>
    <div className="mb-3"><Segmented label="Planner" value={planner} onChange={setPlanner} size="sm"
      options={[{ value: "rules", label: "Rules · $0" }, { value: "model", label: "AI plan + report · paid" }]}/></div>
    <Notice className="mb-8">{planner === "rules"
      ? "Rules planner ($0, no AI) picks the metric and time window. It measures; it does not explain causes."
      : "AI mode makes two guarded paid calls (about $0.002): a plan that must pass the same validator, and a report checked before it is shown. It works only when the server has paid-API approval configured; otherwise use the rules planner or open a past AI run from the list."}
      {" "}“Last month” means November 2025, as the data ends on 2025-12-15. Product-events data is synthetic.</Notice>

    <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_18rem]">
      <div aria-live="polite">
        {error ? <ErrorState message={error} retry={() => submit(question)}/>
          : busy && !run ? <Loading label="Running the investigation…" rows={6}/>
          : run ? <div className={cx(busy && "opacity-60")}><Report run={run}/></div>
          : <p className="text-sm text-ink-2">Pick an example or ask your own question to start.</p>}
      </div>
      <aside aria-label="Recent investigations">
        <h2 className="text-sm font-semibold text-ink">Recent investigations</h2>
        {history && <p className={cx("mt-1 flex items-center gap-1.5 text-2xs", history.audit.ok ? "text-positive" : "text-signal")}>
          {history.audit.ok ? <ShieldCheck size={13}/> : <ShieldAlert size={13}/>}
          {history.audit.ok ? `Audit log verified (${history.audit.entries} entries, hash-chained)` : `Audit log check failed at ${history.audit.first_bad}`}</p>}
        {historyError ? <p className="mt-2 text-xs text-signal">{historyError}</p>
          : !history ? <Loading label="Loading history…" rows={3}/>
          : history.investigations.length === 0 ? <p className="mt-2 text-xs text-ink-3">None yet.</p>
          : <ul className="mt-3 space-y-1">{history.investigations.map(h => <li key={h.id}>
            <button type="button" onClick={() => open(h.id)} className={cx("w-full rounded px-2 py-1.5 text-left transition-colors duration-fast hover:bg-sunken", run?.id === h.id && "bg-sunken")}>
              <span className="line-clamp-2 text-xs text-ink">{h.question}</span>
              <Meta items={[<Status key="s" tone={runTone(h.status)}>{h.status}</Status>, h.has_report && <Tag key="ai" tone="accent">AI report</Tag>, new Date(h.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })]}/>
            </button></li>)}</ul>}
      </aside>
    </div>
  </>;
}
