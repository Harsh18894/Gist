"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useState } from "react";
import { ArrowRight, ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { apiGet, apiSend, Effort, PartKey, PriorityRow, PriorityTable, Strategic } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { usePublicStatus } from "@/lib/public";
import { Button, buttonClass, cx, Id, Notice, PageHeader, Select, Tag, useFlash } from "@/components/ui";

type SortKey = "priority" | "per_effort";
const fmt = (n: number) => n.toFixed(1);

function ScoreBar({ value }: { value: number }) {
  return <span className="flex items-center gap-2.5">
    <span className="num w-9 text-right font-medium text-ink">{fmt(value)}</span>
    <span className="hidden h-1.5 w-16 bg-sunken sm:block" aria-hidden="true">
      <span className="block h-1.5 rounded-r-[2px] bg-accent" style={{ width: `${Math.max(0, Math.min(100, value))}%` }}/></span>
  </span>;
}

function Breakdown({ row }: { row: PriorityRow }) {
  return <div className="grid gap-6 md:grid-cols-[1.5fr_1fr]">
    <div className="scroll-x">
      <table className="w-full min-w-[30rem] text-left text-xs">
        <caption className="eyebrow mb-2 text-left">Measured from stored data</caption>
        <thead className="text-ink-3"><tr className="border-b border-line"><th className="py-1.5 pr-3 font-medium">Part</th><th className="pr-3 font-medium">Raw</th><th className="pr-3 font-medium">Score</th><th className="pr-3 font-medium">Weight</th><th className="text-right font-medium">Adds</th></tr></thead>
        <tbody className="divide-y divide-line">{row.measured.map(p => <tr key={p.part} className="align-top">
          <td className="py-2 pr-3"><span className="text-ink">{p.label}</span><span className="block text-2xs text-ink-3">{p.source}</span></td>
          <td className="num py-2 pr-3">{p.scaling === "share" ? `${Math.round(p.raw * 100)}%` : p.raw}</td>
          <td className="num py-2 pr-3">{fmt(p.score)}<span className="block text-2xs text-ink-3">{p.scaling === "rank" ? "rank vs others" : "the share itself"}</span></td>
          <td className="num py-2 pr-3">{p.weight}</td>
          <td className="num py-2 text-right font-medium">{fmt(p.contribution)}</td></tr>)}
          <tr className="border-t border-line-strong"><td colSpan={4} className="py-2 pr-3 text-right font-medium">Evidence score</td><td className="num py-2 text-right font-semibold">{fmt(row.evidence_score)}</td></tr>
        </tbody>
      </table>
    </div>
    <div className="text-xs leading-6 text-ink-2">
      <p className="eyebrow mb-2">Your estimates</p>
      <p>Strategic relevance: <span className="font-medium text-ink">{row.estimates.strategic ?? "not rated"}</span> (× {row.estimates.strategic_multiplier})</p>
      <p>Effort: <span className="font-medium text-ink">{row.estimates.effort ?? "not entered"}</span>{row.estimates.effort_points ? ` (${row.estimates.effort_points} points)` : ""}</p>
      <p className="num mt-2 rounded bg-sunken px-2.5 py-1.5 font-mono text-2xs text-ink">priority = {fmt(row.evidence_score)} × {row.estimates.strategic_multiplier} = {fmt(row.priority)}</p>
      <Link href={`/opportunities?open=${encodeURIComponent(row.opportunity_id)}`} className="link mt-3 inline-flex items-center gap-1 text-xs">See the evidence for {row.opportunity_id}<ArrowRight size={12}/></Link>
    </div>
  </div>;
}

function NoteEditor({ row, value, onChange, onSave }: { row: PriorityRow; value: string; onChange: (v: string) => void; onSave: () => void }) {
  const dirty = value !== (row.estimates.note ?? "");
  return <div className="mt-5">
    <label htmlFor={`note-${row.opportunity_id}`} className="mb-1.5 flex justify-between text-xs font-medium text-ink-2"><span>Note <span className="font-normal text-ink-3">— your context, for the team</span></span><span className="num font-normal text-ink-3">{value.length}/500</span></label>
    <textarea id={`note-${row.opportunity_id}`} maxLength={500} rows={2} value={value} onChange={e => onChange(e.target.value)}
      className="block w-full rounded border border-control/70 bg-surface p-2.5 text-sm text-ink outline-none hover:border-control focus:border-accent"/>
    <div className="mt-2 flex items-center gap-2"><Button size="sm" variant={dirty ? "primary" : "secondary"} disabled={!dirty} onClick={onSave}>Save note</Button>
      {dirty && <Button size="sm" variant="ghost" onClick={() => onChange(row.estimates.note ?? "")}>Discard</Button>}</div>
  </div>;
}

export default function Priorities() {
  const [data, setData] = useState<PriorityTable | null>(null);
  const readOnly = usePublicStatus()?.read_only ?? false;
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [sort, setSort] = useState<SortKey>("priority");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<PartKey, number> | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [flash, show] = useFlash();
  const reload = useCallback(() => setAttempt(n => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<PriorityTable>("/api/priorities", controller.signal)
      .then(r => { setData(r); setDraft(r.weights); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  const act = async (key: string, fn: () => Promise<unknown>, message: string) => {
    setSaving(key);
    try { await fn(); show(message); reload(); } catch (e) { show(e instanceof Error ? `Not saved: ${e.message}` : "Not saved. Try again.", "error"); }
    finally { setSaving(null); }
  };
  const saveInput = (row: PriorityRow, change: Partial<{ strategic: Strategic | null; effort: Effort | null; note: string | null }>) => {
    const body = { strategic: row.estimates.strategic, effort: row.estimates.effort, note: row.estimates.note, ...change };
    return act(row.opportunity_id, () => apiSend("PUT", `/api/priorities/${encodeURIComponent(row.opportunity_id)}`, body), `Saved ${row.opportunity_id}. Scores updated.`);
  };

  if (error) return <><PageHeader title="Priorities"/><ErrorState message={error} retry={() => { setError(""); reload(); }}/></>;
  if (!data || !draft) return <><PageHeader title="Priorities"/><Loading label="Scoring opportunities…" rows={8}/></>;

  const rows = [...data.rows].sort((a, b) => sort === "priority" ? a.rank - b.rank
    : (b.priority_per_effort_point ?? -1) - (a.priority_per_effort_point ?? -1) || a.rank - b.rank);
  const weightsChanged = (Object.keys(draft) as PartKey[]).some(k => draft[k] !== data.weights[k]);
  const custom = (Object.keys(data.weights) as PartKey[]).some(k => data.weights[k] !== data.default_weights[k]);
  const draftTotal = Object.values(draft).reduce((a, b) => a + b, 0);
  const anyEffort = data.rows.some(r => r.estimates.effort);
  const strategicSelect = (row: PriorityRow, className?: string) => <Select aria-label={`Strategic relevance for ${row.opportunity_id}`} value={row.estimates.strategic ?? ""} disabled={readOnly || saving === row.opportunity_id}
    onChange={e => saveInput(row, { strategic: (e.target.value || null) as Strategic | null })} className={cx("h-9 min-w-[7.5rem] text-sm", className)}>
    <option value="">Not rated</option>{(Object.keys(data.strategic_multipliers) as Strategic[]).map(s => <option key={s} value={s}>{s} (×{data.strategic_multipliers[s]})</option>)}</Select>;
  const effortSelect = (row: PriorityRow, className?: string) => <Select aria-label={`Effort for ${row.opportunity_id}`} value={row.estimates.effort ?? ""} disabled={readOnly || saving === row.opportunity_id}
    onChange={e => saveInput(row, { effort: (e.target.value || null) as Effort | null })} className={cx("h-9 min-w-[7.5rem] text-sm", className)}>
    <option value="">Not entered</option>{(Object.keys(data.effort_points) as Effort[]).map(s => <option key={s} value={s}>{s} ({data.effort_points[s]} pt)</option>)}</Select>;
  const note = (row: PriorityRow) => readOnly ? (row.estimates.note ? <p className="mt-5 text-sm text-ink-2">Note: {row.estimates.note}</p> : null) : <NoteEditor row={row} value={notes[row.opportunity_id] ?? row.estimates.note ?? ""} onChange={v => setNotes({ ...notes, [row.opportunity_id]: v })}
    onSave={() => saveInput(row, { note: notes[row.opportunity_id] ?? row.estimates.note ?? null })}/>;

  return <>
    <PageHeader title="Priorities" lede="A transparent, editable score. Measured parts come from the data; strategic relevance and effort are your estimates and only count once you enter them."
      actions={<Link href="/experiments" className={buttonClass("secondary", "md")}>Experiments<ArrowRight size={15}/></Link>}/>

    <div className="mb-8 space-y-3">
      <Notice title="How the score works"><p>{data.formula}</p><p className="mt-1">{data.interpretation}</p></Notice>
      {readOnly && <Notice tone="caution" title="Read-only public demo">Weights, estimates and notes are shown but can’t be changed here, so visitors can’t alter what others see. Run Gist locally to edit them.</Notice>}
      {data.stale_inputs > 0 && <Notice tone="caution" title={`${data.stale_inputs} saved estimate${data.stale_inputs === 1 ? "" : "s"} not applied`}>They belong to an older version of the data.</Notice>}
    </div>

    <details className="group mb-8 rounded-lg border border-line bg-surface">
      <summary className="flex min-h-12 cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
        <ChevronRight size={15} className="text-ink-3 transition-transform duration-fast group-open:rotate-90" aria-hidden="true"/>
        <span className="text-sm font-semibold">Scoring weights</span>
        {custom ? <Tag tone="accent">Custom</Tag> : <span className="text-xs text-ink-3">Defaults</span>}
        <span className="num ml-auto hidden text-xs text-ink-3 sm:inline">{data.parts.map(p => `${p.label} ${draftTotal ? Math.round(100 * draft[p.part] / draftTotal) : 0}%`).join(" · ")}</span>
      </summary>
      <div className="border-t border-line px-4 py-4 sm:px-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">{data.parts.map(p => <div key={p.part}>
          <label htmlFor={`w-${p.part}`} className="block text-xs font-medium text-ink-2" title={p.source}>{p.label}</label>
          <input id={`w-${p.part}`} type="number" inputMode="numeric" min={0} max={100} step={1} value={draft[p.part]} disabled={readOnly} onChange={e => setDraft({ ...draft, [p.part]: Math.max(0, Math.min(100, Math.round(Number(e.target.value) || 0))) })}
            className="num mt-1.5 block h-10 w-full rounded border border-control/70 bg-surface px-3 text-sm text-ink outline-none hover:border-control focus:border-accent"/>
          <span className="num mt-1 block text-2xs text-ink-3">{draftTotal ? Math.round(100 * draft[p.part] / draftTotal) : 0}% of score</span></div>)}</div>
        {draftTotal === 0 && <p role="alert" className="mt-3 text-xs font-medium text-signal">Set at least one weight above 0.</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" size="sm" disabled={readOnly || !weightsChanged || draftTotal === 0 || saving === "weights"} onClick={() => act("weights", () => apiSend("PUT", "/api/priorities/weights", { weights: draft }), "Weights saved. Ranks updated.")}>Save weights</Button>
          {weightsChanged && <Button size="sm" variant="ghost" onClick={() => setDraft(data.weights)}>Discard changes</Button>}
          <Button size="sm" disabled={readOnly || !custom} onClick={() => act("weights", () => apiSend("DELETE", "/api/priorities/weights"), "Weights reset to defaults.")}><RotateCcw size={13}/>Reset to defaults</Button>
        </div>
      </div>
    </details>

    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-semibold">Ranked opportunities <span className="num font-normal text-ink-3">· {rows.length}</span></h2>
      <Select aria-label="Order by" value={sort} onChange={e => setSort(e.target.value as SortKey)} className="h-9 w-auto text-sm">
        <option value="priority">Order: Priority</option><option value="per_effort" disabled={!anyEffort}>Order: Priority per effort point{anyEffort ? "" : " (enter effort first)"}</option></Select>
    </div>

    {/* Wide screens: an editable table */}
    <div className="hidden overflow-hidden rounded-lg border border-line bg-surface md:block">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line bg-sunken/50 text-xs text-ink-3">
          <tr><th className="py-2.5 pl-5 pr-2 font-medium">#</th><th className="pr-4 font-medium">Opportunity</th>
            <th className="pr-4 font-medium">Evidence <span className="block font-normal">measured</span></th>
            <th className="pr-3 font-medium">Strategic <span className="block font-normal">your estimate</span></th>
            <th className="pr-4 font-medium">Priority</th>
            <th className="pr-3 font-medium">Effort <span className="block font-normal">your estimate</span></th><th className="pr-5 text-right font-medium">Per effort pt</th></tr>
        </thead>
        <tbody className="divide-y divide-line">{rows.map(row => {
          const open = expanded === row.opportunity_id;
          return <Fragment key={row.opportunity_id}>
            <tr className={cx("align-middle transition-colors", open ? "bg-sunken/40" : "hover:bg-sunken/30", saving === row.opportunity_id && "opacity-60")}>
              <td className="num py-3 pl-5 pr-2 text-ink-3">{row.rank}</td>
              <td className="py-3 pr-4"><button type="button" aria-expanded={open} onClick={() => setExpanded(open ? null : row.opportunity_id)} className="flex items-start gap-1.5 text-left">
                <ChevronDown size={15} className={cx("mt-1 shrink-0 text-ink-3 transition-transform duration-fast", !open && "-rotate-90")} aria-hidden="true"/>
                <span><q className="voice line-clamp-2 text-[0.975rem] leading-6">{row.problem}</q><span className="text-xs text-ink-3"><Id>{row.opportunity_id}</Id> · {row.area}{row.estimates.note ? " · has note" : ""}</span></span></button></td>
              <td className="py-3 pr-4"><ScoreBar value={row.evidence_score}/></td>
              <td className="py-3 pr-3">{strategicSelect(row, "w-40")}</td>
              <td className="num py-3 pr-4 text-base font-semibold">{fmt(row.priority)}</td>
              <td className="py-3 pr-3">{effortSelect(row, "w-32")}</td>
              <td className="num py-3 pr-5 text-right text-ink-2">{row.priority_per_effort_point === null ? "—" : fmt(row.priority_per_effort_point)}</td>
            </tr>
            {open && <tr className="bg-sunken/40"><td colSpan={7} className="px-5 pb-6 pt-1"><div className="ml-8 rounded-md border border-line bg-surface p-5"><Breakdown row={row}/>{note(row)}</div></td></tr>}
          </Fragment>;
        })}</tbody>
      </table>
    </div>

    {/* Phones: stacked rows with the same controls */}
    <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface md:hidden">{rows.map(row => {
      const open = expanded === row.opportunity_id;
      return <li key={row.opportunity_id} className={cx("px-4 py-4", saving === row.opportunity_id && "opacity-60")}>
        <div className="flex items-start gap-3">
          <span className="num mt-0.5 w-5 shrink-0 text-sm text-ink-3">{row.rank}</span>
          <div className="min-w-0 flex-1">
            <q className="voice block text-[0.975rem] leading-6">{row.problem}</q>
            <p className="mt-0.5 text-xs text-ink-3"><Id>{row.opportunity_id}</Id> · {row.area}</p>
          </div>
          <div className="num text-right"><span className="block text-lg font-semibold leading-6">{fmt(row.priority)}</span><span className="text-2xs text-ink-3">priority</span></div>
        </div>
        <div className="ml-8 mt-3 grid grid-cols-2 gap-2">
          <div><span className="mb-1 block text-2xs text-ink-3">Strategic</span>{strategicSelect(row)}</div>
          <div><span className="mb-1 block text-2xs text-ink-3">Effort</span>{effortSelect(row)}</div>
        </div>
        <div className="ml-8 mt-2 flex items-center justify-between text-xs text-ink-2">
          <span>Evidence <span className="num font-medium text-ink">{fmt(row.evidence_score)}</span> · per effort pt <span className="num font-medium text-ink">{row.priority_per_effort_point === null ? "—" : fmt(row.priority_per_effort_point)}</span></span>
          <button type="button" aria-expanded={open} onClick={() => setExpanded(open ? null : row.opportunity_id)} className="flex h-9 items-center gap-1 font-medium text-accent">{open ? "Less" : "Breakdown"}<ChevronDown size={14} className={cx("transition-transform", open && "rotate-180")}/></button>
        </div>
        {open && <div className="ml-8 mt-3 border-t border-line pt-4"><Breakdown row={row}/>{note(row)}</div>}
      </li>;
    })}</ol>
    {flash}
  </>;
}
