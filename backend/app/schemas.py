"""Public API response shapes."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Segment = Literal["Individual", "SMB", "Mid-market", "Enterprise"]
Area = Literal["Onboarding", "Dashboard", "Integrations", "Billing", "Notifications", "Collaboration"]
Category = Literal["Verification friction", "Integration failures", "Notification overload", "Slow performance", "Billing confusion", "Feature discoverability", "Account access", "Import mapping", "Alert delivery", "Template permissions", "Multiple issues", "Unclear", "Positive feedback"]


class Feedback(BaseModel):
    id: str
    timestamp: str
    customer_segment: Segment
    subscription_tier: str
    product_area: Area
    feedback_channel: str
    feedback_text: str
    sentiment: str
    issue_category: Category
    related_feature: str


class Page(BaseModel):
    items: list[Feedback]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pages: int = Field(ge=0)


class Breakdown(BaseModel):
    name: str
    count: int


class Stats(BaseModel):
    feedback_count: int
    support_ticket_count: int
    negative_feedback_count: int
    positive_feedback_count: int
    enterprise_feedback_count: int
    by_product_area: list[Breakdown]
    by_category: list[Breakdown]
    by_segment: list[Breakdown]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class RagFilters(BaseModel):
    segment: Segment | None = None
    product_area: Area | None = None
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def check_dates(self) -> "RagFilters":
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class SearchHit(BaseModel):
    source_id: str
    chunk_id: str
    title: str
    kind: str
    path: str
    source_date: str | None
    segment: str | None
    product_area: str | None
    snippet: str
    score: float
    keyword_rank: int | None
    semantic_rank: int | None


class AskRequest(RagFilters):
    question: str = Field(min_length=3, max_length=500)
    mode: Literal["demo", "openai"] = "demo"


class AskResponse(BaseModel):
    answer: str
    status: Literal["answered", "partial", "sources_only", "insufficient_evidence"]
    mode: Literal["demo", "openai"]
    citations: list[SearchHit]
    retrieved_sources: list[SearchHit] = Field(default_factory=list)
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class SourceDetail(BaseModel):
    id: str
    title: str
    kind: str
    path: str
    source_date: str | None
    segment: str | None
    product_area: str | None
    content: str


class UsageSummary(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    total_latency_ms: int
    project_committed_or_reserved_usd: float
    project_uncertain_requests: int
    project_allocation_usd: float
    project_input_tokens: int
    project_output_tokens: int


# --- Phase 3.1 analytics (all counts come from SQL; see app/analytics.py)
Sentiment = Literal["Positive", "Negative", "Mixed"]


class AnalyticsScope(BaseModel):
    from_date: str | None
    to_date: str | None
    segment: str | None
    product_area: str | None


class DateRange(BaseModel):
    first: str | None
    last: str | None


class DataQuality(BaseModel):
    unspecified_feature: int
    unclear_category: int
    multiple_issues: int
    missing_segment: int
    missing_area: int


class AnalyticsSummary(BaseModel):
    scope: AnalyticsScope
    feedback_count: int
    ticket_count: int
    negative_feedback_count: int
    negative_share: float | None
    date_range: DateRange
    by_sentiment: list[Breakdown]
    by_category: list[Breakdown]
    by_segment: list[Breakdown]
    by_area: list[Breakdown]
    by_channel: list[Breakdown]
    tickets_by_severity: list[Breakdown]
    tickets_by_status: list[Breakdown]
    data_quality: DataQuality


class TrendSeries(BaseModel):
    name: str
    counts: list[int]
    total: int


class AnalyticsTrends(BaseModel):
    scope: AnalyticsScope
    metric: Literal["feedback", "negative_feedback", "tickets"]
    group_by: Literal["category", "area", "segment"] | None
    months: list[str]
    series: list[TrendSeries]
    total: int


class ReleaseWindow(BaseModel):
    from_date: str
    to_date: str
    feedback: int
    negative_feedback: int
    tickets: int


class ReleaseImpact(BaseModel):
    id: str
    title: str
    published: str
    product_area: str | None
    before: ReleaseWindow
    after: ReleaseWindow


class AnalyticsReleases(BaseModel):
    scope: AnalyticsScope
    window_days: int
    releases: list[ReleaseImpact]
    interpretation: str


class RepeatedText(BaseModel):
    text: str
    count: int
    record_ids: list[str]


class NegativeFeature(BaseModel):
    feature: str
    category: str
    count: int


class AnalyticsRepeated(BaseModel):
    scope: AnalyticsScope
    repeated_texts: list[RepeatedText]
    top_negative_features: list[NegativeFeature]
    note: str


class Ticket(BaseModel):
    id: str
    timestamp: str
    customer_segment: str
    subscription_tier: str
    product_area: str
    subject: str
    description: str
    severity: str
    issue_category: str
    related_feature: str
    status: str


class TicketPage(BaseModel):
    items: list[Ticket]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    pages: int = Field(ge=0)
