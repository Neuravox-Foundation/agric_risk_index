"""DAVARS Pipeline Tests — Minimum required tests."""
import os
import sys
import pytest
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import (
    DATA_PROCESSED, REPORTS_DIR, BULLETINS_DIR,
    PILOT_DISTRICTS, PRICE_DISTRICTS, NO_PRICE_DISTRICTS,
    MIN_MONTHS_FOR_CVI, HIGH_RISK_PERCENTILE
)


@pytest.fixture(scope="module")
def coverage_report():
    path = os.path.join(DATA_PROCESSED, "coverage_report.csv")
    assert os.path.exists(path), "coverage_report.csv does not exist"
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def cvi_scores():
    path = os.path.join(DATA_PROCESSED, "cvi_scores.parquet")
    assert os.path.exists(path), "cvi_scores.parquet does not exist"
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def cvi_detail():
    path = os.path.join(DATA_PROCESSED, "cvi_commodity_detail.parquet")
    assert os.path.exists(path), "cvi_commodity_detail.parquet does not exist"
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def csi_scores():
    path = os.path.join(DATA_PROCESSED, "csi_scores.parquet")
    assert os.path.exists(path), "csi_scores.parquet does not exist"
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def dars_scores():
    path = os.path.join(DATA_PROCESSED, "dars_scores.parquet")
    assert os.path.exists(path), "dars_scores.parquet does not exist"
    return pd.read_parquet(path)


# Test 1: Coverage
def test_coverage_has_all_pilot_districts(coverage_report):
    """coverage_report.csv exists with at least one row per pilot district."""
    districts_in_report = set(coverage_report["district"].unique())
    for d in PILOT_DISTRICTS:
        assert d in districts_in_report, f"{d} missing from coverage report"


# Test 2: CVI null check
def test_cvi_null_for_no_price_districts(cvi_scores):
    """Oyam and Nebbi have NaN CVI for all months."""
    for d in NO_PRICE_DISTRICTS:
        dd = cvi_scores[cvi_scores["district"] == d]
        assert dd["cvi_score"].isna().all(), f"{d} should have all-NaN CVI"


def test_cvi_nonnull_for_price_districts(cvi_scores):
    """Gulu and Lira have non-null CVI for >= 50% of months in 2015-2020."""
    cvi_scores["date"] = pd.to_datetime(cvi_scores["date"])
    for d in ["Gulu", "Lira"]:
        dd = cvi_scores[
            (cvi_scores["district"] == d) &
            (cvi_scores["date"] >= "2015-01-01") &
            (cvi_scores["date"] <= "2020-12-01")
        ]
        non_null_pct = dd["cvi_score"].notna().mean()
        assert non_null_pct >= 0.5, f"{d} has only {non_null_pct:.1%} non-null CVI in 2015-2020"


# Test 3: CVI inclusion — no series with < 36 months
def test_cvi_min_months(cvi_detail):
    """No commodity-district combination in CVI used fewer than 36 months of data."""
    cvi_detail["date"] = pd.to_datetime(cvi_detail["date"])
    counts = cvi_detail.groupby(["district", "commodity", "price_type"])["date"].apply(
        lambda x: x.dt.to_period("M").nunique()
    )
    violations = counts[counts < MIN_MONTHS_FOR_CVI]
    assert len(violations) == 0, f"CVI includes series with < {MIN_MONTHS_FOR_CVI} months: {violations}"


# Test 4: CSI completeness
def test_csi_completeness(csi_scores):
    """All pilot districts have non-null CSI for all months in 2010-2024."""
    csi_scores["date"] = pd.to_datetime(csi_scores["date"])
    for d in PILOT_DISTRICTS:
        dd = csi_scores[csi_scores["district"] == d]
        # Allow some NaN from lag start-up (first 3 months)
        dd_past_startup = dd[dd["date"] >= "2010-04-01"]
        null_count = dd_past_startup["csi_score"].isna().sum()
        assert null_count == 0, f"{d} has {null_count} null CSI scores after startup"


# Test 5: DARS range
def test_dars_range(dars_scores):
    """All non-null DARS values are between 0 and 100."""
    valid = dars_scores["dars_score"].dropna()
    assert (valid >= 0).all(), "DARS has values < 0"
    assert (valid <= 100).all(), "DARS has values > 100"


# Test 6: Threshold
def test_threshold_matches_percentile(dars_scores):
    """Each district's threshold equals its 75th percentile of non-null DARS."""
    for d in PILOT_DISTRICTS:
        dd = dars_scores[dars_scores["district"] == d]
        valid = dd["dars_score"].dropna()
        if len(valid) == 0:
            continue
        expected = np.percentile(valid, HIGH_RISK_PERCENTILE)
        actual = dd["dars_threshold_75p"].iloc[0]
        assert abs(actual - expected) < 0.1, \
            f"{d}: threshold {actual:.2f} != expected {expected:.2f}"


# Test 7: High-risk flag
def test_high_risk_flag(dars_scores):
    """high_risk_flag is 1 iff DARS >= threshold; 0 if below; NaN if DARS is NaN."""
    for _, row in dars_scores.iterrows():
        if pd.isna(row["dars_score"]):
            assert pd.isna(row["high_risk_flag"]), "Flag should be NaN when DARS is NaN"
        elif row["dars_score"] >= row["dars_threshold_75p"]:
            assert row["high_risk_flag"] == 1, "Flag should be 1 when DARS >= threshold"
        else:
            assert row["high_risk_flag"] == 0, "Flag should be 0 when DARS < threshold"


# Test 8: Comparability flag
def test_comparability_flag(dars_scores):
    """Oyam and Nebbi have missing_price_component for all months."""
    for d in NO_PRICE_DISTRICTS:
        dd = dars_scores[dars_scores["district"] == d]
        flags = dd["dars_comparability_flag"].unique()
        assert all(f == "missing_price_component" for f in flags), \
            f"{d} has unexpected flags: {flags}"


# Test 9: Backtest file
def test_backtest_file():
    """backtest_results.csv exists with expected structure."""
    path = os.path.join(REPORTS_DIR, "backtest_results.csv")
    assert os.path.exists(path), "backtest_results.csv does not exist"
    bt = pd.read_csv(path)
    # Should have one row per district-event pair
    expected_rows = len(PILOT_DISTRICTS) * 3  # 3 events
    assert len(bt) == expected_rows, f"Expected {expected_rows} rows, got {len(bt)}"
    # All events should be within 2010-2024
    for label in bt["event_label"].unique():
        assert "2016" in label or "2020" in label or "2022" in label, \
            f"Unexpected event: {label}"


# Test 10: Bulletin
def test_bulletin():
    """dars_bulletin_latest.csv has one row per pilot district with action_note."""
    path = os.path.join(BULLETINS_DIR, "dars_bulletin_latest.csv")
    assert os.path.exists(path), "Bulletin file does not exist"
    bulletin = pd.read_csv(path)
    assert len(bulletin) == len(PILOT_DISTRICTS), \
        f"Expected {len(PILOT_DISTRICTS)} rows, got {len(bulletin)}"
    for d in PILOT_DISTRICTS:
        dd = bulletin[bulletin["district"] == d]
        assert len(dd) == 1, f"{d} missing from bulletin"
        assert dd.iloc[0]["action_note"] != "", f"{d} has empty action_note"
