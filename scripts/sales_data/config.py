"""Generator-only settings. Never expose profiles to a forecasting model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

GENERATOR_VERSION = "1.0.0"
PROFILES = ("stable", "growing", "declining", "weekly", "intermittent", "new", "low_stock")


@dataclass(frozen=True)
class SimulationConfig:
    days: int = 180
    end_date: date = field(default_factory=lambda: datetime.now(UTC).date() - timedelta(days=1))
    seed: int = 42

    def __post_init__(self) -> None:
        if not 60 <= self.days <= 730:
            raise ValueError("history days must be between 60 and 730")
        if not -(2**31) <= self.seed < 2**31:
            raise ValueError("seed must fit a signed 32-bit database integer")
        if self.end_date >= datetime.now(UTC).date():
            raise ValueError("end_date must be a complete UTC day before today")

    @property
    def start_date(self) -> date:
        return self.end_date - timedelta(days=self.days - 1)
