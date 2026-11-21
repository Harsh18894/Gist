"""Conservative, explicit evidence gate shared by demo and generated answers.

This is a preflight policy, not a proof that a model's answer is grounded.
"""
import re
from dataclasses import dataclass

from .ingest import STOPWORDS
from .retrieval import Hit


@dataclass(frozen=True)
class EvidenceAssessment:
    sufficient: bool
    reason: str


def assess(question: str, hits: list[Hit]) -> EvidenceAssessment:
    if not hits:
        return EvidenceAssessment(False, "No sources matched the query and filters.")
    text = "\n".join(hit.content for hit in hits).lower()
    query = question.lower()
    handoff_question = bool(re.search(r"\b(verification|invitation|invited|invitees)\b", query))
    handoff_match = bool(re.search(r"\b(verification|verify|invitation|invited|invite|join|onboarding|checklist)\b", text))
    if handoff_question and not handoff_match:
        return EvidenceAssessment(False, "The retrieved access reports do not mention the requested handoff.")
    if re.search(r"\b(what caused|why did|root cause)\b", query) and not re.search(
        r"\b(because|due to|caused by|expired|misconfigured|wrong|incorrect|after changing|after we changed)\b", text
    ):
        return EvidenceAssessment(False, "The reports do not establish a cause.")
    # Exact quantities and personal attribution require an explicit statement in
    # the evidence. Related complaints and temporal proximity do not suffice.
    if re.search(r"\b(which|what|who)\s+(engineer|developer|person)\b", query):
        if not re.search(r"\b(engineer|developer)\s+[A-Z][a-z]+\b", "\n".join(hit.content for hit in hits)):
            return EvidenceAssessment(False, "No source identifies the responsible person.")
    if re.search(r"\b(revenue|arr|mrr)\b", query) and not re.search(
        r"(?:\$\s*\d[\d,.]*|\b(?:revenue|arr|mrr)\s+(?:was|of|is|grew by|increased by)\s+\d)", text
    ):
        return EvidenceAssessment(False, "No source states the requested revenue figure.")
    if re.search(r"\b(exact|total|global|how many)\b", query) and re.search(r"\b(alerts?|notifications?)\b", query):
        aggregate = any(re.search(r"\b(?:total|global|across all)\b.{0,45}\b\d+\s+(?:urgent\s+)?(?:alerts?|notifications?)\b|\b\d+\s+(?:urgent\s+)?(?:alerts?|notifications?)\b.{0,45}\b(?:total|global|across all)\b", hit.content.lower()) for hit in hits)
        if not aggregate:
            return EvidenceAssessment(False, "No source states an aggregate alert count.")
    # A loose OR-term retrieval match can be a hard negative. Require at least
    # two informative query terms in one source (one for a one-term query).
    generic = {"evidence", "find", "report", "reports", "case", "record", "records",
               "change", "changed", "people", "someone", "team", "teams", "customer",
               "customers", "after", "before", "show", "suggests"}
    terms = {term for term in re.findall(r"[a-z0-9]+", query)
             if len(term) >= 3 and term not in STOPWORDS and term not in generic}
    if not terms:
        return EvidenceAssessment(False, "The question does not identify a checkable fact.")
    required = min(2, len(terms))
    corpus_terms = set(re.findall(r"[a-z0-9]+", text))
    universal_contradiction = (bool(re.search(r"\b(everyone|all|every)\b", query)) and
                               len(terms & corpus_terms) >= required and
                               any(re.search(r"\b(like|loves|works well|calmer|helpful)\b", hit.content.lower()) for hit in hits) and
                               any(re.search(r"\b(worse|too many|muted|late|missed|overload)\b", hit.content.lower()) for hit in hits))
    if not (handoff_question and handoff_match) and not universal_contradiction and max(len(terms & set(re.findall(r"[a-z0-9]+", hit.content.lower()))) for hit in hits) < required:
        return EvidenceAssessment(False, "Retrieved sources do not cover enough of the question's specific terms.")
    return EvidenceAssessment(True, "Sources may contain relevant evidence; review them before drawing a conclusion.")


def unsupported_numbers(answer: str, cited_texts: list[str]) -> bool:
    """Reject unsupported numeric claims; source IDs and dates are excluded."""
    without_citations = re.sub(r"\[[^\]]+\]", "", answer)
    evidence = " ".join(cited_texts)
    numbers = re.findall(r"(?<![\w-])\$?\d[\d,.]*%?(?![\w-])", without_citations)
    return any(value not in evidence for value in numbers)
