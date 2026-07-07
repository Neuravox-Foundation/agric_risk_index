#!/usr/bin/env python3
"""Build the static dashboard's data.json from pipeline output files.

Reads the same CSVs the old Streamlit app read and emits one JSON bundle the
static site loads client-side. Run after run_pipeline.py, then commit
site/data.json so Cloudflare Pages serves it with no server-side compute.

Usage:  python site/build_data.py
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _num(v):
    """Parse a CSV cell to float, or None for blanks/NaN."""
    if v is None:
        return None
    v = v.strip()
    if v == "" or v.lower() == "nan":
        return None
    try:
        return float(v)
    except ValueError:
        return v


def read_csv(rel_path):
    path = os.path.join(ROOT, rel_path)
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def num_cols(rows, cols):
    """Return rows with the named columns coerced to numbers."""
    out = []
    for r in rows:
        rec = dict(r)
        for c in cols:
            if c in rec:
                rec[c] = _num(rec[c])
        out.append(rec)
    return out


NUMERIC = [
    "dars_score", "cvi_score", "csi_score", "yii_score", "sii_score",
    "icpi_score", "dars_threshold_75p", "high_risk_flag", "n_components_used",
]


def main():
    dars = num_cols(read_csv("data_processed/dars_scores.csv"), NUMERIC)
    dars.sort(key=lambda r: (r["district"], r["date"]))

    districts = sorted({r["district"] for r in dars})

    # Summary metrics for the Overview tab.
    valid = [r for r in dars if r["dars_score"] is not None]
    hr = [r["high_risk_flag"] for r in dars if r["high_risk_flag"] is not None]
    dates = sorted(r["date"] for r in dars)
    summary = {
        "total_months": len(valid),
        "districts_covered": len(districts),
        "date_start": dates[0],
        "date_end": dates[-1],
        "high_risk_rate": round(100 * sum(1 for x in hr if x == 1) / len(hr), 1) if hr else None,
    }

    backtest = num_cols(
        read_csv("outputs/reports/backtest_results.csv"),
        ["mean_dars_during", "mean_dars_outside", "signal_lift",
         "high_risk_rate_during", "high_risk_rate_baseline"],
    )
    predictive = num_cols(
        read_csv("outputs/reports/predictive_signal.csv"),
        ["lag_months", "pearson_r", "p_value", "n_obs"],
    )
    sensitivity = num_cols(
        read_csv("outputs/reports/sensitivity_results.csv"),
        ["corr_equal_vs_config", "corr_equal_vs_no_icpi",
         "corr_config_vs_no_icpi", "n_obs"],
    )
    bulletin = num_cols(
        read_csv("outputs/bulletins/dars_bulletin_latest.csv"),
        ["dars_score", "cvi_score", "csi_score", "yii_score", "sii_score",
         "icpi_score", "dars_threshold_75p", "high_risk_flag"],
    )

    bundle = {
        "generated_from": "run_pipeline.py outputs",
        "districts": districts,
        "summary": summary,
        "dars": dars,
        "backtest": backtest,
        "predictive": predictive,
        "sensitivity": sensitivity,
        "bulletin": bulletin,
    }

    out_path = os.path.join(HERE, "data.json")
    with open(out_path, "w") as f:
        json.dump(bundle, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"Wrote {out_path} ({size_kb:.1f} KB) — {len(dars)} DARS rows, "
          f"{len(districts)} districts")


if __name__ == "__main__":
    main()
