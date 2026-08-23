from backend.data.ingestion.us_live import YF_INCOME_MAP, YF_BALANCE_MAP, YF_CASHFLOW_MAP, YF_SHARE_MAP, _fx_to_usd
from backend.normalization.taxonomy.registry import get_canonical_mapping


def main():
    assert _fx_to_usd("USD") == 1.0
    assert _fx_to_usd("") == 1.0
    assert _fx_to_usd(None) == 1.0
    try:
        _fx_to_usd("zzzz")
    except ValueError:
        pass
    else:
        raise AssertionError("unresolvable currency must fail fast")

    for section in (YF_INCOME_MAP, YF_BALANCE_MAP, YF_CASHFLOW_MAP, YF_SHARE_MAP):
        for label, _cands in section:
            assert get_canonical_mapping(label) is not None, f"unmapped label {label!r}"
    print("us_live self-check ok")


if __name__ == "__main__":
    main()
