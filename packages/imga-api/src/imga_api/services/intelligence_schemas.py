"""Validated contracts shared by the company, PRD and retention surfaces."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=160)]
Code = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
ExternalId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^\s/\\]+$")]
DocumentKind = Literal["company", "prd"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class OrgUnit(Contract):
    id: Code
    name: ShortText
    parent_id: Code | None = None
    accountable_role: str = Field(default="", max_length=160)
    mandate: str = Field(default="", max_length=1000)


class ProcessStep(Contract):
    name: ShortText
    owner_unit_id: Code | None = None
    target_minutes: int | None = Field(default=None, ge=1, le=525600)


class CompanyProcess(Contract):
    id: Code
    name: ShortText
    owner_unit_id: Code | None = None
    category_codes: list[Code] = Field(default_factory=list, max_length=32)
    steps: list[ProcessStep] = Field(default_factory=list, max_length=30)
    resolution_target_minutes: int | None = Field(default=None, ge=1, le=525600)
    escalation: str = Field(default="", max_length=1000)
    source: str = Field(default="", max_length=500)
    verified_on: date | None = None


class CompanyContext(Contract):
    name: str = Field(default="", max_length=160)
    purpose: str = Field(default="", max_length=3000)
    business_model: str = Field(default="", max_length=1000)
    markets: list[Literal["SA", "AE", "TR", "other"]] = Field(default_factory=list, max_length=4)
    timezone: str = Field(default="Asia/Riyadh", max_length=64)
    analysis_profile: Literal["tr", "mena"] = "tr"
    report_language: Literal["tr", "en", "ar", "ur"] = "tr"
    units: list[OrgUnit] = Field(default_factory=list, max_length=100)
    processes: list[CompanyProcess] = Field(default_factory=list, max_length=100)
    constraints: str = Field(default="", max_length=3000)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Geçerli bir IANA saat dilimi gerekli.") from exc
        return value

    @model_validator(mode="after")
    def valid_structure(self) -> CompanyContext:
        units = {unit.id: unit for unit in self.units}
        if len(units) != len(self.units):
            raise ValueError("Birim kimlikleri benzersiz olmalı.")
        if len({p.id for p in self.processes}) != len(self.processes):
            raise ValueError("Süreç kimlikleri benzersiz olmalı.")
        for unit in self.units:
            seen = {unit.id}
            parent = unit.parent_id
            while parent is not None:
                if parent not in units or parent in seen:
                    raise ValueError("Organizasyon ağacı döngü veya bilinmeyen üst birim içeriyor.")
                seen.add(parent)
                parent = units[parent].parent_id
        for process in self.processes:
            owners = [process.owner_unit_id, *(step.owner_unit_id for step in process.steps)]
            if any(owner is not None and owner not in units for owner in owners):
                raise ValueError("Süreç sorumlusu mevcut bir organizasyon birimi olmalı.")
            if process.verified_on and process.verified_on > datetime.now(UTC).date():
                raise ValueError("Doğrulama tarihi gelecekte olamaz.")
        if len(self.model_dump_json().encode("utf-8")) > 65536:
            raise ValueError("Şirket bağlamı UTF-8 biçiminde 64 KiB sınırını aşamaz.")
        return self


class PrdSection(Contract):
    id: Code
    title: ShortText
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=12000)
    evidence: str = Field(default="", max_length=3000)
    acceptance: str = Field(default="", max_length=3000)
    owner: str = Field(default="", max_length=160)
    status: Literal["open", "draft", "confirmed", "not_applicable"] = "open"


class PrdDocument(Contract):
    title: ShortText = "İmga PRD"
    sections: list[PrdSection] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_sections(self) -> PrdDocument:
        if len({section.id for section in self.sections}) != len(self.sections):
            raise ValueError("Bölüm kimlikleri benzersiz olmalı.")
        for section in self.sections:
            if section.status == "confirmed" and not all(
                (section.answer, section.evidence, section.acceptance, section.owner)
            ):
                raise ValueError(
                    "Doğrulanan bölümde yanıt, kanıt, kabul ölçütü ve sorumlu gerekli."
                )
            if section.status == "not_applicable" and not section.answer:
                raise ValueError("Kapsam dışı bölüm için gerekçe gerekli.")
        return self


class DocumentUpdate(Contract):
    expected_revision: int = Field(ge=0)
    status: Literal["draft", "approved"] = "draft"
    content: CompanyContext | PrdDocument


class CustomerProfile(Contract):
    external_id: ExternalId
    name: ShortText
    segment: str = Field(default="", max_length=128)
    source: str = Field(min_length=1, max_length=160)
    observed_on: date
    lifecycle: Literal["active", "paused", "churned"] = "active"
    last_activity_on: date | None = None
    expected_activity_days: int | None = Field(default=None, ge=1, le=365)
    orders_current_30d: int | None = Field(default=None, ge=0, le=100000000)
    orders_previous_30d: int | None = Field(default=None, ge=0, le=100000000)
    usage_current_30d: int | None = Field(default=None, ge=0, le=100000000)
    usage_previous_30d: int | None = Field(default=None, ge=0, le=100000000)
    overdue_invoices: int | None = Field(default=None, ge=0, le=100000)
    cancellation_requested: bool | None = None
    renewal_on: date | None = None
    annual_revenue: Decimal | None = Field(default=None, ge=0, le=1000000000000)
    currency: Literal["SAR", "AED", "USD", "EUR", "TRY"] | None = None
    owner: str = Field(default="", max_length=160)
    next_action: str = Field(default="", max_length=2000)
    follow_up_on: date | None = None
    outcome: Literal["open", "contacted", "retained", "lost", "monitoring"] = "open"

    @model_validator(mode="after")
    def valid_observation(self) -> CustomerProfile:
        if self.observed_on > datetime.now(UTC).date():
            raise ValueError("Gözlem tarihi gelecekte olamaz.")
        if self.last_activity_on and self.last_activity_on > self.observed_on:
            raise ValueError("Son aktivite gözlem tarihinden sonra olamaz.")
        if self.annual_revenue is not None and self.currency is None:
            raise ValueError("Gelir için para birimi gerekli.")
        for current, previous in (
            (self.orders_current_30d, self.orders_previous_30d),
            (self.usage_current_30d, self.usage_previous_30d),
        ):
            if (current is None) != (previous is None):
                raise ValueError("Karşılaştırma için iki 30 günlük dönem birlikte gerekli.")
        return self


class CustomerUpdate(Contract):
    expected_revision: int = Field(ge=0)
    profile: CustomerProfile


class ReviewSignals(Contract):
    total: int = 0
    negative: int = 0
    sla_violations: int = 0
    low_nps: int = 0


class RiskSignal(Contract):
    code: str
    points: int
    evidence: str
    recommendation: str


class CustomerRisk(Contract):
    method: str = "rules-v1"
    as_of: date
    score: int | None
    band: Literal["unknown", "low", "watch", "high", "critical", "inactive"]
    data_status: Literal["sufficient", "insufficient", "stale", "inactive"]
    observed_domains: int
    signals: list[RiskSignal]
    missing: list[str]
    review_signals: ReviewSignals
