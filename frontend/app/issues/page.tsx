"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, ChevronRight, MousePointerClick } from "lucide-react";
import { apiGet, IssueMap, IssueRecord, SubTheme, SubThemeDetail } from "@/lib/api";
import { Dialog } from "@/components/dialog";
import { ErrorState, Loading } from "@/components/states";
import { buttonClass, cx, Id, Meta, Notice, PageHeader, SearchField, sentimentTone, Status, Tag, TrendMark, useMediaQuery } from "@/components/ui";

const shortDate = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const top = (counts: Record<string, number>) => Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "—";

function SubThemeRow({ sub, onOpen, selected }: { sub: SubTheme; onOpen: (id: string) => void; selected: boolean }) {
  return <li>
    <button type="button" onClick={() => onOpen(sub.id)} aria-current={selected ? "true" : undefined}
      className={cx("group relative grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-4 px-4 py-3 text-left transition-colors duration-fast sm:px-5",
        selected ? "bg-accent-soft/70" : "hover:bg-sunken/60")}>
      {selected && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-0.5 bg-accent"/>}
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink">{sub.label}</span>
        {sub.representatives[0] && <q className="voice mt-0.5 line-clamp-1 text-[0.95rem] text-ink-2">{sub.representatives[0].text}</q>}
        <Meta className="mt-1" items={[<TrendMark key="t" trend={sub.trend} recent={sub.recent_90_days} prior={sub.prior_90_days}/>, top(sub.areas), sub.secondary_members ? `+${sub.secondary_members} also mention` : null]}/>
      </span>
      <span className="flex items-center gap-1 self-center">
        <span className="num text-right"><span className="block text-base font-medium leading-5 text-ink">{sub.size}</span><span className="block text-2xs text-ink-3">records</span></span>
        <ChevronRight size={16} className="text-ink-3 transition-transform duration-fast group-hover:translate-x-0.5" aria-hidden="true"/>
      </span>
    </button>
  </li>;
}

function Counts({ title, counts }: { title: string; counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return <div><h4 className="eyebrow mb-2">{title}</h4>
    <ul className="space-y-1.5 text-sm">{Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
      <li key={k}><div className="flex justify-between gap-3"><span className="text-ink-2">{k}</span><span className="num font-medium text-ink">{v}</span></div>
        <div className="mt-0.5 h-1 rounded-r-[2px] bg-sunken" aria-hidden="true"><div className="h-1 rounded-r-[2px] bg-accent/70" style={{ width: `${(v / total) * 100}%` }}/></div></li>)}</ul></div>;
}

function DetailBody({ detail }: { detail: SubThemeDetail }) {
  return <>
    <div className="flex flex-wrap gap-1.5">{detail.top_terms.map(t => <Tag key={t} tone="accent">{t}</Tag>)}</div>
    <Meta className="mt-3" items={[`${detail.size} records${detail.secondary_members ? ` + ${detail.secondary_members} also mention` : ""}`, `${detail.distinct_texts} distinct wordings`, `${shortDate(detail.first_date)} – ${shortDate(detail.last_date)}`,
      <TrendMark key="t" trend={detail.trend} recent={detail.recent_90_days} prior={detail.prior_90_days}/>]}/>
    {detail.needs_triage && <Notice tone="caution" className="mt-4" title="Needs triage">These reports are vague and may not share one cause.</Notice>}
    <div className="mt-6 grid gap-6 sm:grid-cols-3"><Counts title="Segments" counts={detail.segments}/><Counts title="Product areas" counts={detail.areas}/><Counts title="Sentiment" counts={detail.sentiment}/></div>
    <h3 className="mt-8 text-sm font-semibold text-ink">Why these records are grouped</h3>
    <p className="mt-1 text-xs text-ink-2">Similarity to the group (0–1) and the group terms each record shares. “Also mentions” records belong mainly elsewhere but raise this problem in one sentence.</p>
    <ul className="mt-3 divide-y divide-line">{detail.members.map(m => <li key={m.id} className="py-3.5">
      <p className="voice text-[0.975rem] leading-6">{m.text}</p>
      <Meta className="mt-1.5" items={[<Id key="id">{m.id}</Id>, m.membership === "primary" ? <span key="m" className="font-medium text-accent">Member</span> : "Also mentions",
        <span key="s" className="num">similarity {m.similarity.toFixed(2)}</span>, m.date, m.segment, <Status key="se" tone={sentimentTone(m.sentiment)}>{m.sentiment}</Status>,
        m.shared_terms.length > 0 && `shares: ${m.shared_terms.join(", ")}`]}/>
    </li>)}</ul>
  </>;
}

export default function IssueExplorer() {
  const [data, setData] = useState<IssueMap | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [filter, setFilter] = useState("");
  const [detail, setDetail] = useState<SubThemeDetail | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState("");
  const [unclustered, setUnclustered] = useState<IssueRecord[] | null>(null);
  const wide = useMediaQuery("(min-width: 1024px)");
  const reload = useCallback(() => setAttempt(n => n + 1), []);
  const closeDetail = useCallback(() => { setDetail(null); setLoadingId(null); }, []);
  const closeUnclustered = useCallback(() => setUnclustered(null), []);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<IssueMap>("/api/issues", controller.signal).then(result => { setData(result); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  const subs = useMemo(() => new Map((data?.sub_themes ?? []).map(s => [s.id, s])), [data]);
  const needle = filter.trim().toLowerCase();
  const matches = (s: SubTheme) => !needle || `${s.label} ${s.top_terms.join(" ")} ${s.representatives.map(r => r.text).join(" ")}`.toLowerCase().includes(needle);
  const themes = (data?.themes ?? []).filter(t => !t.needs_triage)
    .map(t => ({ ...t, subs: t.sub_theme_ids.map(id => subs.get(id)!).filter(s => s && !s.needs_triage && matches(s)) }))
    .filter(t => t.subs.length);
  const triage = (data?.sub_themes ?? []).filter(s => s.needs_triage && matches(s));
  const open = async (id: string) => {
    setLoadingId(id); setDetailError("");
    try { const d = await apiGet<SubThemeDetail>(`/api/issues/${encodeURIComponent(id)}`); setDetail(d); }
    catch (e) { setDetailError(e instanceof Error ? e.message : "Could not load the sub-theme."); }
    finally { setLoadingId(null); }
  };
  const openUnclustered = async () => {
    try { setUnclustered(await apiGet<IssueRecord[]>("/api/issues/unclustered")); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load unclustered records."); }
  };
  // On wide screens the detail pane is always visible, so start with the largest issue open.
  useEffect(() => {
    if (!wide || !data || detail || loadingId) return;
    const first = data.themes.find(t => !t.needs_triage)?.sub_theme_ids[0];
    if (first) open(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide, data]);
  const selectedId = loadingId ?? detail?.id ?? null;
  const selectedSub = selectedId ? subs.get(selectedId) : undefined;

  const pane = <div className="min-w-0">
    {detailError ? <ErrorState title="Couldn’t open this issue" message={detailError} retry={() => selectedId && open(selectedId)}/>
      : loadingId ? <><p className="font-serif text-lg text-ink">{selectedSub?.label}</p><Loading className="mt-4" label="Loading records…" rows={6}/></>
      : detail ? <><p className="mb-1 text-xs text-ink-3">Sub-theme · <Id>{detail.id}</Id></p><h2 className="mb-4 font-serif text-lg leading-snug">{detail.label}</h2><DetailBody detail={detail}/></>
      : <div className="flex flex-col items-center px-6 py-20 text-center"><MousePointerClick size={22} className="text-ink-3" aria-hidden="true"/>
          <p className="mt-3 font-serif text-lg text-ink">Pick an issue</p><p className="mt-1 max-w-xs text-sm text-ink-2">Select a sub-theme to see its records, who raised it, and why they were grouped.</p></div>}
  </div>;

  return <>
    <PageHeader title="Issues" lede="Recurring problems found by grouping similar feedback. Sub-themes are specific, reliable groups; loose themes gather related ones for browsing."
      actions={<Link href="/opportunities" className={buttonClass("secondary", "md")}>Opportunities<ArrowRight size={15}/></Link>}/>

    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !data ? <Loading label="Grouping feedback…" rows={8}/> : <>
      <div className="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-2">
        <span><span className="num font-medium text-ink">{data.sub_themes.length}</span> sub-themes</span>
        <span><span className="num font-medium text-ink">{data.themes.length}</span> loose themes</span>
        <span><span className="num font-medium text-ink">{data.multi_issue_records}</span> records in two groups</span>
        <button type="button" onClick={openUnclustered} className="link text-sm"><span className="num font-medium">{data.unclustered_count}</span> not grouped — read them</button>
      </div>
      <details className="group mb-6 rounded-md border border-line bg-surface text-xs text-ink-2">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-4 py-2.5 font-medium text-ink [&::-webkit-details-marker]:hidden">
          <ChevronRight size={14} className="text-ink-3 transition-transform duration-fast group-open:rotate-90" aria-hidden="true"/>How grouping works, and how well it scored</summary>
        <div className="space-y-1.5 border-t border-line px-4 py-3 pl-10 leading-5"><p>{data.interpretation}</p><p>{data.evaluation}</p><p>Grouping method: {data.method}.</p></div>
      </details>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] xl:gap-10">
        <div className="min-w-0 space-y-6">
          <SearchField value={filter} onChange={setFilter} label="Filter sub-themes" placeholder="Filter by words, e.g. invoice, SSO, digest" className="max-w-md"/>
          {themes.length === 0 && triage.length === 0 && <p className="py-8 text-sm text-ink-2">No sub-themes match “{filter}”. Try a broader word.</p>}
          {themes.map(theme => <section key={theme.id} aria-labelledby={`${theme.id}-title`} className="overflow-hidden rounded-lg border border-line bg-surface">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line bg-sunken/40 px-4 py-2.5 sm:px-5">
              <h2 id={`${theme.id}-title`} className="text-sm font-semibold text-ink">{theme.label}</h2>
              <span className="text-2xs text-ink-3"><span className="num">{theme.size}</span> records · {Object.keys(theme.areas).join(", ")}</span>
            </div>
            <ul className="divide-y divide-line">{theme.subs.map(s => <SubThemeRow key={s.id} sub={s} onOpen={open} selected={selectedId === s.id}/>)}</ul>
          </section>)}
          {triage.length > 0 && <section aria-labelledby="triage-title" className="overflow-hidden rounded-lg border border-caution/30 bg-surface">
            <div className="border-b border-caution/20 bg-caution-soft px-4 py-2.5 sm:px-5">
              <h2 id="triage-title" className="text-sm font-semibold text-ink">Needs triage</h2>
              <p className="mt-0.5 text-xs text-ink-2">Groups of vague reports, mostly labelled “Unclear”. Similar to each other, but they don’t name a specific problem.</p>
            </div>
            <ul className="divide-y divide-line">{triage.map(s => <SubThemeRow key={s.id} sub={s} onOpen={open} selected={selectedId === s.id}/>)}</ul>
          </section>}
        </div>
        {wide && <aside aria-label="Issue detail" className="sticky top-8 max-h-[calc(100dvh-4rem)] overflow-y-auto rounded-lg border border-line bg-surface p-6">{pane}</aside>}
      </div>
    </>}

    {!wide && <Dialog open={Boolean(detail || loadingId || detailError)} onClose={() => { closeDetail(); setDetailError(""); }} kicker={detail ? <>Sub-theme · <Id>{detail.id}</Id></> : undefined} title={detail?.label ?? selectedSub?.label ?? "Issue"}>
      {detailError ? <ErrorState title="Couldn’t open this issue" message={detailError} retry={() => selectedId && open(selectedId)}/> : detail && !loadingId ? <DetailBody detail={detail}/> : <Loading label="Loading records…" rows={6}/>}
    </Dialog>}

    <Dialog open={Boolean(unclustered)} onClose={closeUnclustered} title={`Not grouped (${unclustered?.length ?? 0})`}>
      <p className="text-sm text-ink-2">These records weren’t similar enough to any group of three or more. Read them directly: some are one-off problems worth noticing.</p>
      <ul className="mt-4 divide-y divide-line">{unclustered?.map(r => <li key={r.id} className="py-3.5">
        <p className="voice text-[0.975rem] leading-6">{r.text}</p>
        <Meta className="mt-1.5" items={[<Id key="id">{r.id}</Id>, r.date, r.segment, r.area, r.category]}/></li>)}</ul>
    </Dialog>
  </>;
}
