from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class GeneralConsumptionPayload(BaseModel):
    """General idle consumption for a machine in a building (factory monitoring)."""

    model_config = ConfigDict(populate_by_name=True)

    total_time: float = Field(
        ...,
        validation_alias=AliasChoices("total_time", "Total_duration", "total_duration"),
        description="Reporting window duration in minutes (may be fractional).",
    )
    total_idle_time: float = Field(
        ...,
        validation_alias=AliasChoices("total_idle_time", "Total_idle_time"),
        description="Minutes the machine was idle during the reporting window. "
        "If there was no production between two submissions, this equals total_time.",
    )
    work_orders_duration: dict[str, float] | None = Field(
        None,
        description="Minutes per work order id while an operation was running during the window.",
    )
    machine_id: str = Field(..., description="Machine identifier (same as machine_name for now).")
    energy_type: str = Field(..., description="e.g. electricity, compressed_air")
    machine_name: str = Field(..., description="Display name of the machine.")
    building_id: str = Field(..., description="Building or hall identifier.")
    idle_consumption_total: float = Field(
        ...,
        description="Total idle energy consumption in kWh over the reporting window.",
    )
    idle_consumption_rate: float | None = Field(
        None,
        description="Idle consumption rate in kWh per hour. If omitted, computed as "
        "idle_consumption_total / (total_time / 60).",
    )
    prod_consumption_total: float = Field(
        0.0,
        validation_alias=AliasChoices("prod_consumption_total", "Prod_consumption_total"),
        description="Total energy consumption in kWh while the operation is running (production). "
        "Omit or use 0 when not applicable (legacy clients).",
    )
    prod_consumption_rate: float | None = Field(
        None,
        validation_alias=AliasChoices("prod_consumption_rate", "Prod_consumption_rate"),
        description="Production consumption rate in kWh per hour. If omitted, computed as "
        "prod_consumption_total / (total_time / 60).",
    )
    publication_datetime: datetime | None = Field(
        None,
        validation_alias=AliasChoices("publication_datetime", "Publication_datetime"),
        description="When this measurement was published (ISO 8601, e.g. 2026-03-26T14:30:00.000Z).",
    )

    @model_validator(mode="after")
    def _compute_consumption_rates(self) -> "GeneralConsumptionPayload":
        td = self.total_time
        hours = td / 60.0 if td and td > 0 else 0.0
        updates: dict[str, float] = {}
        if self.idle_consumption_rate is None:
            updates["idle_consumption_rate"] = (
                self.idle_consumption_total / hours if hours > 0 else 0.0
            )
        if self.prod_consumption_rate is None:
            updates["prod_consumption_rate"] = (
                self.prod_consumption_total / hours if hours > 0 else 0.0
            )
        if not updates:
            return self
        return self.model_copy(update=updates)
