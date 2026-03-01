"""Step 10 — Outputs and reporting."""
import logging
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from src.config import (
    DATA_PROCESSED, CHARTS_DIR, REPORTS_DIR, BULLETINS_DIR, DOCS_DIR,
    PILOT_DISTRICTS, KNOWN_SHOCK_EVENTS, COMPONENT_WEIGHTS,
    NO_PRICE_DISTRICTS, PRICE_DISTRICTS, MIN_MONTHS_FOR_CVI,
    COMMODITY_CANONICAL, HIGH_RISK_PERCENTILE
)

logger = logging.getLogger(__name__)


def run_report():
    """Main entry point for reporting."""
    os.makedirs(CHARTS_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(BULLETINS_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    dars = pd.read_parquet(os.path.join(DATA_PROCESSED, "dars_scores.parquet"))
    dars["date"] = pd.to_datetime(dars["date"])

    _plot_dars_timeseries(dars)
    _plot_components(dars)
    _plot_backtest()
    _generate_bulletin(dars)
    _write_methodology()
    _write_decision_protocol(dars)

    logger.info("All reports generated.")


def _plot_dars_timeseries(dars):
    """10.1 DARS time series chart per district."""
    for district in PILOT_DISTRICTS:
        dd = dars[dars["district"] == district].sort_values("date").copy()

        fig, ax = plt.subplots(figsize=(14, 6))

        # DARS line
        ax.plot(dd["date"], dd["dars_score"], color="navy", linewidth=1.2, label="DARS Score")

        # Threshold line
        threshold = dd["dars_threshold_75p"].iloc[0] if len(dd) > 0 else None
        if threshold and not np.isnan(threshold):
            ax.axhline(y=threshold, color="red", linestyle="--", linewidth=1, alpha=0.7,
                        label=f"75th Percentile Threshold ({threshold:.1f})")

        # High-risk shading
        high_risk = dd[dd["high_risk_flag"] == 1]
        for _, row in high_risk.iterrows():
            ax.axvspan(row["date"] - pd.Timedelta(days=15),
                       row["date"] + pd.Timedelta(days=15),
                       alpha=0.15, color="red", linewidth=0)

        # Shock event bands
        for event in KNOWN_SHOCK_EVENTS:
            event_start = pd.Timestamp(year=event["year_start"], month=event["month_start"], day=1)
            event_end = pd.Timestamp(year=event["year_end"], month=event["month_end"], day=1)
            ax.axvspan(event_start, event_end, alpha=0.08, color="grey")
            mid = event_start + (event_end - event_start) / 2
            ax.text(mid, ax.get_ylim()[1] * 0.95 if ax.get_ylim()[1] > 0 else 95,
                    event["label"].replace("_", "\n"), ha="center", va="top",
                    fontsize=7, color="grey", style="italic")

        ax.set_title(f"DARS — {district}", fontsize=14)
        ax.set_ylabel("DARS Score (0–100)")
        ax.set_xlabel("Date")
        ax.set_ylim(0, 105)
        ax.legend(loc="upper left", fontsize=9)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(os.path.join(CHARTS_DIR, f"dars_{district}.png"), dpi=150)
        plt.close()
        logger.info("Chart saved: dars_%s.png", district)


def _plot_components(dars):
    """10.2 Component comparison chart per district."""
    comp_cols = ["cvi_score", "csi_score", "yii_score", "sii_score", "icpi_score"]
    comp_labels = ["CVI", "CSI", "YII", "SII", "ICPI"]
    colors = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00"]

    for district in PILOT_DISTRICTS:
        dd = dars[dars["district"] == district].sort_values("date").copy()

        # Weight each component for stacked area
        for col, key in zip(comp_cols, ["CVI", "CSI", "YII", "SII", "ICPI"]):
            dd[f"{col}_weighted"] = dd[col].fillna(0) * COMPONENT_WEIGHTS[key] * 100

        fig, ax = plt.subplots(figsize=(14, 6))
        weighted_cols = [f"{c}_weighted" for c in comp_cols]
        ax.stackplot(dd["date"],
                     *[dd[c].values for c in weighted_cols],
                     labels=comp_labels, colors=colors, alpha=0.7)

        ax.set_title(f"DARS Components — {district}", fontsize=14)
        ax.set_ylabel("Weighted Contribution to DARS")
        ax.set_xlabel("Date")
        ax.legend(loc="upper left", fontsize=9)
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(os.path.join(CHARTS_DIR, f"components_{district}.png"), dpi=150)
        plt.close()
        logger.info("Chart saved: components_%s.png", district)


def _plot_backtest():
    """10.3 Backtest validation chart."""
    bt_path = os.path.join(REPORTS_DIR, "backtest_results.csv")
    if not os.path.exists(bt_path):
        logger.warning("Backtest results not found, skipping chart")
        return

    bt = pd.read_csv(bt_path)

    for event in KNOWN_SHOCK_EVENTS:
        label = event["label"]
        ebt = bt[bt["event_label"] == label]

        if len(ebt) == 0:
            continue

        fig, ax = plt.subplots(figsize=(10, 6))
        x = range(len(ebt))
        width = 0.35

        ax.bar([i - width/2 for i in x], ebt["mean_dars_during"], width,
               label="During Event", color="#d62728", alpha=0.8)
        ax.bar([i + width/2 for i in x], ebt["mean_dars_outside"], width,
               label="Outside Event", color="#2ca02c", alpha=0.8)

        ax.set_xticks(list(x))
        ax.set_xticklabels(ebt["district"], rotation=45, ha="right")
        ax.set_ylabel("Mean DARS Score")
        ax.set_title(f"Backtest: {label.replace('_', ' ')}")
        ax.legend()

        # Add signal lift labels
        for i, (_, row) in enumerate(ebt.iterrows()):
            if pd.notna(row["signal_lift"]):
                ax.text(i, max(row["mean_dars_during"], row["mean_dars_outside"]) + 1,
                        f"lift={row['signal_lift']:.2f}", ha="center", fontsize=8)

        plt.tight_layout()
        plt.savefig(os.path.join(CHARTS_DIR, f"backtest_{label}.png"), dpi=150)
        plt.close()
        logger.info("Chart saved: backtest_%s.png", label)


def _generate_bulletin(dars):
    """10.4 Monthly DARS bulletin."""
    # Most recent month with data
    latest_date = dars.dropna(subset=["dars_score"])["date"].max()
    if pd.isna(latest_date):
        latest_date = dars["date"].max()

    bulletin_rows = []
    for district in PILOT_DISTRICTS:
        dd = dars[(dars["district"] == district) & (dars["date"] == latest_date)]
        if len(dd) == 0:
            # Try latest available for this district
            dd_all = dars[dars["district"] == district].dropna(subset=["dars_score"])
            if len(dd_all) > 0:
                dd = dd_all.sort_values("date").tail(1)
            else:
                dd = dars[dars["district"] == district].sort_values("date").tail(1)

        if len(dd) == 0:
            continue

        row = dd.iloc[0]
        dars_score = row.get("dars_score", np.nan)
        hr_flag = row.get("high_risk_flag", np.nan)

        if pd.notna(hr_flag) and hr_flag == 1:
            action_note = ("DARS threshold exceeded. Apply IFRAD Protocol: "
                           "delay expansion grants by 4-6 weeks. "
                           "Shift capital to liquidity stabilisation.")
        elif pd.notna(hr_flag) and hr_flag == 0:
            action_note = "DARS below threshold. Standard allocation rules apply."
        else:
            action_note = "Insufficient data. Apply standard rules."

        bulletin_rows.append({
            "date": row["date"],
            "district": district,
            "dars_score": round(dars_score, 2) if pd.notna(dars_score) else np.nan,
            "cvi_score": round(row.get("cvi_score", np.nan), 3) if pd.notna(row.get("cvi_score")) else np.nan,
            "csi_score": round(row.get("csi_score", np.nan), 3) if pd.notna(row.get("csi_score")) else np.nan,
            "yii_score": round(row.get("yii_score", np.nan), 3) if pd.notna(row.get("yii_score")) else np.nan,
            "sii_score": round(row.get("sii_score", np.nan), 3) if pd.notna(row.get("sii_score")) else np.nan,
            "icpi_score": round(row.get("icpi_score", np.nan), 3) if pd.notna(row.get("icpi_score")) else np.nan,
            "dars_threshold_75p": round(row.get("dars_threshold_75p", np.nan), 2) if pd.notna(row.get("dars_threshold_75p")) else np.nan,
            "high_risk_flag": hr_flag,
            "dars_comparability_flag": row.get("dars_comparability_flag", ""),
            "action_note": action_note
        })

    bulletin = pd.DataFrame(bulletin_rows)
    bulletin.to_csv(os.path.join(BULLETINS_DIR, "dars_bulletin_latest.csv"), index=False)
    logger.info("Bulletin saved: %d districts", len(bulletin))


def _write_methodology():
    """10.5 Methodology document."""
    doc = """# DAVARS Index Methodology

## Overview

The District Agricultural Risk Score (DARS) is a composite monthly index designed to flag
high-risk periods for youth agribusinesses in pilot districts of Northern Uganda. It combines
five sub-indices into a single 0-100 score per district-month.

## Sub-Indices

### 1. Commodity Volatility Index (CVI) — Weight: 25%

**Purpose**: Captures price instability in local commodity markets.

**Formula per commodity-district**:
- 6-month rolling standard deviation of price (robust scaled)
- 12-month rolling standard deviation of price (robust scaled)
- Z-score spike flag: 1 if (price - 12m rolling mean) / 12m rolling std > 1.5
- Retail-wholesale spread stress: 1 if spread > 75th percentile of series

```
raw_score = 0.4 * scaled_6m_std + 0.4 * scaled_12m_std + 0.20 * spike_flag
```

**District CVI**: Average across qualifying commodities, then robust-scaled to 0-1.

**Commodity Harmonisation**: Applied canonical mapping to standardise names:
- "Maize" and "Maize (white)" -> "Maize"
- "Cassava (fresh)" -> "Cassava"
- For duplicates after mapping, kept the series with higher observation count.

**Minimum Months Filter**: Series with fewer than 36 months excluded from CVI scoring.
This prevents normalisation instability from short Arua series.

**Data Gaps**:
- Oyam and Nebbi: no price data exists. CVI = NaN with flag "no_price_data".
- Arua: short series (12-61 months per commodity). Most excluded by the 36-month filter.

### 2. Climate Stress Index (CSI) — Weight: 25%

**Purpose**: Captures rainfall deficit (drought) and heat stress.

**Climatological normals**: Monthly mean and std of rainfall and temperature per district
computed over 2010-2024.

**Anomalies**:
```
rainfall_anomaly = (rainfall_mm - monthly_normal_mean) / monthly_normal_std
temp_anomaly = (temperature - monthly_normal_mean) / monthly_normal_std
rainfall_stress = max(0, -rainfall_anomaly)   # drought signal
temp_stress = max(0, temp_anomaly)            # heat signal
```

**Lagged rainfall**: 1, 2, and 3-month lags of rainfall stress capture cumulative drought.

```
csi_raw = 0.35 * rainfall_stress + 0.20 * lag1 + 0.15 * lag2 + 0.10 * lag3 + 0.20 * temp_stress
```

Normalised to 0-1 using robust scaling per district.

**Coverage**: All pilot districts have complete climate data (2010-2024).

### 3. Yield Instability Index (YII) — Weight: 20%

**Purpose**: Captures year-to-year crop yield instability.

**Data source**: FAOSTAT national annual crop production data.

**UBOS Statistical Abstract Extraction Outcome**: Attempted extraction of district-level crop
data from the 2023 Statistical Abstract PDF. See docs/data_coverage.md for the detailed
finding. Fell back to FAOSTAT national data.

**Method**:
- For each of 5 key commodities (Maize, Beans, Sorghum, Millet, Cassava):
  - Fit linear OLS trend to yield_kg_per_ha
  - Compute residuals (actual - trend)
  - 5-year rolling mean of production
  - yield_instability = |residual| / rolling_5yr_mean

Average across commodities per year, robust-scaled, interpolated to monthly.

**Limitation**: National data applied uniformly to all districts. yii_scope = "national".

### 4. Shock Intensity Index (SII) — Weight: 20%

**Purpose**: Captures conflict events and natural disasters.

**Conflict component** (national, 55% weight):
- Monthly total event count and fatalities from ACLED data
- Each robust-scaled independently, then combined:
  `conflict_signal = 0.6 * scaled_events + 0.4 * scaled_fatalities`

**Disaster component** (district-level, 45% weight):
- Severity mapped: low=0.25, medium/moderate=0.50, high/major=0.75, critical=1.0
- Monthly max severity per district
- Sparse records: most district-months have no disaster event (score = 0)

```
sii_raw = 0.55 * conflict_signal + 0.45 * disaster_severity
```

### 5. Input Cost Pressure Index (ICPI) — Weight: 10%

**Purpose**: Captures rising input costs (fertilizer, fuel, etc.).

**Data**: National annual data (2018-2024). Year-over-year percentage change, positive only
(rising costs = stress). Averaged across items, robust-scaled, interpolated to monthly.

**Limitation**: Low-weight national signal. Annual resolution.

## Normalisation: Robust Scaling

All sub-indices use robust scaling instead of min-max normalisation:
```
scaled = (value - median) / (95th_percentile - 5th_percentile)
scaled = clip(scaled, 0, 1)
```

**Rationale**: Min-max is sensitive to outliers and short series. Robust scaling uses the
interquartile-like range (5th-95th) to reduce the influence of extreme values, producing
more stable scores across districts with different data coverage.

## DARS Composition

```
DARS = (sum of weight_i * component_i) * 100
```

Scale: 0-100.

### Missing Component Handling
- CVI null (Oyam, Nebbi): weight redistributed to CSI and SII proportionally
- Other single null: weight redistributed proportionally to remaining components
- 3+ components null: DARS = NaN

### Comparability Flag
- `full_components`: all five sub-indices present
- `missing_price_component`: CVI is null
- `limited_components`: two or more null

**Usage guidance**: Do not directly compare DARS values across districts with different
comparability flags. A Gulu score (full_components) and an Oyam score (missing_price_component)
are computed with different effective weights and should not be ranked side-by-side without
noting this distinction.

## Threshold and High-Risk Flag

Per-district 75th percentile of DARS over 2010-2024 (non-null values).
`high_risk_flag = 1` if DARS >= threshold.

## Backtesting

Three reference events tested:
1. 2016-2017 drought (Jun 2016 - Dec 2017)
2. 2020 COVID disruption (Mar 2020 - Jun 2021)
3. 2022-2023 inflation shock (Jan 2022 - Jun 2023)

Signal lift = mean DARS during event / mean DARS outside event.
Values > 1.0 indicate DARS rises during known shock periods.

## What DARS Is Not

DARS is **not** a price forecast. It does not predict specific commodity prices or household
income. It is a composite risk signal designed to flag months where agricultural stress factors
are elevated relative to a district's historical baseline, triggering precautionary capital
allocation adjustments by IFRAD.
"""
    with open(os.path.join(DOCS_DIR, "index_methodology.md"), "w") as f:
        f.write(doc)
    logger.info("Methodology document written")


def _write_decision_protocol(dars):
    """10.6 Decision protocol stub with computed thresholds."""
    thresholds = {}
    for district in PILOT_DISTRICTS:
        dd = dars[dars["district"] == district]
        if len(dd) > 0 and dd["dars_threshold_75p"].notna().any():
            thresholds[district] = dd["dars_threshold_75p"].iloc[0]
        else:
            thresholds[district] = "N/A"

    threshold_text = "\n".join(
        f"- **{d}**: {v:.1f}" if isinstance(v, float) else f"- **{d}**: {v}"
        for d, v in thresholds.items()
    )

    doc = f"""# IFRAD DARS Decision Protocol — Draft

## Trigger condition
District X receives high_risk_flag = 1 for Month T.

## Computed 75th Percentile Thresholds (from pipeline)
{threshold_text}

## Actions applied in Month T+1
1. Enterprise expansion grants: delayed by one allocation cycle (4-6 weeks)
2. Capital deployment purpose: shifted from growth to liquidity stabilisation
3. Mentorship emphasis: pivoted to cash-flow preservation and risk reduction

## Standard rules (high_risk_flag = 0 or NaN)
Standard allocation timing and purposes apply.

## Protocol owner
Subject to formal sign-off by IFRAD before pilot activation.

## Fields requiring completion before pilot activation
- [ ] Exact threshold value per district (computed by pipeline - see above)
- [ ] Specific grant types and amounts affected by the delay rule
- [ ] Escalation procedure for extended high-risk periods (3+ consecutive months)
- [ ] Data refresh cadence and responsible officer
"""
    with open(os.path.join(DOCS_DIR, "decision_protocol_stub.md"), "w") as f:
        f.write(doc)
    logger.info("Decision protocol stub written")
