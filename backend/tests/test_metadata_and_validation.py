"""Company metadata, fiscal calendars, and API input validation."""

from datetime import date

import pytest
from fastapi import HTTPException

from backend.api.routes import _require_valid_company_id
from backend.models.spec.historicals import Historicals
from backend.models.spec.metadata import ModelMetadata, parse_fiscal_year_end
from backend.models.spec.model_specification import ModelSpecification


@pytest.mark.parametrize(
    "label,expected",
    [
        ("March 31", (3, 31)),
        ("Sep 30", (9, 30)),
        ("December 31", (12, 31)),
        ("Jan 31", (1, 31)),
        ("Jun 30", (6, 30)),
    ],
)
def test_parse_fiscal_year_end(label, expected):
    assert parse_fiscal_year_end(label) == expected


@pytest.mark.parametrize("bad", ["", "March", "Foo 31", "March 3x"])
def test_parse_fiscal_year_end_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_fiscal_year_end(bad)


def _metadata(fye: str, company_id: str) -> ModelMetadata:
    return ModelMetadata(
        company_id=company_id,
        ticker="X",
        name="Testco",
        market="us" if company_id.endswith("_us") else "india",
        currency="USD" if company_id.endswith("_us") else "INR",
        units="millions" if company_id.endswith("_us") else "crores",
        fiscal_year_end=fye,
        shares_outstanding=10.0,
    )


def _historical_model(company_id: str):
    from backend.models.statements.historical_model import build_historical_model
    from backend.normalization.taxonomy.models import CanonicalDatapoint

    dp = CanonicalDatapoint(
        id=f"{company_id}-rev-FY24",
        company_id=company_id,
        canonical_key="canonical.is.revenue",
        metric_raw="revenue",
        period_label="FY24",
        period_end_date=date(2024, 3, 31),
        value=1000.0,
        currency="USD",
        units="millions",
        status="reported",
        source_datapoint_ids=["fixture"],
    )
    return build_historical_model([dp], target_periods=["FY24"])


def test_spec_period_ends_follow_company_fiscal_calendar():
    model = _historical_model("x_us")
    spec = ModelSpecification.from_historical_model(model, _metadata("Sep 30", "x_us"))
    item = next(i for i in spec.historicals.line_items if i.canonical_key == "canonical.is.revenue")
    assert item.period_end_date == date(2024, 9, 30)

    model_in = _historical_model("y_in")
    spec_in = ModelSpecification.from_historical_model(model_in, _metadata("March 31", "y_in"))
    item_in = next(i for i in spec_in.historicals.line_items if i.canonical_key == "canonical.is.revenue")
    assert item_in.period_end_date == date(2024, 3, 31)


def test_historicals_helper_removed():
    assert not hasattr(Historicals, "from_historical_model")


@pytest.mark.parametrize("bad", ["../etc", "..%2F..%2Fx", "infy-inf y", "A" * 80, "a;b"])
def test_api_rejects_malformed_company_ids(bad):
    with pytest.raises(HTTPException) as exc:
        _require_valid_company_id(bad)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("good", ["infy_infy", "aapl_us", "tcs_tcs"])
def test_api_accepts_wellformed_company_ids(good):
    assert _require_valid_company_id(good) == good
