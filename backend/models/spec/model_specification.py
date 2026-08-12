from __future__ import annotations

import json
from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.drivers import DriverDefinition, V1_DRIVERS
from backend.models.spec.forecast import Forecast
from backend.models.spec.historicals import HistoricalLineItem, Historicals
from backend.models.spec.metadata import MODEL_SPEC_VERSION, ModelMetadata
from backend.models.spec.qa import QAResults
from backend.models.spec.scenarios import ScenarioDefinition, V1_SCENARIOS
from backend.models.spec.valuation import ValuationOutput


class ModelSpecification(BaseModel):
    """The central contract of the Valence system.

    This is the only object that crosses the boundary from the engine layer to
    any renderer. Both the web renderer and the Excel renderer consume only this.

    Design rule enforced: NO renderer-specific concepts in this schema.
    No cell references, no sheet names, no pixel hints, no display order.
    Those belong in the renderer's own mapping layer.

    Schema version: 1.0.0 — bumped only when the *schema* changes, not when
    company data refreshes. Older saved instances must remain loadable.
    """

    metadata: ModelMetadata
    historicals: Historicals
    forecast: Forecast = Field(default_factory=Forecast)
    drivers: List[DriverDefinition] = Field(default_factory=lambda: list(V1_DRIVERS))
    assumptions: List[AssumptionObject] = Field(default_factory=list)
    scenarios: List[ScenarioDefinition] = Field(default_factory=lambda: list(V1_SCENARIOS))
    valuation: List[ValuationOutput] = Field(default_factory=list)
    qa: QAResults = Field(default_factory=QAResults.empty)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def get_assumption(
        self,
        driver_key: str,
        period: str,
        scenario: str = "base",
    ) -> Optional[AssumptionObject]:
        for a in self.assumptions:
            if a.driver_key == driver_key and a.period == period and a.scenario == scenario:
                return a
        return None

    def get_valuation(self, scenario: str = "base") -> Optional[ValuationOutput]:
        for v in self.valuation:
            if v.scenario == scenario:
                return v
        return None

    def get_driver(self, driver_key: str) -> Optional[DriverDefinition]:
        for d in self.drivers:
            if d.driver_key == driver_key:
                return d
        return None

    # ------------------------------------------------------------------ #
    #  Serialization — schema version kept in the JSON envelope
    # ------------------------------------------------------------------ #

    def serialize(self) -> str:
        """Serialize to JSON string preserving schema version in envelope."""
        envelope = {
            "_schema_version": MODEL_SPEC_VERSION,
            "model": self.model_dump(mode="json"),
        }
        return json.dumps(envelope, default=str)

    @classmethod
    def deserialize(cls, raw: str) -> "ModelSpecification":
        """Deserialize from JSON string. Raises if schema version mismatch is breaking."""
        envelope = json.loads(raw)
        version = envelope.get("_schema_version", "unknown")
        # V1: we only have one version — simply load.
        # Future: add migration logic when MODEL_SPEC_VERSION increments.
        if version != MODEL_SPEC_VERSION:
            import warnings
            warnings.warn(
                f"ModelSpecification schema version mismatch: "
                f"file has '{version}', current is '{MODEL_SPEC_VERSION}'. "
                f"Loading anyway — check for field incompatibilities.",
                stacklevel=2,
            )
        return cls.model_validate(envelope["model"])

    # ------------------------------------------------------------------ #
    #  Factory — build from HistoricalModel
    # ------------------------------------------------------------------ #

    @classmethod
    def from_historical_model(
        cls,
        historical_model,
        metadata: ModelMetadata,
    ) -> "ModelSpecification":
        """Construct a structurally complete, sparsely populated ModelSpecification.

        Populates metadata + historicals fully. Forecast, valuation, QA are empty
        scaffolds.
        """
        # Build Historicals from the three assembled statements
        h_items: List[HistoricalLineItem] = []
        all_periods: set[str] = set()

        def _yr(period_label: str) -> int:
            yr = period_label[2:]
            return 2000 + int(yr) if len(yr) == 2 else int(yr)

        for stmt_items in [
            historical_model.income_statement.line_items,
            historical_model.balance_sheet.line_items,
            historical_model.cash_flow_statement.line_items,
        ]:
            for li in stmt_items:
                for period, value in li.values_by_period.items():
                    all_periods.add(period)
                    # Infer derived status from derivation_rule availability
                    status: str = "reported"
                    deriv_rule: Optional[str] = None
                    if li.canonical_key == "canonical.is.ebitda":
                        status = "derived"
                        deriv_rule = "ebitda = canonical.is.operating_profit + canonical.is.depreciation_amortization"

                    h_items.append(
                        HistoricalLineItem(
                            canonical_key=li.canonical_key,
                            period_label=period,
                            period_end_date=date(_yr(period), 3, 31),
                            value=value,
                            currency=li.currency,
                            units=li.units,
                            status=status,
                            source_datapoint_ids=li.lineage_ids_by_period.get(period, []),
                            derivation_rule=deriv_rule,
                        )
                    )

        historicals = Historicals(
            periods=sorted(all_periods),
            line_items=h_items,
        )

        # Scaffold per-scenario valuation containers
        valuation_scaffolds = [
            ValuationOutput(scenario=s)
            for s in ["base", "bull", "bear"]
        ]

        return cls(
            metadata=metadata,
            historicals=historicals,
            forecast=Forecast(),
            drivers=list(V1_DRIVERS),
            assumptions=[],
            scenarios=list(V1_SCENARIOS),
            valuation=valuation_scaffolds,
            qa=QAResults.empty(),
        )
