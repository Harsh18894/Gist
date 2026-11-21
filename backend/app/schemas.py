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
    status: Literal["answered", "sources_only", "insufficient_evidence"]
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
