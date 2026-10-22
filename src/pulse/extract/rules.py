"""Deterministic regex/keyword extractor.

This is the baseline the LLM extractor has to beat in evals/. It is cheap, needs
no model, and is what the scheduled refresh uses for brand-new posts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pulse.contracts import Extraction, RoleFamily, SalaryPeriod, Seniority, WorkMode
from pulse.extract.text import header_line, html_to_text

VERSION = "2"

# --- work mode -----------------------------------------------------------------

# "2 days remote" / "remote Fridays" describe a hybrid schedule, not a remote option.
_REMOTE = re.compile(
    r"(?<!days )(?<!day )\bremote\b(?! (days?|fridays?|mondays?)\b)"
    r"|\bwork(ing)? from home\b|\bWFH\b",
    re.IGNORECASE,
)
_NOT_REMOTE = re.compile(r"\b(no|not)\s+remote\b|\bnon[- ]remote\b", re.IGNORECASE)
_HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE = re.compile(r"\b(on[- ]?site|in[- ]office|in[- ]person)\b", re.IGNORECASE)


def work_mode(header: str, body: str) -> WorkMode:
    """'remote' means remote work is allowed for at least one role, even if hybrid or onsite
    is also offered, so remote is checked before hybrid ("Hybrid or Remote (US)" -> remote).
    """
    for text in (header, body):
        if _REMOTE.search(text) and not _NOT_REMOTE.search(text):
            return "remote"
        if _HYBRID.search(text):
            return "hybrid"
        if _ONSITE.search(text) or _NOT_REMOTE.search(text):
            return "onsite"
    return "unknown"


# --- salary --------------------------------------------------------------------

_CURRENCY = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "usd": "USD",
    "eur": "EUR",
    "gbp": "GBP",
    "cad": "CAD",
    "c$": "CAD",
    "ca$": "CAD",
    "aud": "AUD",
    "a$": "AUD",
}
_SALARY = re.compile(
    r"""
    (?P<cur>C\$|CA\$|A\$|\$|€|£|\bUSD|\bEUR|\bGBP|\bCAD|\bAUD)\s*
    (?P<a>\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*(?P<ak>[kK])?
    (?:\s*(?:-|–|—|to)\s*(?:C\$|CA\$|A\$|\$|€|£)?\s*
       (?P<b>\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*(?P<bk>[kK])?)?
    (?P<tail>\s*(?:USD|EUR|GBP|CAD|AUD)\b)?
    (?P<per>\s*(?:/\s*(?:hr|hour)\b|per\s+hour|an\s+hour|/\s*h\b))?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ANNUAL_RANGE = (15_000, 1_500_000)
_HOURLY_RANGE = (10, 500)


@dataclass(frozen=True)
class Salary:
    low: int
    high: int
    currency: str
    period: SalaryPeriod


def _to_number(digits: str, k: str | None) -> float:
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", digits):
        value = float(re.sub(r"[,.]", "", digits))
    else:
        value = float(digits)
    return value * 1000 if k else value


def salary(text: str) -> Salary | None:
    """First plausible salary/rate in the text, or None.

    Handles '$150k - $200k', '$150,000–$190,000', '€80k', '120-160k USD', '$85/hr'.
    Implausible values (equity %, funding amounts like '$40M') are skipped.
    """
    for m in _SALARY.finditer(text):
        a = _to_number(m.group("a"), m.group("ak"))
        b = _to_number(m.group("b"), m.group("bk") or m.group("ak")) if m.group("b") else a
        # '$150-200k': the k on the upper bound applies to the lower bound too.
        if m.group("bk") and not m.group("ak") and a < 1000:
            a *= 1000
        # Skip funding/revenue amounts: '$40M', '$1.2B'.
        nxt = text[m.end() : m.end() + 2].strip()[:1]
        if nxt.lower() in {"m", "b"} and not m.group("b"):
            continue
        lo, hi = sorted((a, b))
        period: SalaryPeriod = "hour" if m.group("per") else "year"
        lo_ok, hi_ok = _HOURLY_RANGE if period == "hour" else _ANNUAL_RANGE
        if not (lo_ok <= lo and hi <= hi_ok):
            continue
        cur_raw = (m.group("tail") or m.group("cur")).strip().lower()
        currency = _CURRENCY.get(cur_raw, _CURRENCY.get(m.group("cur").lower(), "USD"))
        return Salary(int(lo), int(hi), currency, period)
    return None


# --- role family & seniority ---------------------------------------------------

_ROLE_PATTERNS: list[tuple[RoleFamily, re.Pattern[str]]] = [
    (
        "data_ml",
        re.compile(
            r"(?i:\b(data (scientist|engineer|analyst)s?|analytics|machine learning|AI engineers?|"
            r"research (scientist|engineer)s?)\b)|\b(ML|MLEs?)\b"
        ),
    ),
    (
        "engineering",
        re.compile(
            r"(?i:\b(engineer(s|ing)?|developers?|devops|programmers?|architects?|full[- ]?stack|"
            r"front[- ]?end|back[- ]?end|infrastructure|security|test)\b)|\b(SWEs?|SREs?|QA)\b"
        ),
    ),
    (
        "product",
        re.compile(
            r"(?i:\b(product managers?|product owners?|head of product|product lead)\b)|\bPMs?\b"
        ),
    ),
    ("design", re.compile(r"(?i:\b(designers?|product design|UX)\b)")),
    (
        "sales_marketing",
        re.compile(
            r"(?i:\b(sales|account executives?|marketing|growth|customer success)\b)"
            r"|\b(SDR|BDR)s?\b"
        ),
    ),
    (
        "operations",
        re.compile(
            r"(?i:\b(operations|recruit(er|ers|ing)|finance|people ops|chief of staff|"
            r"(customer )?support)\b)|\bHR\b"
        ),
    ),
]
_SOFTWARE = re.compile(
    r"\b(software|backend|back-end|frontend|front-end|full[- ]?stack|SWE|SRE|devops|platform)\b",
    re.IGNORECASE,
)


def _families_in(text: str) -> list[RoleFamily]:
    found = [family for family, pat in _ROLE_PATTERNS if pat.search(text)]
    # "Data Engineer" also matches the generic engineering pattern; keep the specific one.
    if "data_ml" in found and "engineering" in found and not _SOFTWARE.search(text):
        found.remove("engineering")
    return found


def role_families(header: str, body: str = "") -> list[RoleFamily]:
    """Role families named in the header; falls back to the opening of the body.

    Some posts open with a prose paragraph instead of the 'Company | Role | ...' header.
    """
    return _families_in(header) or _families_in(body[:400]) or ["other"]


_SENIORITY: list[tuple[Seniority, re.Pattern[str]]] = [
    ("intern", re.compile(r"\bintern(ship)?s?\b", re.IGNORECASE)),
    # "Member of Technical Staff" is a title convention, not a staff-level role.
    ("staff_plus", re.compile(r"\b(?<!technical )(staff|principal|distinguished)\b", re.I)),
    (
        "lead_manager",
        re.compile(r"\b(lead|manager|head of|director|VP|vice president|CTO)\b", re.IGNORECASE),
    ),
    ("senior", re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE)),
    ("mid", re.compile(r"\b(mid[- ]level|(engineer|developer|SWE) II|SDE ?2)\b", re.IGNORECASE)),
    ("junior", re.compile(r"\b(junior|jr\.?|entry[- ]level|new grad)\b", re.IGNORECASE)),
]
# In body prose a level word only counts as part of a job title: followed shortly by a role
# noun ("Senior Software Engineer") or itself a capitalised title word ("Commercial Manager").
_ROLE_NOUN = re.compile(
    r"^\W*(\w+\W+){0,3}?(engineers?|developers?|scientists?|designers?|managers?|analysts?|"
    r"architects?|SWEs?|SREs?|devops|marketers?|recruiters?|executives?)\b",
    re.IGNORECASE,
)
_TITLE_WORD = re.compile(r"Manager|Director|Head of|VP|CTO|Lead\b")


def _first_level(text: str, title_only: bool = False) -> Seniority:
    """The level named first in the text (so "Senior / Staff Engineer" -> senior)."""
    hits: list[tuple[int, Seniority]] = []
    for level, pat in _SENIORITY:
        for m in pat.finditer(text):
            if title_only and not (
                _ROLE_NOUN.match(text[m.end() : m.end() + 60]) or _TITLE_WORD.match(m.group(0))
            ):
                continue
            hits.append((m.start(), level))
    return min(hits)[1] if hits else "unknown"


def seniority(header: str, body: str = "") -> Seniority:
    """Level from the header; falls back to job titles in the opening of the body."""
    level = _first_level(header)
    if level == "unknown" and body:
        level = _first_level(body[:600], title_only=True)
    return level


# --- tech, locations, visa, company ----------------------------------------------

TECH: dict[str, re.Pattern[str]] = {
    name: re.compile(pat)
    for name, pat in {
        "python": r"(?i)\bpython\b",
        "typescript": r"(?i)\btypescript\b|\bTS\b",
        "javascript": r"(?i)\bjavascript\b|\bJS\b",
        # Case-sensitive: lowercase "go" is almost always the verb.
        "go": r"(?i:\bgolang\b)|\bGo\b(?! to\b)(?=[,/ )]|$)",
        "rust": r"(?i)\brust\b",
        "java": r"(?i)\bjava\b(?!script)",
        "kotlin": r"(?i)\bkotlin\b",
        "swift": r"(?i)\bswift\b",
        "c++": r"(?i)\bc\+\+",
        "c#": r"(?i)\bc#|\.net\b",
        "ruby": r"(?i)\bruby\b|\brails\b",
        "php": r"(?i)\bphp\b",
        "elixir": r"(?i)\belixir\b",
        "scala": r"(?i)\bscala\b",
        "react": r"(?i)\breact\b",
        "vue": r"(?i)\bvue(\.js)?\b",
        "node": r"(?i)\bnode(\.js|js)?\b",
        "django": r"(?i)\bdjango\b",
        "postgres": r"(?i)\bpostgres(ql)?\b",
        "aws": r"\bAWS\b",
        "gcp": r"\bGCP\b|(?i:google cloud)",
        "azure": r"(?i)\bazure\b",
        "kubernetes": r"(?i)\bkubernetes\b|\bk8s\b",
        "terraform": r"(?i)\bterraform\b",
        "spark": r"(?i)\b(apache )?spark\b",
        "kafka": r"(?i)\bkafka\b",
        "pytorch": r"(?i)\bpytorch\b",
        "llm": r"(?i)\bLLMs?\b|\bgenerative ai\b|\bgenai\b",
    }.items()
}

LOCATIONS: dict[str, re.Pattern[str]] = {
    name: re.compile(pat, re.IGNORECASE)
    for name, pat in {
        "San Francisco Bay Area": r"\b(san francisco|SF|bay area|palo alto|mountain view|"
        r"oakland|san jose|menlo park|sunnyvale|berkeley)\b",
        "New York": r"\b(new york|NYC|NY|brooklyn|manhattan)\b",
        "Seattle": r"\bseattle\b|\bbellevue\b",
        "Los Angeles": r"\b(los angeles|LA|santa monica)\b",
        "Boston": r"\bboston\b|\bcambridge, ma\b",
        "Austin": r"\baustin\b",
        "Chicago": r"\bchicago\b",
        "Denver/Boulder": r"\b(denver|boulder)\b",
        "Washington DC": r"\b(washington,? d\.?c\.?|DC)\b",
        "London": r"\blondon\b",
        "Berlin": r"\bberlin\b",
        "Amsterdam": r"\bamsterdam\b",
        "Toronto": r"\btoronto\b",
        "Paris": r"\bparis\b",
        "Bangalore": r"\b(bangalore|bengaluru)\b",
    }.items()
}
# Short abbreviations are only trusted in the header, where they are unambiguous.
_HEADER_ONLY = {"New York", "Los Angeles", "Washington DC", "San Francisco Bay Area"}

_NO_VISA = re.compile(
    r"\b(no|not|unable to|cannot|can't|don't|do not)\s+(offer\s+|provide\s+)?(visa )?"
    r"sponsor(ship)?\b|\bwithout sponsorship\b",
    re.IGNORECASE,
)
_VISA = re.compile(r"\bvisa\b|\bsponsor(ship)?\b|\bH-?1B\b", re.IGNORECASE)


def tech(text: str) -> list[str]:
    return sorted(name for name, pat in TECH.items() if pat.search(text))


def locations(header: str, body: str) -> list[str]:
    found = {name for name, pat in LOCATIONS.items() if pat.search(header)}
    found |= {
        name for name, pat in LOCATIONS.items() if name not in _HEADER_ONLY and pat.search(body)
    }
    return sorted(found)


def visa(text: str) -> bool | None:
    if _NO_VISA.search(text):
        return False
    if _VISA.search(text):
        return True
    return None


def company(header: str) -> str | None:
    first = re.split(r"\s+[|—–]\s+|\s+-\s+|\s*\|\s*", header, maxsplit=1)[0]
    first = re.sub(r"\s*\(.*?\)\s*$", "", first).strip(" :,")
    if not first or len(first) > 80:
        return None
    return first


# --- entry point ---------------------------------------------------------------


def extract(post_id: int, text_html: str) -> Extraction:
    text = html_to_text(text_html)
    head = header_line(text)
    body = text[len(head) :]
    sal = salary(text)
    return Extraction(
        post_id=post_id,
        extractor="rules",
        extractor_version=VERSION,
        company=company(head),
        work_mode=work_mode(head, body),
        role_families=role_families(head, body),
        seniority=seniority(head, body),
        locations=locations(head, body),
        salary_min=sal.low if sal else None,
        salary_max=sal.high if sal else None,
        salary_currency=sal.currency if sal else None,
        salary_period=sal.period if sal else None,
        tech=tech(text),
        visa_sponsorship=visa(text),
    )
