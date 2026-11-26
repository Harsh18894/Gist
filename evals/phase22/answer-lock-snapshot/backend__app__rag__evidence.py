"""Conservative, explicit evidence gate shared by demo and generated answers.

This is a preflight policy, not a proof that a model's answer is grounded.

Policy: when a question demands a specific kind of fact (a responsible person,
a money amount, an aggregate count, a cause) at least one retrieved source must
state that kind of fact. When a question names a product process (access
handoff, sync, import, notifications) the evidence must be about that process.
Otherwise the sources must cover the question's informative terms.

The rules are written as general fact types with documented vocabularies.
`backend/tests/test_evidence_gate.py` holds hand-written cases that are
independent of the benchmark; extend those rather than fitting benchmark wording.
"""
import re
from dataclasses import dataclass

from .ingest import STOPWORDS
from .retrieval import Hit


@dataclass(frozen=True)
class EvidenceAssessment:
    sufficient: bool
    reason: str
    rule: str = "sufficient"


@dataclass(frozen=True)
class FactRule:
    """A question demanding this fact type needs one source that states it."""
    name: str
    question: re.Pattern[str]
    evidence: re.Pattern[str]
    reason: str
    case_sensitive_evidence: bool = False


_AGGREGATE = r"(?:in total|total|overall|altogether|in all|across all|globally|global)"
_NUMBER = r"(?<![\d-])\d[\d,]*(?![\d-])"  # excludes ISO dates such as 2025-04-05

FACT_RULES: tuple[FactRule, ...] = (
    FactRule(
        "cause",
        re.compile(r"\b(?:what caused|what causes|root cause|reasons? for|what led to|"
                   r"why (?:did|do|does|is|are|was|were|has|have))\b"),
        re.compile(r"\b(?:because|due to|caused by|as a result of|led to|resulted from|result of|"
                   r"expired|misconfigured|wrong|incorrect|after changing|after we changed)\b"),
        "The reports do not establish a cause."),
    FactRule(
        "person",
        re.compile(r"\b(?:which|what|who)\s+(?:engineer|developer|person|teammate|employee|contractor|"
                   r"team member|staff member)s?\b|"
                   r"\bwho\b.*\b(?:caused|causes|broke|introduced|shipped|wrote|merged|is responsible|"
                   r"was responsible|approved|approves|signed off|authorized|decided)\b|"
                   r"\b(?:responsible for|to blame|at fault)\b"),
        # A named individual in a role, or a capitalized name (not sentence-initial) as the actor.
        re.compile(r"\b(?i:engineer|developer|teammate|employee|contractor)\s+[A-Z][a-z]+|"
                   r"(?<=[a-z,;:] )[A-Z][a-z]+\s+(?:introduced|caused|broke|shipped|wrote|merged|owns|owned|approved|authorized|decided|signed off)\b"),
        "No source identifies the responsible person.",
        case_sensitive_evidence=True),
    FactRule(
        "money",
        re.compile(r"\b(?:revenue|arr|mrr|income|earnings|profits?)\b|"
                   r"\bhow much\b.*\b(?:money|make|made|earn|earned|generate|generated|bring in|brought in)\b|"
                   r"\b(?:what|how much)\s+(?:were|was|are|is)\s+(?:the\s+)?sales\b|"
                   r"\bsales\s+(?:revenue|figures?|numbers?|totals?)\b"),
        re.compile(r"[$€£]\s*\d|\b\d[\d,.]*\s*(?:usd|dollars|euros|pounds)\b|"
                   r"\b(?:revenue|arr|mrr|income|sales|earnings)\s+(?:was|were|of|is|reached|totaled|"
                   r"grew by|increased by|fell by|dropped by)\s+[$€£]?\d"),
        "No source states the requested money amount."),
    FactRule(
        "count",
        re.compile(rf"\b(?:exact|total|global|overall|complete|full|entire)\s+(?:count|number|amount|tally)\b|"
                   rf"\bhow many\b.*\b{_AGGREGATE}\b|"
                   r"\bhow many\s+(?:\w+\s+){0,2}(?:customers|users|teams|accounts|workspaces|admins|people|"
                   r"reports|tickets|complaints|alerts|notifications|failures|errors|incidents|records)\b"),
        re.compile(rf"\b{_AGGREGATE}\b.{{0,45}}{_NUMBER}|{_NUMBER}.{{0,45}}\b{_AGGREGATE}\b"),
        "No source states an aggregate count; retrieved records are a sample, not a total."),
)

# Product processes. A question naming one needs evidence about the same process;
# members of a group count as covering each other for term coverage.
PROCESS_SYNONYMS: dict[str, frozenset[str]] = {
    "access": frozenset({"verification", "verify", "verified", "verifying", "invitation", "invitations",
                         "invite", "invites", "invited", "invitee", "invitees", "join", "joined", "joining"}),
    "sync": frozenset({"sync", "synced", "syncing", "connector", "connectors", "integration", "integrations"}),
    "import": frozenset({"import", "imports", "imported", "importing", "csv", "upload", "uploads",
                         "uploaded", "mapping"}),
    "notifications": frozenset({"alert", "alerts", "notification", "notifications", "digest", "digests"}),
}
_PROCESS_OF = {term: group for group, terms in PROCESS_SYNONYMS.items() for term in terms}

# A universal claim ("did everyone…") is answered by mixed evidence spread across sources.
UNIVERSAL = re.compile(r"\b(?:everyone|everybody|all|every|nobody|no one|always)\b")
POSITIVE = re.compile(r"\b(?:like|likes|liked|love|loves|loved|helpful|works well|calmer|better|great|easier|"
                      r"faster|appreciate|appreciated|prefer|prefers|enjoy|happy)\b")
NEGATIVE = re.compile(r"\b(?:worse|too many|muted|mute|late|missed|overload|noisy|annoying|hate|hates|hated|"
                      r"slower|broken|frustrating|frustrated|confusing|turned (?:it )?off|unhappy)\b")

GENERIC = {"evidence", "find", "report", "reports", "case", "record", "records",
           "change", "changed", "people", "someone", "team", "teams", "customer",
           "customers", "after", "before", "show", "suggests"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _covered(terms: set[str], words: set[str]) -> int:
    """Count question terms present in `words`, letting process synonyms stand in."""
    return sum(1 for term in terms
               if term in words or (term in _PROCESS_OF and PROCESS_SYNONYMS[_PROCESS_OF[term]] & words))


def assess(question: str, hits: list[Hit], *, fact_rules_only: bool = False) -> EvidenceAssessment:
    """Gate retrieved evidence before an answer.

    `fact_rules_only` (paid mode) applies only the fact-type rules. A model then
    judges topical fit and must declare a status and cite sources; the lexical
    process and coverage rules stay for the no-model demo.
    """
    if not hits:
        return EvidenceAssessment(False, "No sources matched the query and filters.", "no_hits")
    query = question.lower()
    contents = [hit.content for hit in hits]
    lowered = [content.lower() for content in contents]
    hit_words = [_words(content) for content in contents]
    terms = {term for term in re.findall(r"[a-z0-9]+", query)
             if len(term) >= 3 and term not in STOPWORDS and term not in GENERIC}

    for group in (() if fact_rules_only else sorted({_PROCESS_OF[term] for term in terms if term in _PROCESS_OF})):
        if not any(PROCESS_SYNONYMS[group] & words for words in hit_words):
            return EvidenceAssessment(False, f"No source is about the requested {group} process.", "process")

    for rule in FACT_RULES:
        if rule.question.search(query):
            texts = contents if rule.case_sensitive_evidence else lowered
            if not any(rule.evidence.search(text) for text in texts):
                return EvidenceAssessment(False, rule.reason, rule.name)

    if fact_rules_only:
        return EvidenceAssessment(True, "No fact-type rule blocks this question; the model must cite supporting sources.")
    if not terms:
        return EvidenceAssessment(False, "The question does not identify a checkable fact.", "no_terms")
    # A loose OR-term retrieval match can be a hard negative. Require at least
    # two informative query terms in one source (one for a one-term query).
    required = min(2, len(terms))
    if max(_covered(terms, words) for words in hit_words) >= required:
        return EvidenceAssessment(True, "Sources may contain relevant evidence; review them before drawing a conclusion.")
    mixed = any(POSITIVE.search(text) for text in lowered) and any(NEGATIVE.search(text) for text in lowered)
    if UNIVERSAL.search(query) and mixed and _covered(terms, set().union(*hit_words)) >= required:
        return EvidenceAssessment(True, "Sources show mixed reactions to a universal claim; review them before drawing a conclusion.")
    return EvidenceAssessment(False, "Retrieved sources do not cover enough of the question's specific terms.", "coverage")


def unsupported_numbers(answer: str, cited_texts: list[str]) -> bool:
    """Reject unsupported numeric claims; source IDs and dates are excluded."""
    without_citations = re.sub(r"\[[^\]]+\]", "", answer)
    evidence = " ".join(cited_texts)
    numbers = re.findall(r"(?<![\w-])\$?\d[\d,.]*%?(?![\w-])", without_citations)
    return any(value not in evidence for value in numbers)
