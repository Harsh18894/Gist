"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, ChevronDown, Database, TriangleAlert } from "lucide-react";
import { apiGet, areas, Experiment, ExperimentList, ExperimentStatus } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { cx, EmptyState, Id, Meta, Notice, PageHeader, SearchField, Select, Status } from "@/components/ui";

const STATUS: Record<ExperimentStatus, { label: string; tone: "accent" | "caution" | "neutral" }> = {
  draft: { label: "Suggestion ready", tone: "accent" }, failed_checks: { label: "Withheld by checks", tone: "caution" },
  stale: { label: "Evidence changed", tone: "caution" }, not_generated: { label: "No draft yet", tone: "neutral" },
};

function List({ title, items }: { title: string; items: string[] }) {
  return <div><h4 className="eyebrow">{title}</h4>
    <ul className="mt-2 list-disc space-y-1 pl-4 text-sm leading-6 text-ink-2 marker:text-ink-3">{items.map(i => <li key={i}>{i}</li>)}</ul></div>;
}
function Item({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><h4 className="eyebrow">{title}</h4><div className="mt-1.5 text-sm leading-6 text-ink">{children}</div></div>;
}

function Card({ e }: { e: Experiment }) {
  const [open, setOpen] = useState(false);
  const s = e.suggestion;
  const panelId = `${e.opportunity_id}-plan`;
  return <article className="overflow-hidden rounded-lg border border-line bg-surface" aria-labelledby={`${e.opportunity_id}-title`}>
    <div className="px-5 pt-5 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Meta items={[<Id key="id">{e.opportunity_id}</Id>, e.area]}/>
        <Status tone={STATUS[e.status].tone}>{STATUS[e.status].label}</Status>
      </div>
      <h3 id={`${e.opportunity_id}-title`} className="mt-2 text-base font-semibold leading-6">{e.facts.problem_statement}</h3>
    </div>

    <section className="mx-5 mt-4 rounded-md bg-sunken/70 px-4 py-3 sm:mx-6" aria-label="Facts from data">
      <h4 className="flex items-center gap-1.5 text-2xs font-medium text-ink-2"><Database size={12} aria-hidden="true"/>Facts from data</h4>
      <dl className="mt-1.5 grid gap-x-6 gap-y-1 text-xs text-ink-2 sm:grid-cols-2">
        <div><dt className="inline text-ink-3">Segments: </dt><dd className="inline">{e.facts.affected_segments_text}</dd></div>
        <div><dt className="inline text-ink-3">Last 90 days: </dt><dd className="num inline">{e.facts.baseline.records_last_90_days} records ({e.facts.baseline.records_prior_90_days} the 90 days before) · {e.facts.baseline.linked_tickets} linked tickets</dd></div>
        {e.facts.documents.length > 0 && <div className="sm:col-span-2"><dt className="inline text-ink-3">Related documents: </dt><dd className="inline">{e.facts.documents.map(d => `${d.title} (${d.id})`).join(", ")}</dd></div>}
      </dl>
      <p className="mt-1.5 text-2xs text-ink-3">{e.facts.baseline.note}</p>
    </section>

    {s ? <section className="px-5 pb-5 pt-5 sm:px-6" aria-label="AI suggestion">
      <p className="flex flex-wrap items-center gap-x-2 text-2xs text-ink-3"><span className="rounded-[3px] border border-dashed border-accent/60 px-1.5 py-0.5 font-medium text-accent">AI suggestion · not validated</span>
        <span>{s.label}{e.generation && ` Model ${e.generation.model}, prompt ${e.generation.prompt_version}.`}</span></p>
      <div className="mt-3 border-l-2 border-dashed border-accent/50 pl-4">
        <h4 className="eyebrow">Hypothesis</h4>
        <p className="mt-1.5 text-[0.975rem] leading-7 text-ink">{s.hypothesis}</p>
      </div>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} aria-controls={panelId} className="mt-4 flex h-9 items-center gap-1.5 text-xs font-medium text-accent">
        <ChevronDown size={14} className={cx("transition-transform duration-fast", open && "rotate-180")} aria-hidden="true"/>{open ? "Hide full plan" : "Show full plan: intervention, metrics, design, risks"}
      </button>
      {open && <div id={panelId} className="mt-3 grid gap-6 border-t border-line pt-5 animate-fade-in md:grid-cols-2">
        <Item title="Intervention">{s.intervention}</Item>
        <Item title="Target audience">{s.target_audience}</Item>
        <Item title="Primary metric"><p className="font-medium">{s.primary_metric.name}</p><p className="text-ink-2">{s.primary_metric.definition}</p></Item>
        <Item title="Guardrail metrics"><ul className="space-y-1">{s.guardrail_metrics.map(g => <li key={g.name}><span className="font-medium">{g.name}</span> <span className="text-ink-2">— {g.why}</span></li>)}</ul></Item>
        <div className="md:col-span-2"><Item title={`Experiment design · ${s.experiment_design.type}`}>{s.experiment_design.description}
          <p className="mt-1 text-xs text-ink-3">Baseline, sample size, duration and expected effect aren’t suggested; set them from product analytics.</p></Item></div>
        <List title="Risks" items={s.risks}/>
        <List title="Assumptions to validate" items={s.assumptions_to_validate}/>
      </div>}
    </section> : <div className="px-5 pb-5 pt-4 sm:px-6"><p className="flex items-start gap-2 text-sm text-ink-2">
      <TriangleAlert size={15} className="mt-0.5 shrink-0 text-caution" aria-hidden="true"/>
      <span>{e.status === "failed_checks" ? <>The AI draft was withheld because it failed automated checks: {e.problems.join("; ")}.</>
        : e.status === "stale" ? "This opportunity’s evidence changed after the draft was made, so the draft is hidden until it is regenerated."
        : "No suggestion has been drafted for this opportunity. Drafting is a separate, approved paid step."}</span></p></div>}

    <div className="border-t border-line px-5 py-3 sm:px-6">
      <Link href={`/opportunities?open=${encodeURIComponent(e.opportunity_id)}`} className="link inline-flex items-center gap-1 text-xs">See the evidence for {e.opportunity_id}<ArrowRight size={12}/></Link>
    </div>
  </article>;
}

export default function Experiments() {
  const [data, setData] = useState<ExperimentList | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [area, setArea] = useState("");
  const [status, setStatus] = useState("");
  const [design, setDesign] = useState("");
  const [filter, setFilter] = useState("");
  const reload = useCallback(() => setAttempt(n => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<ExperimentList>("/api/experiments", controller.signal).then(r => { setData(r); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (data?.experiments ?? []).filter(e => (!area || e.area === area) && (!status || e.status === status)
      && (!design || e.suggestion?.experiment_design.type === design)
      && (!needle || JSON.stringify([e.facts.problem_statement, e.suggestion]).toLowerCase().includes(needle)));
  }, [data, area, status, design, filter]);
  const clear = () => { setArea(""); setStatus(""); setDesign(""); setFilter(""); };

  return <>
    <PageHeader title="Experiments" lede="One test idea per opportunity. Facts come from the data; the hypothesis, metrics and design are AI suggestions for you to review, not recommendations Gist has validated."/>

    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !data ? <Loading label="Loading experiments…" rows={8}/> : <>
      <Notice className="mb-6">{data.interpretation} <span className="font-medium text-ink"><span className="num">{data.counts.draft}</span> suggestions ready, <span className="num">{data.counts.failed_checks}</span> withheld by checks{data.counts.stale ? `, ${data.counts.stale} stale` : ""}{data.counts.not_generated ? `, ${data.counts.not_generated} not drafted` : ""}.</span></Notice>

      <div className="mb-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-[minmax(0,1fr)_10rem_12rem_12rem]">
        <SearchField value={filter} onChange={setFilter} label="Filter experiments" placeholder="Filter by words" className="sm:col-span-3 lg:col-span-1"/>
        <Select aria-label="Product area" value={area} onChange={e => setArea(e.target.value)}><option value="">All areas</option>{areas.map(a => <option key={a}>{a}</option>)}</Select>
        <Select aria-label="Experiment design" value={design} onChange={e => setDesign(e.target.value)}><option value="">All designs</option>{data.design_types.map(d => <option key={d}>{d}</option>)}</Select>
        <Select aria-label="Status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{(Object.keys(STATUS) as ExperimentStatus[]).map(k => <option key={k} value={k}>{STATUS[k].label}</option>)}</Select>
      </div>
      <p className="mb-5 text-xs text-ink-3"><span className="num">{visible.length}</span> of <span className="num">{data.experiments.length}</span> shown · ordered by opportunity ID, not priority (see <Link href="/priorities" className="link">Priorities</Link>).</p>

      {visible.length === 0 ? <div className="rounded-lg border border-line bg-surface"><EmptyState title="No experiments match" action={<button type="button" onClick={clear} className="link text-sm">Clear filters</button>}>Remove a filter to see more.</EmptyState></div> :
        <div className="grid gap-5 xl:grid-cols-2">{visible.map(e => <Card key={e.opportunity_id} e={e}/>)}</div>}
    </>}
  </>;
}
