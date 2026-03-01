# DAVARS Index Methodology

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
