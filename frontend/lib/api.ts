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
  answer: string; status: "answered" | "partial" | "sources_only" | "insufficient_evidence";
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

/** An API failure. `status` is 0 when the API could not be reached at all. */
export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function fallbackMessage(status: number): string {
  if (status === 404) return "Not found.";
  if (status >= 500) return `The Gist API failed (HTTP ${status}). Check the API logs.`;
  return `The Gist API rejected the request (HTTP ${status}).`;
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, cache: "no-store" });
  } catch (error) {
    // Aborts are expected on navigation; pages ignore them by name.
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "unreachable", `Gist could not reach the API at ${base}. Check that it is running.`);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(response.status, payload?.error?.code || "http_error",
      payload?.error?.message || fallbackMessage(response.status));
  }
  return response.json() as Promise<T>;
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal });
}

export function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
}

// --- Phase 3.1 analytics (every number is computed in SQL by the API)
export interface AnalyticsScope { from_date: string | null; to_date: string | null; segment: string | null; product_area: string | null }
export interface DataQuality { unspecified_feature: number; unclear_category: number; multiple_issues: number; missing_segment: number; missing_area: number }
export interface AnalyticsSummary {
  scope: AnalyticsScope; feedback_count: number; ticket_count: number; negative_feedback_count: number;
  negative_share: number | null; date_range: { first: string | null; last: string | null };
  by_sentiment: Breakdown[]; by_category: Breakdown[]; by_segment: Breakdown[]; by_area: Breakdown[]; by_channel: Breakdown[];
  tickets_by_severity: Breakdown[]; tickets_by_status: Breakdown[]; data_quality: DataQuality;
}
export type TrendMetric = "feedback" | "negative_feedback" | "tickets";
export interface AnalyticsTrends { scope: AnalyticsScope; metric: TrendMetric; group_by: string | null; months: string[]; series: { name: string; counts: number[]; total: number }[]; total: number }
export interface ReleaseWindow { from_date: string; to_date: string; feedback: number; negative_feedback: number; tickets: number }
export interface ReleaseImpact { id: string; title: string; published: string; product_area: string | null; before: ReleaseWindow; after: ReleaseWindow }
export interface AnalyticsReleases { scope: AnalyticsScope; window_days: number; releases: ReleaseImpact[]; interpretation: string }
export interface AnalyticsRepeated {
  scope: AnalyticsScope; note: string;
  repeated_texts: { text: string; count: number; record_ids: string[] }[];
  top_negative_features: { feature: string; category: string; count: number }[];
}
export interface Ticket {
  id: string; timestamp: string; customer_segment: string; subscription_tier: string; product_area: string; subject: string;
  description: string; severity: string; issue_category: string; related_feature: string; status: string;
}
export const segments: Segment[] = ["Individual", "SMB", "Mid-market", "Enterprise"];
export const areas: Area[] = ["Onboarding", "Dashboard", "Integrations", "Billing", "Notifications", "Collaboration"];

/** Build a query string from non-empty values, so links and fetches share one filter shape. */
export function query(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  const text = params.toString();
  return text ? `?${text}` : "";
}
