from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from pulse.contracts import Extraction
from pulse.extract import rules
from pulse.extract.text import html_to_text
from tests.conftest import load_fixture


def test_html_to_text_unescapes_and_splits_paragraphs() -> None:
    raw = 'Acme | Engineer &#x2F; SRE<p>We use <a href="x">Rust</a> &amp; Go.<p>'
    assert html_to_text(raw) == "Acme | Engineer / SRE\nWe use Rust & Go."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$150k - $200k", (150_000, 200_000, "USD", "year")),
        ("$170k–$210k + equity", (170_000, 210_000, "USD", "year")),
        ("$150,000 — $190,000", (150_000, 190_000, "USD", "year")),
        ("$150-200k", (150_000, 200_000, "USD", "year")),
        ("€80k-€100k", (80_000, 100_000, "EUR", "year")),
        ("£65,000 to £85,000", (65_000, 85_000, "GBP", "year")),
        ("CA$120k - 150k", (120_000, 150_000, "CAD", "year")),
        ("Salary: $185k", (185_000, 185_000, "USD", "year")),
        ("$85/hr", (85, 85, "USD", "hour")),
        ("$60 - $90 per hour", (60, 90, "USD", "hour")),
    ],
)
def test_salary_formats(text: str, expected: tuple[int, int, str, str]) -> None:
    s = rules.salary(text)
    assert s is not None
    assert (s.low, s.high, s.currency, s.period) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We raised $40M from great investors",
        "$5k signing bonus",
        "0.1% - 0.5% equity",
        "401k matching",
        "No salary listed",
    ],
)
def test_salary_ignores_non_salary_amounts(text: str) -> None:
    assert rules.salary(text) is None


@given(lo=st.integers(20, 900), width=st.integers(0, 300))
def test_salary_range_property(lo: int, width: int) -> None:
    """Any '$Xk - $Yk' range in a plausible band parses to exactly those bounds."""
    hi = lo + width
    s = rules.salary(f"Pay: ${lo}k - ${hi}k")
    if hi <= 1500:
        assert s is not None
        assert (s.low, s.high) == (lo * 1000, hi * 1000)
    else:
        assert s is None


@pytest.mark.parametrize(
    ("header", "body", "expected"),
    [
        ("Acme | Engineer | REMOTE (US)", "", "remote"),
        ("Acme | Engineer | ONSITE or REMOTE", "", "remote"),
        ("Acme | Engineer | NYC | Hybrid", "", "hybrid"),
        ("Acme | Engineer | San Francisco | Onsite", "", "onsite"),
        ("Acme | Engineer | Austin | No remote", "", "onsite"),
        ("Acme | Engineer | Austin", "This role is fully remote.", "remote"),
        ("Acme | Engineer | Austin", "We love our office.", "unknown"),
    ],
)
def test_work_mode(header: str, body: str, expected: str) -> None:
    assert rules.work_mode(header, body) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Acme | Senior Software Engineers | Remote", ["engineering"]),
        ("Acme | Data Engineer | Remote", ["data_ml"]),
        ("Acme | Data Engineer, Backend Engineer", ["data_ml", "engineering"]),
        ("Acme | Product Manager | NYC", ["product"]),
        ("Acme | PM, Product Designer", ["product", "design"]),
        ("Acme | Account Executive", ["sales_marketing"]),
        ("Acme | We are a fun company", ["other"]),
    ],
)
def test_role_families(header: str, expected: list[str]) -> None:
    assert rules.role_families(header) == expected


def test_role_families_falls_back_to_body() -> None:
    assert rules.role_families("Acme builds robots.", "We're hiring a backend engineer.") == [
        "engineering"
    ]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Acme | Staff Engineer", "staff_plus"),
        ("Acme | Senior Engineer", "senior"),
        ("Acme | Engineering Manager", "lead_manager"),
        ("Acme | Summer Interns", "intern"),
        ("Acme | Engineer", "unknown"),
    ],
)
def test_seniority(header: str, expected: str) -> None:
    assert rules.seniority(header) == expected


def test_tech_avoids_common_false_positives() -> None:
    assert rules.tech("We use Java and Go, plus Postgres on AWS") == [
        "aws",
        "go",
        "java",
        "postgres",
    ]
    assert rules.tech("JavaScript only; go to our site") == ["javascript"]


def test_visa() -> None:
    assert rules.visa("We sponsor visas") is True
    assert rules.visa("Unfortunately we cannot sponsor visas") is False
    assert rules.visa("Great benefits") is None


def test_locations_header_abbreviations_only() -> None:
    assert rules.locations("Acme | SF or NYC", "") == ["New York", "San Francisco Bay Area"]
    # 'LA' in body prose must not count; full city names in the body do.
    assert rules.locations("Acme", "LA LA land. Offices in London.") == ["London"]


def test_company() -> None:
    assert rules.company("Acme Corp (YC W24) | Engineer") == "Acme Corp"
    assert rules.company("Acme — Engineer — Remote") == "Acme"


def test_every_fixture_post_satisfies_contract() -> None:
    """Integration over real recorded posts: extraction never violates the contract."""
    item = load_fixture("hn_item_49922569.json")
    for child in item["children"]:
        if child.get("text"):
            e = rules.extract(child["id"], child["text"])
            assert e.role_families
            if e.salary_min is not None:
                assert e.salary_max is not None
                assert e.salary_min <= e.salary_max


def test_contract_rejects_inverted_salary() -> None:
    with pytest.raises(ValidationError, match="salary_min > salary_max"):
        Extraction(
            post_id=1,
            extractor="rules",
            extractor_version="1",
            company="Acme",
            work_mode="remote",
            role_families=["engineering"],
            seniority="unknown",
            locations=[],
            salary_min=200_000,
            salary_max=100_000,
            salary_currency="USD",
            salary_period="year",
            tech=[],
        )
