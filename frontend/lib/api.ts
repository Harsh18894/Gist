export type Segment = "Individual" | "SMB" | "Mid-market" | "Enterprise";
export type Area = "Onboarding" | "Dashboard" | "Integrations" | "Billing" | "Notifications" | "Collaboration";
export type Category = "Verification friction" | "Integration failures" | "Notification overload" | "Slow performance" | "Billing confusion" | "Feature discoverability" | "Account access" | "Import mapping" | "Alert delivery" | "Template permissions" | "Multiple issues" | "Unclear" | "Positive feedback";

export interface Feedback {
  id: string; timestamp: string; customer_segment: Segment; subscription_tier: string;
  product_area: Area; feedback_channel: string; feedback_text: string;
  sentiment: "Positive" | "Negative" | "Mixed"; issue_category: Category; related_feature: string;
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
export interface Breakdown { name: string; count: number }
export interface Stats {
  feedback_count: number; support_ticket_count: number; negative_feedback_count: number;
  positive_feedback_count: number; enterprise_feedback_count: number;
  by_product_area: Breakdown[]; by_category: Breakdown[]; by_segment: Breakdown[];
}
export interface SearchHit {
  source_id: string; chunk_id: string; title: string; kind: string; path: string;
  source_date: string | null; segment: string | null; product_area: string | null;
  snippet: string; score: number; keyword_rank: number | null; semantic_rank: number | null;
}
export interface AskResult {
  answer: string; status: "answered" | "sources_only" | "insufficient_evidence";
  mode: "demo" | "openai"; citations: SearchHit[]; retrieved_sources: SearchHit[]; latency_ms: number;
  input_tokens: number; output_tokens: number; estimated_cost_usd: number;
}
export interface SourceDetail {
  id: string; title: string; kind: string; path: string; source_date: string | null;
  segment: string | null; product_area: string | null; content: string;
}
export interface RagStatus { dataset_version: "v1" | "v2" | "unseeded"; source_sha256: string | null; sources: number; chunks: number; openai_vectors: number; paid_api_enabled: boolean; llm_model: string }
export interface UsageSummary { calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number; total_latency_ms: number; project_committed_or_reserved_usd: number; project_uncertain_requests: number; project_allocation_usd: number; project_input_tokens: number; project_output_tokens: number }

const base = process.env.NEXT_PUBLIC_GIST_API_URL || "http://localhost:8000";

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, { signal, cache: "no-store" });
  if (!response.ok) {
    throw new Error(response.status === 404 ? "Record not found." : "Gist could not load data. Check that the API is running.");
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body), signal, cache: "no-store",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
    throw new Error(payload?.error?.message || "Gist could not answer. Check that the API is running.");
  }
  return response.json() as Promise<T>;
}
