"""Runtime configuration of the testbed, including the trouble it injects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Layout = Literal["a", "b"]


class Chaos(BaseModel):
    """What MiniERP does to make automation hard. Rates are probabilities (0..1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    layout: Layout = Field(default="a", description="'b' renames labels, ids and buttons.")
    drift: int | None = Field(
        default=None, description="A seed: the layout changed as an update would (the lab)."
    )
    drift_rate: float = Field(
        default=0.5, ge=0, le=1, description="With drift: how likely each change is."
    )
    session_popup_rate: float = Field(default=0.0, ge=0, le=1, description="Per page view.")
    session_popup_delay_ms: tuple[int, int] = (400, 1500)
    slow_load_max_ms: int = Field(default=0, ge=0, le=10_000, description="Spinner 0..max ms.")
    lying_banner_rate: float = Field(
        default=0.0, ge=0, le=1, description="Per save: show 'saved' but store nothing."
    )
    save_error_rate: float = Field(
        default=0.0, ge=0, le=1, description="Per save: HTTP 500 before anything is stored."
    )
    lost_response_rate: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Per save: the price is stored, then the answer is lost (HTTP 502).",
    )
    slow_save_max_ms: int = Field(
        default=0, ge=0, le=30_000, description="Per save: 0..max ms before storing and answering."
    )
    read_lag_ms: int = Field(
        default=0, ge=0, le=30_000, description="The read API sees a new version only this late."
    )
    read_error_rate: float = Field(
        default=0.0, ge=0, le=1, description="Per call of the read API (/api/prices): HTTP 503."
    )

    @model_validator(mode="after")
    def _delay_range(self) -> Self:
        low, high = self.session_popup_delay_ms
        if low < 0 or high < low:
            raise ValueError(
                "session_popup_delay_ms must be a range (low, high) with 0 <= low <= high"
            )
        return self


CHAOS_PRESETS: dict[str, Chaos] = {
    "off": Chaos(),
    "default": Chaos(session_popup_rate=0.15, slow_load_max_ms=3000, lying_banner_rate=0.05),
    "heavy": Chaos(session_popup_rate=0.4, slow_load_max_ms=3000, lying_banner_rate=0.2),
    "faults": Chaos(
        session_popup_rate=0.1,
        slow_load_max_ms=800,
        lying_banner_rate=0.1,
        save_error_rate=0.1,
        lost_response_rate=0.1,
        slow_save_max_ms=1500,
        read_lag_ms=600,
        read_error_rate=0.1,
    ),
}


@dataclass(frozen=True)
class Settings:
    seed: int = 42
    chaos: Chaos = field(default_factory=Chaos)
    today: date | None = None
    """None means the real date; tests pin it so statuses are stable."""
    confirm_threshold_pct: Decimal = Decimal(20)
    username: str = "demo"
    password: str = "demo"
