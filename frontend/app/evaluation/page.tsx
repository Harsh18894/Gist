"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleCheck, CircleX, ShieldAlert, ShieldCheck } from "lucide-react";
import { apiGet, apiSend, BenchmarkMetric, BenchmarkRun, Benchmarks, FeedbackSummary, Regressions, Runtime } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { usePublicStatus } from "@/lib/public";
import { Button, cx, Field, Figure, Id, Input, Meta, Notice, PageHeader, Section, Select, Status, Tag } from "@/components/ui";

const FAMILY: Record<string, string> = {
  "retrieval-strategy": "Retrieval strategies", "answer-budget": "Answer output budget", "frozen-finals": "Phase 2 frozen finals",
  "judge-prompt": "AI judge prompts", "product-intelligence": "Product intelligence (Phase 3)", "investigation-prompt": "Investigations (Phase 4)",
};
const JUDGE_TONE = { automatic: "accent", owner: "positive", "ai-judge": "caution" } as const;
const KIND_LABEL: Record<string, string> = { "frozen-final": "frozen final", development: "development", diagnostic: "diagnostic" };

function fmt(m: BenchmarkMetric): string {
  if (m.not_applicable) return "n/a";
  if (m.value === null) return "—";
  const v = m.value;
  const body = m.unit === "share" ? `${(v * 100).toFixed(1)}%` : m.unit === "usd" ? `$${v.toFixed(4)}` : m.unit === "ms" ? `${Math.round(v).toLocaleString()} ms`
    : m.unit === "ratio" ? v.toFixed(2) : Number.isInteger(v) ? String(v) : v.toFixed(1);
  return m.of ? `${body} of ${m.of}` : body;
}
const usd = (v: number | null | undefined, d = 4) => v === null || v === undefined ? "—" : `$${v.toFixed(d)}`;
// Accepted limitations are amber (caution), not red: they were recorded and accepted, not hidden or failing silently.
const statusTone = (s: BenchmarkRun["status"]) => s === "met" ? "positive" as const
  : s === "partly_met" || s === "below_target" || s === "below_release_bar" ? "caution" as const : "neutral" as const;

function RunRow({ run }: { run: BenchmarkRun }) {
  return <li className="py-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="text-sm font-medium text-ink">{run.title}</p>
      <Status tone={statusTone(run.status)}>{run.verdict}</Status>
    </div>
    <Meta className="mt-1" items={[`Phase ${run.phase}`, <Tag key="k" tone={run.kind === "frozen-final" ? "accent" : "neutral"}>{KIND_LABEL[run.kind] ?? run.kind}</Tag>, run.split,
      <Status key="j" tone={JUDGE_TONE[run.judged_by as keyof typeof JUDGE_TONE] ?? "neutral"}>judged: {run.judged_by}</Status>, run.version]}/>
    {run.target_note && <p className="mt-1.5 text-xs text-ink-2">{run.target_note}</p>}
    <dl className="mt-2.5 grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-5">{run.metrics.map(m => <div key={m.key}>
      <dt className="text-2xs text-ink-3">{m.label}</dt><dd className="num text-sm text-ink" title={m.problem ?? undefined}>{fmt(m)}</dd></div>)}</dl>
    <details className="mt-2">
      <summary className="cursor-pointer text-2xs font-medium text-accent">Configuration, process and files</summary>
      <div className="mt-2 space-y-1 text-xs text-ink-2">
        <p>Configuration: {Object.entries(run.config).map(([k, v]) => `${k} = ${v}`).join(" · ")}</p>
        <p>Benchmark: {run.benchmark}. Process: <Id>{run.process}</Id></p>
        {run.files.map(f => <p key={f.path}><Id>{f.path}</Id> <span className="text-ink-3">sha256 {f.sha256?.slice(0, 12) ?? "missing"}…</span></p>)}
      </div>
    </details>
  </li>;
}

function Compare({ runs }: { runs: BenchmarkRun[] }) {
  const keys = Array.from(new Map(runs.flatMap(r => r.metrics.map(m => [m.key, m] as const))).values());
  const configKeys = Array.from(new Set(runs.flatMap(r => Object.keys(r.config))));
  // "Best" only among runs on the same benchmark and split: different question sets are not comparable.
  const best = (key: string, run: BenchmarkRun) => {
    const peers = runs.filter(r => r.benchmark === run.benchmark && r.split === run.split);
    const vals = peers.map(r => r.metrics.find(m => m.key === key)).filter((m): m is BenchmarkMetric => !!m && m.value !== null);
    if (vals.length < 2) return null;
    return vals[0].better === "lower" ? Math.min(...vals.map(v => v.value!)) : Math.max(...vals.map(v => v.value!));
  };
  return <div className="relative overflow-x-auto rounded-lg border border-line bg-surface">
    <table className="w-full min-w-[640px] text-left text-xs">
      <thead className="border-b border-line bg-sunken/50 text-ink-3"><tr><th className="py-2 pl-4 pr-3 font-medium">Measure</th>
        {runs.map(r => <th key={r.id} className="px-3 font-medium text-ink-2">{r.title}<span className="block font-normal text-ink-3">{r.benchmark} · {r.split}</span></th>)}</tr></thead>
      <tbody className="divide-y divide-line">
        {configKeys.map(k => {
          const values = runs.map(r => String(r.config[k] ?? "—"));
          const differs = new Set(values).size > 1;
          return <tr key={k} className={differs ? "bg-caution-soft/40" : ""}><td className="py-1.5 pl-4 pr-3 text-ink-3">{k}{differs && <span className="sr-only"> (differs)</span>}</td>
            {values.map((v, i) => <td key={i} className={cx("px-3", differs && "font-medium text-ink")}>{v}</td>)}</tr>;
        })}
        {keys.map(k => {
          return <tr key={k.key}><td className="py-1.5 pl-4 pr-3 text-ink-2">{k.label}<span className="block text-2xs text-ink-3">{k.better === "lower" ? "lower is better" : "higher is better"}</span></td>
            {runs.map(r => { const m = r.metrics.find(x => x.key === k.key);
              const top = best(k.key, r);
              return <td key={r.id} className={cx("num px-3", m && m.value !== null && top !== null && m.value === top && "font-semibold text-accent")}>{m ? fmt(m) : "—"}</td>; })}</tr>;
        })}
      </tbody>
    </table>
    <p className="border-t border-line px-4 py-2 text-2xs text-ink-3">Highlighted rows: configuration that differs between runs. Best value per measure in accent, compared only among runs on the same benchmark and split, because different question sets are not comparable.</p>
  </div>;
}

function Table({ head, rows, caption }: { head: string[]; rows: (string | number)[][]; caption: string }) {
  return <div className="relative overflow-x-auto rounded-lg border border-line bg-surface">
    <table className="w-full min-w-[560px] text-left text-xs"><caption className="sr-only">{caption}</caption>
      <thead className="border-b border-line bg-sunken/50 text-ink-3"><tr>{head.map(h => <th key={h} className="px-3 py-2 font-medium first:pl-4">{h}</th>)}</tr></thead>
      <tbody className="divide-y divide-line">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="num px-3 py-1.5 first:pl-4 text-ink-2">{c}</td>)}</tr>)}</tbody>
    </table></div>;
}

export default function Evaluation() {
  const [bench, setBench] = useState<Benchmarks | null>(null);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [feedback, setFeedback] = useState<FeedbackSummary | null>(null);
  const [regs, setRegs] = useState<Regressions | null>(null);
  const [error, setError] = useState("");
  const [family, setFamily] = useState("retrieval-strategy");
  const [kind, setKind] = useState("");
  const [billing, setBilling] = useState({ day: "", amount: "", source: "provider cost export" });
  const [billingMsg, setBillingMsg] = useState("");
  const readOnly = usePublicStatus()?.read_only ?? false;

  const load = useCallback(() => {
    Promise.all([apiGet<Benchmarks>("/api/eval/benchmarks"), apiGet<Runtime>("/api/observability/runtime"),
      apiGet<FeedbackSummary>("/api/feedback"), apiGet<Regressions>("/api/eval/regressions")])
      .then(([b, r, f, g]) => { setBench(b); setRuntime(r); setFeedback(f); setRegs(g); setError(""); })
      .catch(e => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const familyRuns = useMemo(() => (bench?.runs ?? []).filter(r => r.family === family), [bench, family]);
  const listed = useMemo(() => (bench?.runs ?? []).filter(r => !kind || r.kind === kind), [bench, kind]);

  const saveBilling = async () => {
    try {
      await apiSend("PUT", "/api/observability/billing", { day: billing.day, amount_usd: Number(billing.amount), source: billing.source });
      setBillingMsg("Saved."); setBilling(b => ({ ...b, day: "", amount: "" })); load();
    } catch (e) { setBillingMsg(e instanceof Error ? e.message : "Could not save."); }
  };

  if (error) return <ErrorState message={error} retry={load}/>;
  if (!bench || !runtime || !feedback || !regs) return <Loading label="Loading evaluation results…" rows={8}/>;
  const L = runtime.ledger, I = runtime.investigations;
  const regsOk = regs.cases.every(c => c.test_exists);

  return <>
    <PageHeader title="Evaluation" lede="Every quality, cost and reliability number in Gist, traced to a versioned result file or log. For developers: what was measured, how, by whom, and what it cost."/>
    <Notice className="mb-10">{bench.note} “Judged: owner” means human labels or review; “automatic” means scored by code against a fixed key; “ai-judge” was calibrated and not adopted as a measure.</Notice>

    <div className="space-y-14">
      <Section id="compare" title="Compare runs" description="Side by side within one family: configuration differences and the best value per measure."
        actions={<Select aria-label="Family" value={family} onChange={e => setFamily(e.target.value)} className="h-9 w-auto text-xs">
          {Object.keys(bench.families).map(f => <option key={f} value={f}>{FAMILY[f] ?? f} ({bench.families[f].length})</option>)}</Select>}>
        <Compare runs={familyRuns}/>
      </Section>

      <Section id="benchmarks" title={`Benchmark runs (${listed.length})`} description="Versioned results against targets set before each run. Frozen finals ran once and were never tuned against; results below target are recorded as accepted limitations."
        actions={<Select aria-label="Kind" value={kind} onChange={e => setKind(e.target.value)} className="h-9 w-auto text-xs">
          <option value="">All kinds</option><option value="frozen-final">Frozen finals</option><option value="development">Development</option><option value="diagnostic">Diagnostic</option></Select>}>
        <ul className="divide-y divide-line">{listed.map(r => <RunRow key={r.id} run={r}/>)}</ul>
      </Section>

      <Section id="runtime" title="Runtime cost and reliability" description={L.note}>
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <Figure label="Paid requests" value={L.totals.requests ?? 0}/>
          <Figure label="Ledger cost" value={usd(L.totals.cost_usd, 3)} detail={`of the $${L.totals.cap_usd?.toFixed(2)} cap`}/>
          <Figure label="Uncertain requests" value={L.totals.uncertain ?? 0} tone={L.totals.uncertain ? "signal" : undefined} detail={`${L.totals.reconciled ?? 0} reconciled`}/>
          <Figure label="AI investigation cost" value={usd(I.cost_per_ai_investigation?.mean_usd)} detail={`mean of ${I.cost_per_ai_investigation?.runs ?? 0}; max ${usd(I.cost_per_ai_investigation?.max_usd)}`}/>
        </div>
        <h3 className="mb-2 mt-8 text-xs font-semibold uppercase tracking-wide text-ink-3">By UTC day, with provider billing</h3>
        <Table caption="Spend by day" head={["Day (UTC)", "Requests", "Tokens in / out", "Ledger cost", "Billed", "Ledger ÷ billed", "p50 / p95 latency", "Failed or uncertain"]}
          rows={L.by_day.map(d => { const b = runtime.billing.days.find(x => x.day === d.key);
            return [d.key, d.requests, `${d.input_tokens.toLocaleString()} / ${d.output_tokens.toLocaleString()}`, usd(d.cost_usd), usd(b?.billed_usd),
              b?.ledger_vs_billed ? `${(b.ledger_vs_billed * 100).toFixed(1)}%` : "—", `${d.latency_p50_ms ?? "—"} / ${d.latency_p95_ms ?? "—"} ms`, d.failed_or_uncertain]; })}/>
        {!readOnly && <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={e => { e.preventDefault(); saveBilling(); }}>
          <Field label="Billed day (UTC)" htmlFor="bill-day"><Input id="bill-day" type="date" value={billing.day} onChange={e => setBilling({ ...billing, day: e.target.value })} className="h-9 w-40"/></Field>
          <Field label="Amount (USD)" htmlFor="bill-amt"><Input id="bill-amt" inputMode="decimal" value={billing.amount} onChange={e => setBilling({ ...billing, amount: e.target.value })} className="h-9 w-28"/></Field>
          <Field label="Source" htmlFor="bill-src"><Input id="bill-src" value={billing.source} maxLength={120} onChange={e => setBilling({ ...billing, source: e.target.value })} className="h-9 w-48"/></Field>
          <Button type="submit" size="sm" disabled={!billing.day || billing.amount === ""}>Save billed amount</Button>
          <span role="status" className="text-xs text-ink-3">{billingMsg}</span>
        </form>}
        <p className="mt-1 text-2xs text-ink-3">{runtime.billing.note}</p>

        <h3 className="mb-2 mt-8 text-xs font-semibold uppercase tracking-wide text-ink-3">By endpoint and model</h3>
        <Table caption="Spend by endpoint" head={["Endpoint · model", "Requests", "Tokens in / out", "Ledger cost", "p50 / p95 latency"]}
          rows={L.by_endpoint.map(d => [d.key, d.requests, `${d.input_tokens.toLocaleString()} / ${d.output_tokens.toLocaleString()}`, usd(d.cost_usd), `${d.latency_p50_ms ?? "—"} / ${d.latency_p95_ms ?? "—"} ms`])}/>
      </Section>

      <Section id="investigations" title="Investigations: traces and checks" description="From the hash-chained audit log."
        actions={<span className={cx("flex items-center gap-1.5 text-xs", I.audit?.ok ? "text-positive" : "text-signal")}>
          {I.audit?.ok ? <ShieldCheck size={14}/> : <ShieldAlert size={14}/>}{I.audit?.ok ? `Audit chain verified (${I.audit.entries})` : "Audit chain check failed"}</span>}>
        {!I.available ? <p className="text-sm text-ink-2">No investigations yet.</p> : <div className="grid gap-8 lg:grid-cols-2">
          <div className="space-y-4 text-sm">
            <Meta items={[`${I.runs} runs`, ...Object.entries(I.by_status ?? {}).map(([k, v]) => `${v} ${k}`)]}/>
            <Meta items={Object.entries(I.by_planner ?? {}).map(([k, v]) => `${v} × ${k}`)}/>
            <div><p className="text-xs font-semibold text-ink-2">AI report outcomes</p>
              <Meta className="mt-1" items={Object.entries(I.report_status ?? {}).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`)}/></div>
            {Object.keys(I.report_problems ?? {}).length > 0 && <div><p className="text-xs font-semibold text-ink-2">Why reports were withheld</p>
              <ul className="mt-1 space-y-0.5 text-xs text-ink-2">{Object.entries(I.report_problems!).map(([k, v]) => <li key={k}><span className="num font-medium text-ink">{v}×</span> {k}</li>)}</ul></div>}
            <div><p className="text-xs font-semibold text-ink-2">Recent</p>
              <ul className="mt-1 space-y-1 text-xs">{I.recent?.map(r => <li key={r.id}><Link href={`/investigate?id=${r.id}`} className="text-accent hover:underline">{r.question}</Link>
                <span className="text-ink-3"> · {r.planner} · {r.status} · {usd(r.cost_usd)}</span></li>)}</ul></div>
          </div>
          <Table caption="Step latency by tool" head={["Tool", "Steps", "p50", "p95"]} rows={(I.step_latency ?? []).map(t => [t.tool, t.steps, `${t.p50_ms} ms`, `${t.p95_ms} ms`])}/>
        </div>}
      </Section>

      <Section id="feedback" title={`User feedback (${feedback.total})`} description={feedback.note}>
        {feedback.total === 0 ? <p className="text-sm text-ink-2">No feedback yet. Use “Was this helpful?” under AI investigation reports and Ask answers.</p> : <>
          <Meta items={Object.entries(feedback.by_target).map(([k, v]) => `${k}: ${v.up} helpful, ${v.down} not helpful`)}/>
          <ul className="mt-3 divide-y divide-line text-xs">{feedback.recent.map(f => <li key={f.id} className="py-1.5">
            <Status tone={f.rating === "up" ? "positive" : "signal"}>{f.rating === "up" ? "helpful" : "not helpful"}</Status> <Id>{f.target_type} {f.target_id}</Id>
            {f.comment && <span className="text-ink-2"> · “{f.comment}”</span>}</li>)}</ul></>}
      </Section>

      <Section id="regressions" title={`Regression guards (${regs.cases.length})`} description={regs.note}
        actions={<Status tone={regsOk ? "positive" : "signal"}>{regsOk ? "every guard has a test" : "missing tests"}</Status>}>
        <ul className="divide-y divide-line text-xs">{regs.cases.map(c => <li key={c.id} className="flex gap-3 py-2">
          {c.test_exists ? <CircleCheck size={14} className="mt-0.5 shrink-0 text-positive" aria-label="test exists"/> : <CircleX size={14} className="mt-0.5 shrink-0 text-signal" aria-label="test missing"/>}
          <span><span className="text-ink">{c.failure}</span> <span className="text-ink-3">(Phase {c.phase})</span><Id className="block break-all">{c.test}</Id></span></li>)}</ul>
      </Section>
    </div>
  </>;
}
