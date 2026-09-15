import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, time
from nse_data import fetch_option_chain
from calculations import (
    prepare_chain,
    atm_strike,
    strike_wise_oi,
    max_pain,
    overall_oi,
    current_coi,
    load_intraday_history,
    save_snapshot,
)

st.set_page_config(page_title="NSE Option Chain Dashboard", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] {
    font-size: 85% !important;
}
.stApp {
    font-size: 85% !important;
}
h1 { font-size: 1.8rem !important; }
h2 { font-size: 1.45rem !important; }
h3 { font-size: 1.2rem !important; }
[data-testid="stMetricValue"] { font-size: 1.35rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
[data-testid="stMetricDelta"] { font-size: 0.75rem !important; }
button { font-size: 0.8rem !important; }
</style>
""", unsafe_allow_html=True)

col_title, col_refresh = st.columns([8, 1])
with col_title:
    st.title("NSE Option Chain Dashboard")
    st.caption("Current-expiry charts: NIFTY and BANKNIFTY • Fresh data frame/session each trading day • Auto-refresh every 3 minutes")
with col_refresh:
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

@st.cache_data(ttl=60)
def get_data(symbol):
    raw = fetch_option_chain(symbol)
    return prepare_chain(raw, symbol)

@st.fragment(run_every="3m")
def live_dashboard():
    try:
        nifty = get_data("NIFTY")
        bank = get_data("BANKNIFTY")
    except Exception as e:
        st.error(f"Unable to fetch NSE option-chain data: {e}")
        st.stop()

    # Save current snapshot for intraday COI history.
    try:
        save_snapshot(nifty)
        save_snapshot(bank)
    except Exception as e:
        st.warning(f"Snapshot storage warning: {e}")

    nifty_expiry = nifty["expiryDate"].iloc[0]
    bank_expiry = bank["expiryDate"].iloc[0]

    n1, n2, n3 = st.columns(3)
    n1.metric("NIFTY Spot", f'{round(float(nifty["underlyingValue"].iloc[0])):,}')
    n2.metric("NIFTY Expiry", pd.Timestamp(nifty_expiry).strftime("%d-%b-%Y"))
    n3.metric("NIFTY Max Pain", f'{max_pain(nifty):,.0f}')

    b1, b2, b3 = st.columns(3)
    b1.metric("BANKNIFTY Spot", f'{round(float(bank["underlyingValue"].iloc[0])):,}')
    b2.metric("BANKNIFTY Expiry", pd.Timestamp(bank_expiry).strftime("%d-%b-%Y"))
    b3.metric("BANKNIFTY Max Pain", f'{max_pain(bank):,.0f}')

    st.divider()

    # ------------------------------------------------------------------
    # ATM CE / PE Premium
    # ------------------------------------------------------------------
    st.subheader("NIFTY ATM Strike Premium")

    atm = atm_strike(nifty)
    atm_row = nifty.loc[nifty["strikePrice"] == atm].iloc[0]

    # Premium = option LTP (last traded price).
    # The NSE parser supplies CE_Premium / PE_Premium from lastPrice.
    # Keep a clear error if an older cached dataset is still being used.
    if "CE_Premium" not in nifty.columns or "PE_Premium" not in nifty.columns:
        st.error(
            "CE/PE premium fields are missing. Please replace nse_data.py with the "
            "updated file and click Refresh."
        )
        st.stop()

    atm_ce_premium = float(atm_row["CE_Premium"])
    atm_pe_premium = float(atm_row["PE_Premium"])
    atm_premium_diff = atm_ce_premium - atm_pe_premium

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ATM Strike", f"{atm:,.0f}")
    c2.metric("CE Premium", f"{atm_ce_premium:,.2f}")
    c3.metric("PE Premium", f"{atm_pe_premium:,.2f}")
    c4.metric("CE - PE Difference", f"{atm_premium_diff:,.2f}")

    # ------------------------------------------------------------------
    # 1 & 2. COI
    # ------------------------------------------------------------------
    st.subheader("1. NIFTY COI")
    hist_n = load_intraday_history("NIFTY")
    fig = go.Figure()

    if not hist_n.empty:
        fig.add_trace(go.Scatter(
            x=hist_n["timestamp"],
            y=hist_n["cumulative_coi"],
            mode="lines+markers",
            name="NIFTY COI",
        ))
    else:
        fig.add_annotation(
            text="Intraday history will appear after snapshots are collected.",
            x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False
        )

    fig.update_layout(height=400, xaxis_title="Time", yaxis_title="Cumulative COI",
                      hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("2. NIFTY BANK COI")
    hist_b = load_intraday_history("BANKNIFTY")
    fig = go.Figure()

    if not hist_b.empty:
        fig.add_trace(go.Scatter(
            x=hist_b["timestamp"],
            y=hist_b["cumulative_coi"],
            mode="lines+markers",
            name="BANKNIFTY COI",
        ))
    else:
        fig.add_annotation(
            text="Intraday history will appear after snapshots are collected.",
            x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False
        )

    fig.update_layout(height=400, xaxis_title="Time", yaxis_title="Cumulative COI",
                      hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------------
    # 3. Overall OI
    # ------------------------------------------------------------------
    st.subheader("3. Overall Open Interest")
    oi = overall_oi(nifty, bank)

    fig = go.Figure()
    fig.add_trace(go.Bar(name="NIFTY CE", x=["NIFTY"], y=[oi["NIFTY"]["CE"]]))
    fig.add_trace(go.Bar(name="NIFTY PE", x=["NIFTY"], y=[oi["NIFTY"]["PE"]]))
    fig.add_trace(go.Bar(name="BANKNIFTY CE", x=["BANKNIFTY"], y=[oi["BANKNIFTY"]["CE"]]))
    fig.add_trace(go.Bar(name="BANKNIFTY PE", x=["BANKNIFTY"], y=[oi["BANKNIFTY"]["PE"]]))
    fig.update_layout(barmode="group", height=450, yaxis_title="Open Interest",
                      hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------------
    # 4 & 5. Strike-wise OI
    # ------------------------------------------------------------------
    st.subheader("4. NIFTY Strike Price-wise OI")
    df = strike_wise_oi(nifty, window=10)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["strikePrice"], y=df["CE_OI"], name="CE OI"))
    fig.add_trace(go.Bar(x=df["strikePrice"], y=df["PE_OI"], name="PE OI"))
    fig.update_layout(barmode="group", height=500, xaxis_title="Strike Price",
                      yaxis_title="Open Interest", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("5. NIFTY Bank Strike Price-wise OI")
    df = strike_wise_oi(bank, window=10)
    fig = go.Figure()
    # Match the orange / light-orange combination used for Overall Open Interest.
    fig.add_trace(go.Bar(
        x=df["strikePrice"],
        y=df["CE_OI"],
        name="CE OI",
        marker_color="orange"
    ))
    fig.add_trace(go.Bar(
        x=df["strikePrice"],
        y=df["PE_OI"],
        name="PE OI",
        marker_color="moccasin"
    ))
    fig.update_layout(barmode="group", height=500, xaxis_title="Strike Price",
                      yaxis_title="Open Interest", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------------
    # 6 & 7. Max Pain
    # ------------------------------------------------------------------
    st.subheader("6. NIFTY Max Pain")
    mp_n, pain_n = max_pain(nifty, return_table=True)
    # Show only 15 strikes before and 15 strikes after Max Pain, plus Max Pain itself.
    pain_n = pain_n.sort_values("strikePrice").reset_index(drop=True)
    mp_idx = pain_n.index[pain_n["strikePrice"] == mp_n][0]
    pain_n = pain_n.iloc[max(0, mp_idx - 15): min(len(pain_n), mp_idx + 16)]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=pain_n["strikePrice"], y=pain_n["totalPain"], name="Total Pain"))
    fig.add_vline(
        x=mp_n,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Max Pain: {mp_n}",
        annotation_font_color="red"
    )
    fig.update_layout(height=450, xaxis_title="Strike Price", yaxis_title="Total Pain")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("7. NIFTY Bank Max Pain")
    mp_b, pain_b = max_pain(bank, return_table=True)
    # Show only 15 strikes before and 15 strikes after Max Pain, plus Max Pain itself.
    pain_b = pain_b.sort_values("strikePrice").reset_index(drop=True)
    mp_idx = pain_b.index[pain_b["strikePrice"] == mp_b][0]
    pain_b = pain_b.iloc[max(0, mp_idx - 15): min(len(pain_b), mp_idx + 16)]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=pain_b["strikePrice"], y=pain_b["totalPain"], name="Total Pain"))
    fig.add_vline(
        x=mp_b,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Max Pain: {mp_b}",
        annotation_font_color="red"
    )
    fig.update_layout(height=450, xaxis_title="Strike Price", yaxis_title="Total Pain")
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "COI is built from intraday snapshots. Keep this dashboard running during market hours "
        "to build the current-session COI curve. OI and Max Pain use the latest current-expiry chain."
    )


live_dashboard()
