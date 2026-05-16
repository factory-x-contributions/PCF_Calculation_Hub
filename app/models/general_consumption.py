from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

# Reserved factory-DB machine key for building-level (hall / site) idle totals —
# not a physical machine; kept separate from per-machine rows.
BUILDING_IDLE_MACHINE_ID = "building_idle"


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
    machine_id: str | None = Field(
        None,
        description="Machine identifier; omit together with machine_name for building-level idle (hall aggregate).",
    )
    energy_type: str = Field(..., description="e.g. electricity, compressed_air")
    machine_name: str | None = Field(
        None,
        description="Display name; omit together with machine_id for building-level idle (optional building_name).",
    )
    building_id: str = Field(..., description="Building or hall identifier.")
    building_name: str | None = Field(
        None,
        validation_alias=AliasChoices("building_name", "Building_name"),
        description="Optional building label from upstream; used as display name when machine fields are omitted.",
    )
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
    def _normalize_machine_vs_building_idle(self) -> "GeneralConsumptionPayload":
        """Resolve optional machine fields and building-hall idle payloads."""
        mid = (self.machine_id or "").strip() or None
        mname = (self.machine_name or "").strip() or None
        bname = (self.building_name or "").strip() or None
        bid = self.building_id.strip()

        if mid is None and mname is None:
            display = (bname or bid).strip() or bid
            return self.model_copy(
                update={
                    "machine_id": BUILDING_IDLE_MACHINE_ID,
                    "machine_name": display,
                }
            )
        if mid is None:
            return self.model_copy(update={"machine_id": mname, "machine_name": mname})
        if mname is None:
            return self.model_copy(update={"machine_name": mid})
        return self.model_copy(update={"machine_id": mid, "machine_name": mname})

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
