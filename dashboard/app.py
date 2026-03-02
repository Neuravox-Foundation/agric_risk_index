"""DAVARS Dashboard — Read-only Streamlit dashboard for DARS pipeline outputs."""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import os

st.set_page_config(
    page_title="DAVARS — District Agricultural Risk System",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# File loading with caching
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PILOT_DISTRICTS = ["Gulu", "Arua", "Lira", "Oyam", "Nebbi"]

SHOCK_EVENTS = [
    {"label": "2016–17 Drought", "start": "2016-07-01", "end": "2017-12-31"},
    {"label": "COVID Disruption", "start": "2020-03-01", "end": "2021-06-30"},
    {"label": "2022–23 Inflation Shock", "start": "2022-01-01", "end": "2023-06-30"},
]


def _load_file(relative_path):
    """Load a CSV file relative to project root."""
    path = os.path.join(BASE_DIR, relative_path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return path


@st.cache_data
def load_dars():
    path = _load_file("data_processed/dars_scores.csv")
    return pd.read_csv(path, parse_dates=["date"])


@st.cache_data
def load_backtest():
    path = _load_file("outputs/reports/backtest_results.csv")
    return pd.read_csv(path)


@st.cache_data
def load_predictive():
    path = _load_file("outputs/reports/predictive_signal.csv")
    return pd.read_csv(path)


@st.cache_data
def load_sensitivity():
    path = _load_file("outputs/reports/sensitivity_results.csv")
    return pd.read_csv(path)


@st.cache_data
def load_bulletin():
    path = _load_file("outputs/bulletins/dars_bulletin_latest.csv")
    return pd.read_csv(path)


def safe_load(loader, name):
    """Wrap a loader with user-friendly error handling."""
    try:
        return loader()
    except FileNotFoundError as e:
        st.error(
            "Demo data files are missing from this deployment. "
            "This dashboard reads pre-generated outputs from the DAVARS pipeline."
        )
        with st.expander("Technical details"):
            st.code(f"File not found: {e}")
        return None


# ---------------------------------------------------------------------------
# Sidebar — persistent across all tabs
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## DAVARS")
    st.markdown("District Agricultural Risk System")
    st.divider()

    district = st.selectbox(
        "Select district",
        PILOT_DISTRICTS,
        key="selected_district",
    )

    st.divider()

    dars_df = safe_load(load_dars, "DARS scores")
    if dars_df is not None:
        date_min = dars_df["date"].min().strftime("%b %Y")
        date_max = dars_df["date"].max().strftime("%b %Y")
        st.caption(f"Data period: {date_min} – {date_max}")

    st.markdown("[View source on GitHub](https://github.com/Lu9er/DAVARS)")
    st.divider()
    st.caption("Built by Neuravox. Prototype v1.0.")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

if dars_df is None:
    st.stop()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Overview", "District Risk", "Risk Breakdown", "Validation", "IFRAD Bulletin"
])


# ========================== TAB 1: OVERVIEW ================================

with tab1:
    st.header("DAVARS — District Agricultural Volatility and Adaptive Risk System")

    st.markdown(
        "DAVARS computes a monthly agricultural risk score for five districts in "
        "Northern Uganda — Gulu, Arua, Lira, Oyam, and Nebbi. The score combines "
        "price volatility, climate stress, production instability, conflict and "
        "disaster shocks, and input cost pressure into a single composite index "
        "(0–100). When the score exceeds a district-specific threshold, it signals "
        "a high-risk month — a period when deploying growth capital into youth "
        "agribusinesses is statistically more likely to produce income losses."
    )

    st.subheader("Key Metrics")

    valid_dars = dars_df["dars_score"].dropna()
    total_months = len(valid_dars)
    districts_covered = dars_df["district"].nunique()
    date_range_str = f"{dars_df['date'].min().strftime('%b %Y')} – {dars_df['date'].max().strftime('%b %Y')}"
    hr_rate = (dars_df["high_risk_flag"].dropna() == 1).mean() * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Months Modelled", f"{total_months:,}")
    c2.metric("Districts Covered", districts_covered)
    c3.metric("Data Period", date_range_str)
    c4.metric("Overall High-Risk Rate", f"{hr_rate:.1f}%")

    st.subheader("Index Components")

    comp_data = pd.DataFrame([
        {"Component": "Commodity Volatility Index (CVI)", "Weight": "25%",
         "Data Source": "WFP VAM price data", "Coverage": "Gulu, Arua, Lira only"},
        {"Component": "Climate Stress Index (CSI)", "Weight": "25%",
         "Data Source": "NASA POWER", "Coverage": "All districts"},
        {"Component": "Yield Instability Index (YII)", "Weight": "20%",
         "Data Source": "FAOSTAT national crops", "Coverage": "All districts (national signal)"},
        {"Component": "Shock Intensity Index (SII)", "Weight": "20%",
         "Data Source": "ACLED + disaster records", "Coverage": "All districts"},
        {"Component": "Input Cost Pressure Index (ICPI)", "Weight": "10%",
         "Data Source": "IFDC fertilizer data", "Coverage": "All districts (national signal)"},
    ])
    st.dataframe(comp_data, hide_index=True, use_container_width=True)

    st.info(
        "**Data limitations**\n\n"
        "Oyam and Nebbi have no commodity price data. Their DARS scores are computed "
        "from four components and are flagged `missing_price_component` throughout.\n\n"
        "YII, ICPI, and the conflict component of SII are national-level signals applied "
        "uniformly across all districts. They do not reflect district-specific production "
        "or conflict conditions.\n\n"
        "DAVARS is a prototype volatility index. It does not measure household welfare, "
        "predict specific commodity prices, or substitute for field-level enterprise assessment."
    )


# ========================== TAB 2: DISTRICT RISK ===========================

with tab2:
    sel = st.session_state["selected_district"]
    dd = dars_df[dars_df["district"] == sel].sort_values("date").copy()

    st.header(f"District Risk — {sel}")

    # Most recent non-null values
    dd_valid = dd.dropna(subset=["dars_score"])
    if len(dd_valid) == 0:
        st.warning(f"No DARS data available for {sel} in the selected period.")
    else:
        latest = dd_valid.iloc[-1]
        current_score = latest["dars_score"]
        threshold = latest["dars_threshold_75p"]
        hr_flag = latest["high_risk_flag"]
        comp_flag = latest["dars_comparability_flag"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current DARS Score", f"{current_score:.1f}")
        c2.metric("District Threshold", f"{threshold:.1f}")

        with c3:
            if pd.notna(hr_flag) and hr_flag == 1:
                st.error("⬆ HIGH RISK")
            elif pd.notna(hr_flag) and hr_flag == 0:
                st.success("✓ NORMAL")
            else:
                st.warning("— INSUFFICIENT DATA")

        c4.metric("Comparability", comp_flag)

        # ---- DARS Time Series Chart ----
        st.subheader("DARS Score Over Time")

        fig = go.Figure()

        # Main DARS line
        fig.add_trace(go.Scatter(
            x=dd["date"], y=dd["dars_score"],
            mode="lines", name="DARS Score",
            line=dict(color="#1F4E79", width=2),
            hovertemplate=(
                "<b>%{x|%b %Y}</b><br>"
                "DARS: %{y:.1f}<br>"
                "<extra></extra>"
            ),
            customdata=dd[["high_risk_flag", "n_components_used", "dars_comparability_flag"]].values,
        ))

        # Update hover for custom data
        fig.update_traces(
            hovertemplate=(
                "<b>%{x|%b %Y}</b><br>"
                "DARS: %{y:.1f}<br>"
                "High Risk: %{customdata[0]}<br>"
                "Components: %{customdata[1]}<br>"
                "Flag: %{customdata[2]}<br>"
                "<extra></extra>"
            ),
            selector=dict(name="DARS Score"),
        )

        # Threshold line
        fig.add_hline(
            y=threshold, line_dash="dash", line_color="#E63946",
            annotation_text=f"Risk Threshold ({threshold:.1f})",
            annotation_position="top right",
            annotation_font_color="#E63946",
        )

        # High-risk shading — contiguous blocks
        hr_months = dd[dd["high_risk_flag"] == 1]["date"].sort_values().reset_index(drop=True)
        if len(hr_months) > 0:
            blocks = []
            block_start = hr_months.iloc[0]
            prev = block_start
            for i in range(1, len(hr_months)):
                curr = hr_months.iloc[i]
                if (curr - prev).days > 45:
                    blocks.append((block_start, prev))
                    block_start = curr
                prev = curr
            blocks.append((block_start, prev))

            for bs, be in blocks:
                fig.add_vrect(
                    x0=bs - pd.Timedelta(days=15),
                    x1=be + pd.Timedelta(days=15),
                    fillcolor="rgba(230, 57, 70, 0.15)",
                    line_width=0, layer="below",
                )

        # Shock event bands
        for event in SHOCK_EVENTS:
            fig.add_vrect(
                x0=event["start"], x1=event["end"],
                fillcolor="rgba(150, 150, 150, 0.12)",
                line_width=0, layer="below",
            )
            mid_date = pd.Timestamp(event["start"]) + (
                pd.Timestamp(event["end"]) - pd.Timestamp(event["start"])
            ) / 2
            fig.add_annotation(
                x=mid_date, y=100, text=event["label"],
                showarrow=False, font=dict(size=9, color="grey"),
                yanchor="top",
            )

        fig.update_layout(
            yaxis=dict(range=[0, 105], title="DARS Score"),
            xaxis=dict(title="Date"),
            height=500,
            margin=dict(t=40),
            showlegend=True,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        )

        st.plotly_chart(fig, use_container_width=True)

        # Data table — last 24 months
        st.subheader("Recent Data (Last 24 Months)")
        recent = dd.tail(24)[["date", "dars_score", "high_risk_flag",
                              "n_components_used", "dars_comparability_flag"]].copy()
        recent["date"] = recent["date"].dt.strftime("%Y-%m")
        recent.columns = ["Date", "DARS Score", "High Risk", "Components Used", "Comparability Flag"]
        st.dataframe(recent, height=300, hide_index=True, use_container_width=True)


# ========================== TAB 3: RISK BREAKDOWN ==========================

with tab3:
    sel = st.session_state["selected_district"]
    dd = dars_df[dars_df["district"] == sel].sort_values("date").copy()

    st.header(f"Risk Breakdown — {sel}")

    component_config = [
        ("cvi_score", "CVI — Commodity Volatility", "#1F4E79"),
        ("csi_score", "CSI — Climate Stress", "#2E75B6"),
        ("yii_score", "YII — Yield Instability", "#70AD47"),
        ("sii_score", "SII — Shock Intensity", "#ED7D31"),
        ("icpi_score", "ICPI — Input Cost Pressure", "#A9D18E"),
    ]

    fig = go.Figure()

    for col, label, color in component_config:
        series = dd[["date", col]].dropna(subset=[col])
        if len(series) == 0:
            continue
        fig.add_trace(go.Scatter(
            x=series["date"], y=series[col],
            mode="lines", name=label,
            line=dict(color=color, width=1.5),
            hovertemplate=f"<b>{label}</b><br>" + "%{x|%b %Y}: %{y:.3f}<extra></extra>",
        ))

    fig.update_layout(
        yaxis=dict(title="Component Score (0–1)", range=[-0.05, 1.05]),
        xaxis=dict(title="Date"),
        height=500,
        margin=dict(t=40),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )

    st.plotly_chart(fig, use_container_width=True)

    if sel in ["Oyam", "Nebbi"]:
        st.markdown(
            "*CVI is not available for this district — no commodity price data. "
            "DARS is computed from four components.*"
        )

    st.markdown(
        "*These lines show the level of each component index over time. They are not "
        "additive contributions — they are independent risk signals combined through "
        "the weighted DARS formula.*"
    )

    # Component summary table
    st.subheader("Component Summary")
    summary_rows = []
    for col, label, _ in component_config:
        vals = dd[col].dropna()
        if len(vals) == 0:
            summary_rows.append({"Component": label, "Mean": "N/A", "Max": "N/A"})
        else:
            summary_rows.append({
                "Component": label,
                "Mean": f"{vals.mean():.3f}",
                "Max": f"{vals.max():.3f}",
            })
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)

    # Sensitivity note
    st.subheader("Weight Sensitivity")
    sens_df = safe_load(load_sensitivity, "Sensitivity")
    if sens_df is not None:
        sel_sens = sens_df[sens_df["district"] == sel]
        if len(sel_sens) > 0:
            row = sel_sens.iloc[0]
            r_vals = (
                f"equal vs config: {row['corr_equal_vs_config']:.3f}, "
                f"equal vs no-ICPI: {row['corr_equal_vs_no_icpi']:.3f}, "
                f"config vs no-ICPI: {row['corr_config_vs_no_icpi']:.3f}"
            )
            robust_label = "**robust**" if row["robust_flag"] == "robust" else "**sensitive**"
            st.markdown(
                f"Correlation between equal-weight, configured-weight, and "
                f"ICPI-excluded DARS variants: {r_vals}. "
                f"Index is {robust_label} to weight variation."
            )
        else:
            st.caption("No sensitivity data available for this district.")


# ========================== TAB 4: VALIDATION ==============================

with tab4:
    st.header("Validation")

    # --- Section 1: Backtest ---
    st.subheader("Historical shock alignment — does DARS rise during known crisis periods?")

    bt_df = safe_load(load_backtest, "Backtest")
    if bt_df is not None:
        # Grouped bar chart
        fig = go.Figure()

        events = bt_df["event_label"].unique()
        districts = bt_df["district"].unique()

        fig.add_trace(go.Bar(
            name="During event",
            x=[f"{row['event_label'].replace('_', ' ')}<br>{row['district']}"
               for _, row in bt_df.iterrows()],
            y=bt_df["mean_dars_during"],
            marker_color="#1F4E79",
            hovertemplate="%{x}<br>Mean DARS: %{y:.1f}<extra>During</extra>",
        ))

        fig.add_trace(go.Bar(
            name="Outside event",
            x=[f"{row['event_label'].replace('_', ' ')}<br>{row['district']}"
               for _, row in bt_df.iterrows()],
            y=bt_df["mean_dars_outside"],
            marker_color="#A9D18E",
            hovertemplate="%{x}<br>Mean DARS: %{y:.1f}<extra>Outside</extra>",
        ))

        fig.update_layout(
            barmode="group",
            yaxis_title="Mean DARS Score",
            height=500,
            margin=dict(t=40),
        )

        st.plotly_chart(fig, use_container_width=True)

        # Results table with highlighting
        st.subheader("Backtest Results")

        display_bt = bt_df[["event_label", "district", "signal_lift",
                            "high_risk_rate_during", "high_risk_rate_baseline",
                            "dars_comparability_flag"]].copy()
        display_bt.columns = ["Event", "District", "Signal Lift",
                              "High-Risk Rate (During)", "High-Risk Rate (Baseline)",
                              "Comparability Flag"]

        def highlight_lift(row):
            if pd.notna(row["Signal Lift"]) and row["Signal Lift"] > 1.2:
                return ["background-color: #d4edda"] * len(row)
            return [""] * len(row)

        styled = display_bt.style.apply(highlight_lift, axis=1).format(
            {"Signal Lift": "{:.3f}",
             "High-Risk Rate (During)": "{:.3f}",
             "High-Risk Rate (Baseline)": "{:.3f}"},
            na_rep="N/A"
        )
        st.dataframe(styled, hide_index=True, use_container_width=True)

        st.info(
            "Signal lift > 1.2 means DARS was at least 20% higher on average during the "
            "documented shock period than during non-shock months. Results are shown "
            "separately for districts with full component coverage and those missing the "
            "price component — these are not directly comparable."
        )

    # --- Section 2: Lead-lag diagnostic ---
    st.divider()
    st.subheader("Lead–lag diagnostic: does the risk signal move ahead of price volatility?")

    pred_df = safe_load(load_predictive, "Predictive signal")
    if pred_df is not None:
        # Pivot to show T+2 and T+3 side by side
        pred_t2 = pred_df[pred_df["lag_months"] == 2][["district", "pearson_r", "p_value"]].rename(
            columns={"pearson_r": "Correlation T+2", "p_value": "P-value T+2"}
        )
        pred_t3 = pred_df[pred_df["lag_months"] == 3][["district", "pearson_r", "p_value"]].rename(
            columns={"pearson_r": "Correlation T+3", "p_value": "P-value T+3"}
        )
        pred_merged = pred_t2.merge(pred_t3, on="district", how="outer")
        pred_merged.columns = ["District", "Correlation T+2", "P-value T+2",
                               "Correlation T+3", "P-value T+3"]

        st.dataframe(pred_merged, hide_index=True, use_container_width=True)

        st.caption(
            "A statistically significant positive correlation at T+2 or T+3 indicates "
            "the composite risk signal tends to move ahead of price instability by 2–3 "
            "months. This is a diagnostic check, not a forecast claim — it shows "
            "co-movement between the index and subsequent price behaviour, not a causal "
            "prediction."
        )


# ========================== TAB 5: IFRAD BULLETIN ==========================

with tab5:
    st.header("Current Month Risk Bulletin")

    bulletin_df = safe_load(load_bulletin, "Bulletin")
    if bulletin_df is not None:
        # Subheader with most recent date
        if "date" in bulletin_df.columns:
            latest_date = pd.to_datetime(bulletin_df["date"]).max()
            st.subheader(latest_date.strftime("%B %Y"))

        # District cards: 3 + 2 layout
        row1_cols = st.columns(3)
        row2_cols = st.columns(3)  # Use 3 cols but only fill 2
        all_cols = row1_cols + row2_cols

        for i, district_name in enumerate(PILOT_DISTRICTS):
            brow = bulletin_df[bulletin_df["district"] == district_name]
            if len(brow) == 0:
                continue
            brow = brow.iloc[0]

            with all_cols[i]:
                with st.container(border=True):
                    st.markdown(f"### {district_name}")

                    dars_val = brow.get("dars_score")
                    if pd.notna(dars_val):
                        st.markdown(f"<h1 style='margin:0; color:#1F4E79;'>{dars_val:.1f}</h1>",
                                    unsafe_allow_html=True)
                    else:
                        st.markdown("<h1 style='margin:0; color:grey;'>—</h1>",
                                    unsafe_allow_html=True)

                    hr = brow.get("high_risk_flag")
                    if pd.notna(hr) and hr == 1:
                        st.error("⬆ HIGH RISK")
                    elif pd.notna(hr) and hr == 0:
                        st.success("✓ NORMAL")
                    else:
                        st.warning("— INSUFFICIENT DATA")

                    threshold_val = brow.get("dars_threshold_75p")
                    if pd.notna(threshold_val):
                        st.caption(f"Threshold: {threshold_val:.1f}")

                    comp_flag = brow.get("dars_comparability_flag", "")
                    if pd.notna(comp_flag) and comp_flag:
                        st.caption(f"Flag: {comp_flag}")

                    action = brow.get("action_note", "")
                    if pd.notna(action) and action:
                        if pd.notna(hr) and hr == 1:
                            st.markdown(
                                f'<div style="background:#fce4e4; padding:10px; '
                                f'border-radius:5px; font-size:13px;">{action}</div>',
                                unsafe_allow_html=True,
                            )
                        elif pd.notna(hr) and hr == 0:
                            st.markdown(
                                f'<div style="background:#e4fce4; padding:10px; '
                                f'border-radius:5px; font-size:13px;">{action}</div>',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f'<div style="background:#f0f0f0; padding:10px; '
                                f'border-radius:5px; font-size:13px;">{action}</div>',
                                unsafe_allow_html=True,
                            )

        st.divider()

        st.download_button(
            label="Download Bulletin CSV",
            data=bulletin_df.to_csv(index=False),
            file_name="dars_bulletin_latest.csv",
            mime="text/csv",
        )

        st.caption(
            "This bulletin is generated from the DAVARS pipeline using data current "
            "to the date shown above. District scores flagged `missing_price_component` "
            "(Oyam, Nebbi) are computed from four of five index components and should be "
            "interpreted with this limitation in mind."
        )
