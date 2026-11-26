"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, RagStatus, UsageSummary } from "@/lib/api";
import { ErrorState, Loading } from "@/components/states";
import { Notice, PageHeader, Section, Status } from "@/components/ui";

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return <dl className="divide-y divide-line text-sm">{rows.map(([k, v]) =>
    <div key={k} className="flex min-h-11 flex-wrap items-center justify-between gap-x-6 gap-y-1 py-2"><dt className="text-ink-2">{k}</dt><dd className="num min-w-0 break-all text-right text-ink">{v}</dd></div>)}</dl>;
}

export default function DataAndUsage() {
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(n => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([apiGet<RagStatus>("/api/rag/status", controller.signal), apiGet<UsageSummary>("/api/usage", controller.signal)])
      .then(([s, u]) => { setStatus(s); setUsage(u); setError(""); })
      .catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [attempt]);

  const used = usage ? usage.project_committed_or_reserved_usd : 0;
  const share = usage && usage.project_allocation_usd ? Math.min(1, used / usage.project_allocation_usd) : 0;

  return <div className="max-w-3xl">
    <PageHeader title="Data & usage" lede="What Gist is reading from, and what paid AI calls have cost so far. Read-only."/>
    {error ? <ErrorState message={error} retry={() => { setError(""); reload(); }}/> : !status || !usage ? <Loading label="Reading workspace status…" rows={6}/> : <div className="space-y-12">
      <Section id="dataset-title" title="Dataset" description="Pulse is a fictional SaaS company. Every record in Gist is synthetic.">
        <Rows rows={[
          ["Dataset", status.dataset_version === "unseeded" ? <Status tone="caution">Not seeded</Status> : `Pulse ${status.dataset_version}`],
          ["Indexed sources", status.sources], ["Searchable chunks", status.chunks], ["Stored embedding vectors", status.openai_vectors],
          ["Source fingerprint", <span key="sha" className="font-mono text-2xs text-ink-2">{status.source_sha256 ?? "—"}</span>],
        ]}/>
        {status.dataset_version === "unseeded" && <Notice tone="caution" className="mt-4" title="No data indexed">Seed the database from the repository root, e.g. <code className="font-mono">.venv/bin/python backend/scripts/seed.py --dataset v1</code>.</Notice>}
      </Section>

      <Section id="ai-title" title="AI answers" description="Find sources is always local and free. Writing answers uses the paid OpenAI API and must be enabled by the operator.">
        <Rows rows={[
          ["Paid answers", status.paid_api_enabled ? <Status tone="accent">Enabled</Status> : <Status>Switched off</Status>],
          ["Answer model", <span key="m" className="font-mono text-xs">{status.llm_model}</span>],
        ]}/>
      </Section>

      <Section id="spend-title" title="Paid API spend" description="Project-wide, from the shared reservation ledger. Includes reserved but unconfirmed requests.">
        <div className="mb-5">
          <p className="num font-serif text-[2rem] leading-10">${used.toFixed(4)} <span className="font-sans text-sm text-ink-3">of ${usage.project_allocation_usd.toFixed(2)} allocation</span></p>
          <div className="mt-2 h-2 max-w-md rounded-r-[4px] bg-sunken" role="meter" aria-valuemin={0} aria-valuemax={usage.project_allocation_usd} aria-valuenow={used} aria-label="Allocation used">
            <div className={`h-2 rounded-r-[4px] ${share > 0.8 ? "bg-signal" : "bg-accent"}`} style={{ width: `${Math.max(share * 100, used > 0 ? 1 : 0)}%` }}/></div>
          <p className="num mt-1 text-2xs text-ink-3">{Math.round(share * 100)}% used</p>
        </div>
        <Rows rows={[
          ["Recorded calls", usage.calls], ["Input tokens", usage.project_input_tokens.toLocaleString()], ["Output tokens", usage.project_output_tokens.toLocaleString()],
          ["Uncertain requests", usage.project_uncertain_requests > 0 ? <Status tone="caution">{usage.project_uncertain_requests} to reconcile with billing</Status> : "0"],
          ["Total model latency", `${(usage.total_latency_ms / 1000).toFixed(1)} s`],
        ]}/>
      </Section>

      <p className="text-xs text-ink-3">Data import, model choice and usage controls will appear here when those capabilities exist.</p>
    </div>}
  </div>;
}
