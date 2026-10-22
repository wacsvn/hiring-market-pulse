"""Data contracts for every dataset that enters the pipeline.

Rows that fail a contract are never silently dropped: callers route them to a
quarantine table along with the reason, so bad upstream data shows up in counts
and tests instead of disappearing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorkMode = Literal["remote", "hybrid", "onsite", "unknown"]
RoleFamily = Literal[
    "engineering", "data_ml", "product", "design", "sales_marketing", "operations", "other"
]
Seniority = Literal["intern", "junior", "mid", "senior", "staff_plus", "lead_manager", "unknown"]
SalaryPeriod = Literal["year", "hour"]
JoltsMeasure = Literal["openings", "hires", "quits"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HiringThread(_Strict):
    thread_id: int
    title: str
    thread_month: date  # first day of the month the thread covers
    posted_at: datetime

    @field_validator("thread_month")
    @classmethod
    def _first_of_month(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError("thread_month must be the first day of a month")
        return v


class RawPost(_Strict):
    post_id: int
    thread_id: int
    thread_month: date
    posted_at: datetime
    author: str | None
    text_html: str = Field(min_length=1)

    @field_validator("posted_at")
    @classmethod
    def _not_in_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("posted_at must be timezone-aware")
        if v > datetime.now(UTC):
            raise ValueError("posted_at is in the future")
        return v


class JoltsObservation(_Strict):
    series_id: str
    measure: JoltsMeasure
    month: date
    value_thousands: float = Field(ge=0)
    is_preliminary: bool


class Extraction(_Strict):
    """Structured fields pulled from one job post, by any extractor."""

    post_id: int
    extractor: str  # e.g. "rules", "ollama:qwen2.5:7b", "anthropic:claude-haiku-5-5"
    extractor_version: str
    company: str | None
    work_mode: WorkMode
    role_families: list[RoleFamily] = Field(min_length=1)
    seniority: Seniority
    locations: list[str]
    salary_min: int | None = Field(default=None, gt=0)
    salary_max: int | None = Field(default=None, gt=0)
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    tech: list[str]
    visa_sponsorship: bool | None = None

    @model_validator(mode="after")
    def _salary_consistent(self) -> Extraction:
        lo, hi = self.salary_min, self.salary_max
        if (lo is None) != (hi is None):
            raise ValueError("salary_min and salary_max must both be set or both be null")
        if lo is not None and hi is not None:
            if lo > hi:
                raise ValueError("salary_min > salary_max")
            if self.salary_currency is None or self.salary_period is None:
                raise ValueError("salary requires currency and period")
        return self


class Rejected(_Strict):
    dataset: str
    record_key: str
    reason: str
    payload: str
