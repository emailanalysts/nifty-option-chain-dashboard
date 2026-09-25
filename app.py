import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from calculations import (
    prepare_chain,
    atm_strike,
    strike_wise_oi,
    max_pain,
    overall_oi,
    load_intraday_history,
    latest_saved_trading_date,
    previous_saved_trading_date,
    load_latest_snapshot_on_or_before,
    load_nifty_futures_history,
    load_buddy_dashboard_history,
    authenticate_dashboard_user,
    load_dashboard_users,
    load_dashboard_login_events,
    create_dashboard_user,
    set_dashboard_user_active,
)

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)


st.set_page_config(
    page_title="NSE Option Chain Dashboard",
    layout="wide"
)


st.markdown("""
<style>
html, body, [class*="css"] {
    font-size: 85% !important;
}

.stApp {
    font-size: 85% !important;
}

h1 {
    font-size: 1.8rem !important;
}

h2 {
    font-size: 1.45rem !important;
}

h3 {
    font-size: 1.2rem !important;
}

[data-testid="stMetricValue"] {
    font-size: 1.35rem !important;
}

[data-testid="stMetricLabel"] {
    font-size: 0.8rem !important;
}

[data-testid="stMetricDelta"] {
    font-size: 0.75rem !important;
}

button {
    font-size: 0.8rem !important;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# TIME FUNCTIONS
# ============================================================

def ist_now():
    return datetime.now(IST)


def market_hours(now):
    return (
        now.weekday() < 5
        and MARKET_OPEN <= now.time() <= MARKET_CLOSE
    )


# ============================================================
# DISPLAY DATE
# ============================================================

def choose_display_date(symbol, now):

    today = now.date().isoformat()

    latest = latest_saved_trading_date(symbol)

    if latest == today:
        return today

    return latest


# ============================================================
# LOAD DISPLAY DATA
# ============================================================

def load_display_data(symbol, now):

    target = choose_display_date(
        symbol,
        now
    )

    if not target:
        return pd.DataFrame(), None

    return (
        load_latest_snapshot_on_or_before(
            symbol,
            target
        ),
        target
    )


# ============================================================
# SNAPSHOT AGE
# ============================================================

def snapshot_age_minutes(symbol, now):

    target = choose_display_date(
        symbol,
        now
    )

    if not target:
        return None

    hist = load_intraday_history(
        symbol,
        target
    )

    if hist.empty:
        return None

    ts = hist["timestamp"].max()

    return max(
        0.0,
        (now - ts).total_seconds() / 60.0
    )


# ============================================================
# DASHBOARD TITLE
# ============================================================

def render_dashboard_title(now, nifty_date, bank_date):

    today = now.date().isoformat()

    # Green = today's live data
    # Red = previous/latest completed trading day
    live = (
        market_hours(now)
        and nifty_date == today
        and bank_date == today
    )

    if live:
        st.title("🟢 NSE Option Chain Dashboard")
    else:
        st.title("🔴 NSE Option Chain Dashboard")


# ============================================================
# MAIN DASHBOARD
# ============================================================

def render_dashboard():

    now = ist_now()

    # ---------------------------------------------------------
    # Load current / last available data
    # ---------------------------------------------------------

    nifty, nifty_date = load_display_data(
        "NIFTY",
        now
    )

    bank, bank_date = load_display_data(
        "BANKNIFTY",
        now
    )

    # ---------------------------------------------------------
    # Title + Refresh
    # ---------------------------------------------------------

    col_title, col_refresh = st.columns([8, 1])

    with col_title:

        render_dashboard_title(
            now,
            nifty_date,
            bank_date
        )

    with col_refresh:

        if st.button(
            "🔄 Refresh",
            use_container_width=True
        ):

            st.cache_data.clear()
            st.rerun()

    # ---------------------------------------------------------
    # No data available
    # ---------------------------------------------------------

    if nifty.empty or bank.empty:

        st.warning(
            "No option-chain snapshot is available in Supabase yet."
        )

        st.info(
            "The background collector will populate the dashboard "
            "automatically during NSE market hours."
        )

        return

    # ---------------------------------------------------------
    # Determine live mode
    # ---------------------------------------------------------

    today = now.date().isoformat()

    live = (
        market_hours(now)
        and nifty_date == today
        and bank_date == today
    )

    # =========================================================
    # COLLECTOR FRESHNESS
    # =========================================================

    if live:

        age_n = snapshot_age_minutes(
            "NIFTY",
            now
        )

        age_b = snapshot_age_minutes(
            "BANKNIFTY",
            now
        )

        if age_n is not None and age_b is not None:

            age = max(
                age_n,
                age_b
            )

            if age > 6:

                st.warning(
                    f"⚠️ Collector gap detected: latest "
                    f"NIFTY/BANKNIFTY snapshot is about "
                    f"{age:.1f} minutes old. "
                    "The chart is showing the last stored snapshot; "
                    "no values are being fabricated."
                )

    # =========================================================
    # NIFTY SUMMARY
    # =========================================================

    ne = nifty["expiryDate"].iloc[0]

    n1, n2, n3 = st.columns(3)

    n1.metric(
        "NIFTY Spot",
        f'{round(float(nifty["underlyingValue"].iloc[0])):,}'
    )

    n2.metric(
        "NIFTY Expiry",
        pd.Timestamp(ne).strftime("%d-%b-%Y")
    )

    n3.metric(
        "NIFTY Max Pain",
        f'{max_pain(nifty):,.0f}'
    )

    # =========================================================
    # BANKNIFTY SUMMARY
    # =========================================================

    be = bank["expiryDate"].iloc[0]

    b1, b2, b3 = st.columns(3)

    b1.metric(
        "BANKNIFTY Spot",
        f'{round(float(bank["underlyingValue"].iloc[0])):,}'
    )

    b2.metric(
        "BANKNIFTY Expiry",
        pd.Timestamp(be).strftime("%d-%b-%Y")
    )

    b3.metric(
        "BANKNIFTY Max Pain",
        f'{max_pain(bank):,.0f}'
    )

    # =========================================================
    # NIFTY ATM PREMIUM
    # =========================================================

    st.divider()

    st.subheader("NIFTY ATM Strike Premium")

    atm = atm_strike(nifty)

    row = nifty.loc[
        nifty["strikePrice"] == atm
    ].iloc[0]

    ce = float(row["CE_Premium"])
    pe = float(row["PE_Premium"])

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "ATM Strike",
        f"{atm:,.0f}"
    )

    c2.metric(
        "CE Premium",
        f"{ce:,.2f}"
    )

    c3.metric(
        "PE Premium",
        f"{pe:,.2f}"
    )

    c4.metric(
        "CE - PE Difference",
        f"{ce - pe:,.2f}"
    )

    # =========================================================
    # 1 & 3. COI + CE/PE OI — DUAL Y-AXIS
    # =========================================================

    for title, symbol in [
        ("1. NIFTY COI", "NIFTY"),
        ("3. NIFTY BANK COI", "BANKNIFTY"),
    ]:

        st.subheader(title)

        hist_date = choose_display_date(
            symbol,
            now
        )

        hist = (
            load_intraday_history(
                symbol,
                hist_date
            )
            if hist_date
            else pd.DataFrame()
        )

        fig = go.Figure()

        if not hist.empty:

            # -------------------------------------------------
            # PRIMARY Y-AXIS
            # Cumulative COI
            # -------------------------------------------------

            fig.add_trace(
                go.Scatter(
                    x=hist["timestamp"],
                    y=hist["cumulative_coi"],
                    mode="lines+markers",
                    name="Cumulative COI",
                    yaxis="y",
                )
            )

            # -------------------------------------------------
            # SECONDARY Y-AXIS
            # CE / PE OPEN INTEREST
            # -------------------------------------------------

            if symbol == "NIFTY":

                ce_name = "NIFTY CE OI"
                pe_name = "NIFTY PE OI"

            else:

                ce_name = "NIFTY BANK CE OI"
                pe_name = "NIFTY BANK PE OI"

            # CE OI — RED
            if "ce_oi" in hist.columns:

                fig.add_trace(
                    go.Scatter(
                        x=hist["timestamp"],
                        y=hist["ce_oi"],
                        mode="lines",
                        name=ce_name,
                        yaxis="y2",
                        line=dict(
                            color="red",
                            width=2
                        ),
                    )
                )

            # PE OI — GREEN
            if "pe_oi" in hist.columns:

                fig.add_trace(
                    go.Scatter(
                        x=hist["timestamp"],
                        y=hist["pe_oi"],
                        mode="lines",
                        name=pe_name,
                        yaxis="y2",
                        line=dict(
                            color="green",
                            width=2
                        ),
                    )
                )

        else:

            fig.add_annotation(
                text="No intraday COI history available.",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
            )

        # -----------------------------------------------------
        # DUAL Y-AXIS LAYOUT
        # -----------------------------------------------------

        fig.update_layout(

            height=400,

            xaxis=dict(
                title="Time",
            ),

            yaxis=dict(
                title="Cumulative COI",
                side="left",
            ),

            yaxis2=dict(
                title="Open Interest",
                overlaying="y",
                side="right",
                showgrid=False,
            ),

            hovermode="x unified",

            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
            ),
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            key=f"coi_chart_{symbol}",
        )

        # =====================================================
        # 2. NIFTY FUTURES — PRICE + VWAP
        # =====================================================

        if symbol == "NIFTY":

            st.subheader(
                "2. NIFTY Futures — Price & VWAP"
            )

            futures_date = choose_display_date(
                "NIFTY",
                now
            )

            futures_hist = (
                load_nifty_futures_history(
                    futures_date
                )
                if futures_date
                else pd.DataFrame()
            )

            fig_futures = go.Figure()

            if not futures_hist.empty:

                # -------------------------------------------------
                # NIFTY FUTURES PRICE
                # -------------------------------------------------

                fig_futures.add_trace(
                    go.Scatter(
                        x=futures_hist["timestamp"],
                        y=futures_hist["price"],
                        mode="lines",
                        name="NIFTY Futures",
                        line=dict(
                            color="blue",
                            width=2
                        ),
                    )
                )

                # -------------------------------------------------
                # VWAP
                # -------------------------------------------------

                fig_futures.add_trace(
                    go.Scatter(
                        x=futures_hist["timestamp"],
                        y=futures_hist["vwap"],
                        mode="lines",
                        name="VWAP",
                        line=dict(
                            color="orange",
                            width=2
                        ),
                    )
                )

            else:

                fig_futures.add_annotation(
                    text="No NIFTY futures data available.",
                    x=0.5,
                    y=0.5,
                    xref="paper",
                    yref="paper",
                    showarrow=False,
                )

            fig_futures.update_layout(

                height=450,

                xaxis=dict(
                    title="Time",
                ),

                yaxis=dict(
                    title="NIFTY Futures Price",
                ),

                hovermode="x unified",

                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="left",
                    x=0,
                ),
            )

            st.plotly_chart(
                fig_futures,
                use_container_width=True,
                key="nifty_futures_vwap_chart",
            )

    # =========================================================
    # 4. OVERALL OPEN INTEREST
    # =========================================================

    st.subheader("4. Overall Open Interest")

    oi = overall_oi(
        nifty,
        bank
    )

    fig = go.Figure()

    for name, x, s in [

        ("NIFTY CE", "NIFTY", "CE"),
        ("NIFTY PE", "NIFTY", "PE"),
        ("BANKNIFTY CE", "BANKNIFTY", "CE"),
        ("BANKNIFTY PE", "BANKNIFTY", "PE")

    ]:

        fig.add_trace(
            go.Bar(
                name=name,
                x=[x],
                y=[oi[x][s]]
            )
        )

    fig.update_layout(
        barmode="group",
        height=350,
        yaxis_title="Open Interest",
        hovermode="x unified"
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key="overall_oi_chart"
    )

    # =========================================================
    # 5 & 6. STRIKE PRICE-WISE OI — SIDE BY SIDE
    # =========================================================

    col1, col2 = st.columns(2)

    strike_oi_items = [

        (
            col1,
            "5. NIFTY Strike Price-wise OI",
            nifty,
            False,
            "strike_oi_chart_nifty"
        ),

        (
            col2,
            "6. NIFTY Bank Strike Price-wise OI",
            bank,
            True,
            "strike_oi_chart_banknifty"
        ),

    ]

    for col, title, data, orange, chart_key in strike_oi_items:

        with col:

            st.subheader(title)

            d = strike_wise_oi(
                data,
                10
            )

            fig = go.Figure()

            # CE OI
            fig.add_trace(
                go.Bar(
                    x=d.strikePrice,
                    y=d.CE_OI,
                    name="CE OI",
                    marker_color=(
                        "orange"
                        if orange
                        else None
                    ),
                )
            )

            # PE OI
            fig.add_trace(
                go.Bar(
                    x=d.strikePrice,
                    y=d.PE_OI,
                    name="PE OI",
                    marker_color=(
                        "moccasin"
                        if orange
                        else None
                    ),
                )
            )

            fig.update_layout(
                barmode="group",
                height=350,
                xaxis_title="Strike Price",
                yaxis_title="Open Interest",
                hovermode="x unified",
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key=chart_key,
            )

    # =========================================================
    # 7 & 8. MAX PAIN — SIDE BY SIDE
    # =========================================================

    col1, col2 = st.columns(2)

    max_pain_items = [

        (
            col1,
            "7. NIFTY Max Pain",
            nifty,
            "max_pain_chart_nifty"
        ),

        (
            col2,
            "8. BANKNIFTY Max Pain",
            bank,
            "max_pain_chart_banknifty"
        ),

    ]

    for col, title, data, chart_key in max_pain_items:

        with col:

            st.subheader(title)

            mp, pain = max_pain(
                data,
                True
            )

            pain = (
                pain
                .sort_values("strikePrice")
                .reset_index(drop=True)
            )

            idx = pain.index[
                pain.strikePrice == mp
            ][0]

            # 15 strikes before
            # + Max Pain
            # + 15 strikes after

            pain = pain.iloc[
                max(0, idx - 15):
                min(len(pain), idx + 16)
            ]

            fig = go.Figure()

            fig.add_trace(
                go.Bar(
                    x=pain.strikePrice,
                    y=pain.totalPain,
                    name="Total Pain"
                )
            )

            fig.add_vline(
                x=mp,
                line_dash="dash",
                line_color="red",
                annotation_text=f"Max Pain: {mp}",
                annotation_font_color="red"
            )

            fig.update_layout(
                height=350,
                xaxis_title="Strike Price",
                yaxis_title="Total Pain",
                hovermode="x unified",
                margin=dict(
                    l=45,
                    r=20,
                    t=40,
                    b=45
                )
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key=chart_key
            )

    # ============================================================
    # BUDDY ANALYSIS
    # ============================================================
    
    st.subheader("BUDDY Analysis")
    
    buddy_df = load_buddy_dashboard_history(limit=20)
    
    if buddy_df.empty:
        st.info("No BUDDY analysis snapshots available yet.")
    else:
        st.dataframe(
            buddy_df,
            use_container_width=True,
            hide_index=True
        )

# ============================================================
# AUTO REFRESH
# ============================================================

def login_screen():
    st.title("🔐 Dashboard Login")
    st.write("Please enter your username and password.")

    username = st.text_input("Username")
    password = st.text_input(
        "Password",
        type="password"
    )

    if st.button("Login", type="primary"):
        user = authenticate_dashboard_user(
            username,
            password
        )

        if user:
            st.session_state["authenticated"] = True
            st.session_state["dashboard_user"] = user
            st.rerun()
        else:
            st.error("Invalid username or password.")


if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False


if not st.session_state["authenticated"]:
    login_screen()
    st.stop()

# ============================================================
# ADMIN ACTIVITY
# ============================================================

if st.session_state.get("dashboard_user", {}).get("username") == "admin":

    with st.expander("🔐 Admin — User Activity"):

        st.subheader("➕ Create New User")

with st.form("create_dashboard_user_form"):

    new_username = st.text_input(
        "Username"
    )

    new_display_name = st.text_input(
        "Display Name"
    )

    new_password = st.text_input(
        "Password",
        type="password"
    )

    create_user_clicked = st.form_submit_button(
        "Create User"
    )

    if create_user_clicked:

        success, message = create_dashboard_user(
            new_username,
            new_display_name,
            new_password
        )

        if success:
            st.success(message)
            st.rerun()
        else:
            st.error(message)

        st.subheader("Dashboard Users")

        users_df = load_dashboard_users()

        if users_df.empty:
            st.info("No dashboard users found.")
        else:
            st.dataframe(
                users_df,
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("Recent Login Activity")

        login_df = load_dashboard_login_events(limit=100)

        if login_df.empty:
            st.info("No login activity found.")
        else:
            st.dataframe(
                login_df,
                use_container_width=True,
                hide_index=True,
            )

user = st.session_state.get("dashboard_user")

col1, col2 = st.columns([8, 1])

with col1:
    if user:
        st.caption(f"Logged in as: {user['display_name']}")

with col2:
    if st.button("Logout"):
        st.session_state["authenticated"] = False
        st.session_state.pop("dashboard_user", None)
        st.rerun()

@st.fragment(run_every="3m")
def auto_refresh_dashboard():
    render_dashboard()


auto_refresh_dashboard()
