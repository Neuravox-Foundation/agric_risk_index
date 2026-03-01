"""Step 8 — Compose DARS + Step 9 — Backtesting."""
import logging
import os
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats

from src.config import (
    DATA_PROCESSED, REPORTS_DIR,
    PILOT_DISTRICTS, PRICE_DISTRICTS, NO_PRICE_DISTRICTS,
    COMPONENT_WEIGHTS, HIGH_RISK_PERCENTILE, KNOWN_SHOCK_EVENTS,
    DATE_START, DATE_END
)

logger = logging.getLogger(__name__)

COMPONENT_COLS = ["cvi_score", "csi_score", "yii_score", "sii_score", "icpi_score"]
COMPONENT_KEYS = ["CVI", "CSI", "YII", "SII", "ICPI"]


def run_dars():
    """Main entry point for DARS composition."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    # Load master panel
    panel = pd.read_parquet(os.path.join(DATA_PROCESSED, "master_panel.parquet"))

    # Load sub-indices
    cvi = pd.read_parquet(os.path.join(DATA_PROCESSED, "cvi_scores.parquet"))
    csi = pd.read_parquet(os.path.join(DATA_PROCESSED, "csi_scores.parquet"))
    yii = pd.read_parquet(os.path.join(DATA_PROCESSED, "yii_scores.parquet"))
    sii = pd.read_parquet(os.path.join(DATA_PROCESSED, "sii_scores.parquet"))
    icpi = pd.read_parquet(os.path.join(DATA_PROCESSED, "icpi_scores.parquet"))

    # Join all to panel
    dars = panel.copy()
    dars = dars.merge(cvi[["date", "district", "cvi_score"]], on=["date", "district"], how="left")
    dars = dars.merge(csi[["date", "district", "csi_score"]], on=["date", "district"], how="left")
    dars = dars.merge(yii[["date", "district", "yii_score"]], on=["date", "district"], how="left")
    dars = dars.merge(sii[["date", "district", "sii_score"]], on=["date", "district"], how="left")
    dars = dars.merge(icpi[["date", "district", "icpi_score"]], on=["date", "district"], how="left")

    # --- Comparability flag ---
    def get_comparability_flag(row):
        nulls = sum(1 for c in COMPONENT_COLS if pd.isna(row[c]))
        if nulls == 0:
            return "full_components"
        elif pd.isna(row["cvi_score"]) and row["district"] in NO_PRICE_DISTRICTS:
            return "missing_price_component"
        elif pd.isna(row["cvi_score"]):
            return "missing_price_component"
        elif nulls >= 2:
            return "limited_components"
        else:
            return "limited_components"

    dars["dars_comparability_flag"] = dars.apply(get_comparability_flag, axis=1)

    # --- Compute DARS with missing component handling ---
    dars_scores = []
    weight_notes = []
    n_components_list = []

    for idx, row in dars.iterrows():
        available = {}
        for key, col in zip(COMPONENT_KEYS, COMPONENT_COLS):
            if pd.notna(row[col]):
                available[key] = row[col]

        n_components = len(available)
        n_components_list.append(n_components)

        if n_components < 3:
            dars_scores.append(np.nan)
            weight_notes.append("insufficient_components")
            continue

        # Determine weights with redistribution
        base_weights = COMPONENT_WEIGHTS.copy()
        missing_keys = [k for k in COMPONENT_KEYS if k not in available]

        if missing_keys:
            total_missing_weight = sum(base_weights[k] for k in missing_keys)

            if "CVI" in missing_keys:
                # Redistribute CVI weight to CSI and SII only
                cvi_weight = base_weights["CVI"]
                remaining_missing = [k for k in missing_keys if k != "CVI"]
                remaining_missing_weight = sum(base_weights[k] for k in remaining_missing)

                # Redistribute CVI weight proportionally to CSI and SII
                csi_sii_total = base_weights.get("CSI", 0) + base_weights.get("SII", 0)
                if csi_sii_total > 0 and "CSI" in available and "SII" in available:
                    csi_share = base_weights["CSI"] / csi_sii_total
                    sii_share = base_weights["SII"] / csi_sii_total
                    base_weights["CSI"] += cvi_weight * csi_share
                    base_weights["SII"] += cvi_weight * sii_share
                elif "CSI" in available:
                    base_weights["CSI"] += cvi_weight
                elif "SII" in available:
                    base_weights["SII"] += cvi_weight

                # If other components are also missing, redistribute proportionally to remaining
                if remaining_missing:
                    avail_keys_no_cvi = [k for k in available if k != "CVI"]
                    avail_total = sum(base_weights[k] for k in avail_keys_no_cvi)
                    if avail_total > 0:
                        for mk in remaining_missing:
                            mw = base_weights[mk]
                            for ak in avail_keys_no_cvi:
                                base_weights[ak] += mw * (base_weights[ak] / avail_total)
            else:
                # Non-CVI missing: redistribute proportionally to available
                avail_total = sum(base_weights[k] for k in available)
                if avail_total > 0:
                    for mk in missing_keys:
                        mw = base_weights[mk]
                        for ak in available:
                            base_weights[ak] += mw * (base_weights[ak] / avail_total)

        # Compute weighted sum
        score = sum(base_weights[k] * available[k] for k in available)
        dars_scores.append(score * 100)

        effective = {k: round(base_weights[k], 3) for k in available}
        weight_notes.append(str(effective))

    dars["dars_score"] = dars_scores
    dars["dars_weight_note"] = weight_notes
    dars["n_components_used"] = n_components_list

    # --- District-specific thresholds ---
    for district in PILOT_DISTRICTS:
        mask = dars["district"] == district
        valid_scores = dars.loc[mask, "dars_score"].dropna()
        if len(valid_scores) > 0:
            threshold = np.percentile(valid_scores, HIGH_RISK_PERCENTILE)
        else:
            threshold = np.nan
        dars.loc[mask, "dars_threshold_75p"] = threshold

    # --- High risk flag ---
    dars["high_risk_flag"] = np.where(
        dars["dars_score"].isna(),
        np.nan,
        np.where(dars["dars_score"] >= dars["dars_threshold_75p"], 1.0, 0.0)
    )

    # Output columns
    output_cols = [
        "date", "district", "dars_score", "cvi_score", "csi_score",
        "yii_score", "sii_score", "icpi_score", "dars_threshold_75p",
        "high_risk_flag", "dars_comparability_flag", "dars_weight_note",
        "n_components_used"
    ]
    dars_out = dars[output_cols].sort_values(["district", "date"]).reset_index(drop=True)

    dars_out.to_parquet(os.path.join(DATA_PROCESSED, "dars_scores.parquet"), index=False)
    dars_out.to_csv(os.path.join(DATA_PROCESSED, "dars_scores.csv"), index=False)
    logger.info("DARS scores saved: %d rows", len(dars_out))

    return dars_out


def run_backtest():
    """Step 9 — Backtesting."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    dars = pd.read_parquet(os.path.join(DATA_PROCESSED, "dars_scores.parquet"))
    dars["date"] = pd.to_datetime(dars["date"])

    # --- 9.1 Event alignment test ---
    bt_records = []

    for event in KNOWN_SHOCK_EVENTS:
        event_start = pd.Timestamp(year=event["year_start"], month=event["month_start"], day=1)
        event_end = pd.Timestamp(year=event["year_end"], month=event["month_end"], day=1)

        for district in PILOT_DISTRICTS:
            dmask = dars["district"] == district

            # Event period
            event_mask = dmask & (dars["date"] >= event_start) & (dars["date"] <= event_end)
            event_scores = dars.loc[event_mask, "dars_score"].dropna()

            # Non-event period (excluding buffer)
            buffer_start = event_start - pd.DateOffset(months=2)
            buffer_end = event_end + pd.DateOffset(months=2)
            nonevent_mask = dmask & ~((dars["date"] >= buffer_start) & (dars["date"] <= buffer_end))
            nonevent_scores = dars.loc[nonevent_mask, "dars_score"].dropna()

            mean_during = event_scores.mean() if len(event_scores) > 0 else np.nan
            mean_outside = nonevent_scores.mean() if len(nonevent_scores) > 0 else np.nan
            signal_lift = mean_during / mean_outside if mean_outside and mean_outside > 0 else np.nan

            hr_during = dars.loc[event_mask, "high_risk_flag"]
            hr_nonevent = dars.loc[nonevent_mask, "high_risk_flag"]
            hr_rate_during = hr_during.mean() if len(hr_during) > 0 else np.nan
            hr_rate_baseline = hr_nonevent.mean() if len(hr_nonevent) > 0 else np.nan

            comp_flag = dars.loc[dmask, "dars_comparability_flag"].mode()
            comp_flag_val = comp_flag.iloc[0] if len(comp_flag) > 0 else "unknown"

            bt_records.append({
                "event_label": event["label"],
                "district": district,
                "mean_dars_during": round(mean_during, 2) if pd.notna(mean_during) else np.nan,
                "mean_dars_outside": round(mean_outside, 2) if pd.notna(mean_outside) else np.nan,
                "signal_lift": round(signal_lift, 3) if pd.notna(signal_lift) else np.nan,
                "high_risk_rate_during": round(hr_rate_during, 3) if pd.notna(hr_rate_during) else np.nan,
                "high_risk_rate_baseline": round(hr_rate_baseline, 3) if pd.notna(hr_rate_baseline) else np.nan,
                "dars_comparability_flag": comp_flag_val
            })

    bt_df = pd.DataFrame(bt_records)
    bt_df.to_csv(os.path.join(REPORTS_DIR, "backtest_results.csv"), index=False)
    logger.info("Backtest results saved: %d rows", len(bt_df))

    # --- 9.2 Predictive signal test ---
    pred_records = []
    for district in PRICE_DISTRICTS:
        dmask = dars["district"] == district
        dd = dars.loc[dmask].sort_values("date").copy()
        dd = dd.dropna(subset=["dars_score", "cvi_score"])

        for lag in [2, 3]:
            dd[f"cvi_lead_{lag}"] = dd["cvi_score"].shift(-lag)
            valid = dd.dropna(subset=["dars_score", f"cvi_lead_{lag}"])
            if len(valid) >= 10:
                corr, pval = scipy_stats.pearsonr(valid["dars_score"], valid[f"cvi_lead_{lag}"])
                pred_records.append({
                    "district": district,
                    "lag_months": lag,
                    "pearson_r": round(corr, 4),
                    "p_value": round(pval, 4),
                    "n_obs": len(valid)
                })

    pred_df = pd.DataFrame(pred_records)
    pred_df.to_csv(os.path.join(REPORTS_DIR, "predictive_signal.csv"), index=False)
    logger.info("Predictive signal results saved")

    # --- 9.3 Sensitivity test ---
    _run_sensitivity_test()

    return bt_df


def _compute_dars_with_weights(weights, include_icpi=True):
    """Compute DARS with custom weights for sensitivity testing."""
    panel = pd.read_parquet(os.path.join(DATA_PROCESSED, "master_panel.parquet"))
    cvi = pd.read_parquet(os.path.join(DATA_PROCESSED, "cvi_scores.parquet"))
    csi = pd.read_parquet(os.path.join(DATA_PROCESSED, "csi_scores.parquet"))
    yii = pd.read_parquet(os.path.join(DATA_PROCESSED, "yii_scores.parquet"))
    sii = pd.read_parquet(os.path.join(DATA_PROCESSED, "sii_scores.parquet"))
    icpi = pd.read_parquet(os.path.join(DATA_PROCESSED, "icpi_scores.parquet"))

    dars = panel.copy()
    dars = dars.merge(cvi[["date", "district", "cvi_score"]], on=["date", "district"], how="left")
    dars = dars.merge(csi[["date", "district", "csi_score"]], on=["date", "district"], how="left")
    dars = dars.merge(yii[["date", "district", "yii_score"]], on=["date", "district"], how="left")
    dars = dars.merge(sii[["date", "district", "sii_score"]], on=["date", "district"], how="left")
    dars = dars.merge(icpi[["date", "district", "icpi_score"]], on=["date", "district"], how="left")

    if not include_icpi:
        dars["icpi_score"] = 0.0

    scores = []
    for _, row in dars.iterrows():
        available = {}
        for key, col in zip(COMPONENT_KEYS, COMPONENT_COLS):
            if pd.notna(row[col]):
                available[key] = row[col]

        if len(available) < 3:
            scores.append(np.nan)
            continue

        # Redistribute missing weights
        w = weights.copy()
        missing = [k for k in COMPONENT_KEYS if k not in available]
        if missing:
            missing_w = sum(w.get(k, 0) for k in missing)
            avail_total = sum(w.get(k, 0) for k in available)
            if avail_total > 0:
                for mk in missing:
                    mw = w.get(mk, 0)
                    for ak in available:
                        w[ak] = w.get(ak, 0) + mw * (w.get(ak, 0) / avail_total)

        score = sum(w.get(k, 0) * available[k] for k in available)
        scores.append(score * 100)

    dars["dars_score"] = scores
    return dars[["date", "district", "dars_score"]]


def _run_sensitivity_test():
    """Run DARS with three weight configurations and compare."""
    # Config 1: equal weights
    equal_weights = {k: 0.20 for k in COMPONENT_KEYS}
    dars_equal = _compute_dars_with_weights(equal_weights)
    dars_equal = dars_equal.rename(columns={"dars_score": "dars_equal"})

    # Config 2: configured weights
    dars_config = _compute_dars_with_weights(COMPONENT_WEIGHTS)
    dars_config = dars_config.rename(columns={"dars_score": "dars_config"})

    # Config 3: ICPI excluded (redistribute to CVI, CSI, SII)
    no_icpi_weights = COMPONENT_WEIGHTS.copy()
    icpi_w = no_icpi_weights.pop("ICPI")
    # Redistribute to CVI, CSI, SII
    redist_keys = ["CVI", "CSI", "SII"]
    redist_total = sum(no_icpi_weights[k] for k in redist_keys)
    for k in redist_keys:
        no_icpi_weights[k] += icpi_w * (no_icpi_weights[k] / redist_total)
    no_icpi_weights["ICPI"] = 0
    dars_no_icpi = _compute_dars_with_weights(no_icpi_weights, include_icpi=False)
    dars_no_icpi = dars_no_icpi.rename(columns={"dars_score": "dars_no_icpi"})

    # Merge
    merged = dars_equal.merge(dars_config, on=["date", "district"])
    merged = merged.merge(dars_no_icpi, on=["date", "district"])

    # Correlations per district
    sens_records = []
    for district in PILOT_DISTRICTS:
        dd = merged[merged["district"] == district].dropna(subset=["dars_equal", "dars_config", "dars_no_icpi"])
        if len(dd) < 10:
            continue

        r_eq_cfg, _ = scipy_stats.pearsonr(dd["dars_equal"], dd["dars_config"])
        r_eq_noicpi, _ = scipy_stats.pearsonr(dd["dars_equal"], dd["dars_no_icpi"])
        r_cfg_noicpi, _ = scipy_stats.pearsonr(dd["dars_config"], dd["dars_no_icpi"])

        sens_records.append({
            "district": district,
            "corr_equal_vs_config": round(r_eq_cfg, 4),
            "corr_equal_vs_no_icpi": round(r_eq_noicpi, 4),
            "corr_config_vs_no_icpi": round(r_cfg_noicpi, 4),
            "n_obs": len(dd),
            "robust_flag": "robust" if min(r_eq_cfg, r_eq_noicpi, r_cfg_noicpi) > 0.85 else "sensitive"
        })

    sens_df = pd.DataFrame(sens_records)
    sens_df.to_csv(os.path.join(REPORTS_DIR, "sensitivity_results.csv"), index=False)
    logger.info("Sensitivity results saved")
