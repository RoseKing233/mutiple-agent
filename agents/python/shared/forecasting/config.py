"""Versioned course-project rules, not universal retail thresholds."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ENGINE_VERSION = "sales-forecast-v1"


class PerformanceRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    comparison_days: int = Field(default=28, ge=7, le=90)
    trend_percent: float = Field(default=15, gt=0, le=100, allow_inf_nan=False)
    trend_min_units: int = Field(default=5, ge=1, le=10000)
    slow_max_units: int = Field(default=3, ge=0, le=1000)
    no_sale_days: int = Field(default=14, ge=7, le=90)
    overstock_days: int = Field(default=60, ge=14, le=365)
    overstock_min_units: int = Field(default=5, ge=1, le=10000)


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    as_of: date = Field(default_factory=lambda: datetime.now(UTC).date() - timedelta(days=1))
    horizon: Literal[7, 14, 28] = 14
    category: str | None = Field(default=None, max_length=100)
    product_id: UUID | None = None
    rules: PerformanceRules = Field(default_factory=PerformanceRules)

    @model_validator(mode="after")
    def complete_days_only(self) -> "ForecastRequest":
        if self.as_of >= datetime.now(UTC).date():
            raise ValueError("Forecast cutoff must be a complete UTC day (yesterday or earlier)")
        if self.as_of < datetime.now(UTC).date() - timedelta(days=730):
            raise ValueError("Forecast cutoff must be within the last 730 days")
        return self
