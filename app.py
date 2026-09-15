import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from nse_data import fetch_option_chain
from calculations import prepare_chain, atm_strike, strike_wise_oi, max_pain, overall_oi, load_intraday_history, save_snapshot, latest_saved_trading_date, load_latest_snapshot_on_or_before

IST=ZoneInfo("Asia/Kolkata")
MARKET_OPEN=dt_time(9,15); MARKET_CLOSE=dt_time(15,30)
st.set_page_config(page_title="NSE Option Chain Dashboard", layout="wide")
st.markdown("""<style>html,body,[class*="css"]{font-size:85%!important}.stApp{font-size:85%!important}h1{font-size:1.8rem!important}h2{font-size:1.45rem!important}h3{font-size:1.2rem!important}[data-testid="stMetricValue"]{font-size:1.35rem!important}[data-testid="stMetricLabel"]{font-size:.8rem!important}[data-testid="stMetricDelta"]{font-size:.75rem!important}button{font-size:.8rem!important}</style>""",unsafe_allow_html=True)

def ist_now(): return datetime.now(IST)
def market_hours(now): return MARKET_OPEN <= now.time() <= MARKET_CLOSE

def completed_day_data(symbol):
    now=ist_now(); target=now.date().isoformat()
    if now.time() < MARKET_OPEN:
        # Before today's open, use the most recent prior saved day.
        last=latest_saved_trading_date(symbol)
        if last==target:
            with __import__('sqlite3').connect(__import__('calculations').DB) as con:
                row=con.execute("SELECT MAX(substr(timestamp,1,10)) FROM snapshots WHERE symbol=? AND substr(timestamp,1,10) < ?",(symbol,target)).fetchone()
            last=row[0] if row and row[0] else None
        target=last
    return load_latest_snapshot_on_or_before(symbol,target) if target else pd.DataFrame()

@st.cache_data(ttl=60)
def get_live_data(symbol): return prepare_chain(fetch_option_chain(symbol),symbol)

def render_dashboard():
    now=ist_now(); live=market_hours(now)
    if live:
        try: nifty=get_live_data("NIFTY"); bank=get_live_data("BANKNIFTY")
        except Exception as e: st.error(f"Unable to fetch NSE option-chain data: {e}"); st.stop()
        try: save_snapshot(nifty); save_snapshot(bank)
        except Exception as e: st.warning(f"Snapshot storage warning: {e}")
        data_label="LIVE • Market hours"
    else:
        nifty=completed_day_data("NIFTY"); bank=completed_day_data("BANKNIFTY"); data_label="PREVIOUS COMPLETED TRADING DAY • Market closed"
        if nifty.empty or bank.empty:
            st.warning("No completed trading-day snapshot is available yet. Open the dashboard during market hours to collect the first snapshot."); st.stop()

    col_title,col_refresh=st.columns([8,1])
    with col_title:
        st.title("NSE Option Chain Dashboard")
        st.caption(f"{data_label} • IST {now.strftime('%d-%b-%Y %H:%M:%S')} • Auto-refresh every 3 minutes during 09:15–15:30 IST")
    with col_refresh:
        if st.button("🔄 Refresh",use_container_width=True): st.cache_data.clear(); st.rerun()

    ne=nifty["expiryDate"].iloc[0]; be=bank["expiryDate"].iloc[0]
    n1,n2,n3=st.columns(3); n1.metric("NIFTY Spot",f'{round(float(nifty["underlyingValue"].iloc[0])):,}'); n2.metric("NIFTY Expiry",pd.Timestamp(ne).strftime("%d-%b-%Y")); n3.metric("NIFTY Max Pain",f'{max_pain(nifty):,.0f}')
    b1,b2,b3=st.columns(3); b1.metric("BANKNIFTY Spot",f'{round(float(bank["underlyingValue"].iloc[0])):,}'); b2.metric("BANKNIFTY Expiry",pd.Timestamp(be).strftime("%d-%b-%Y")); b3.metric("BANKNIFTY Max Pain",f'{max_pain(bank):,.0f}')
    st.divider(); st.subheader("NIFTY ATM Strike Premium")
    atm=atm_strike(nifty); row=nifty.loc[nifty["strikePrice"]==atm].iloc[0]; ce=float(row["CE_Premium"]); pe=float(row["PE_Premium"])
    c1,c2,c3,c4=st.columns(4); c1.metric("ATM Strike",f"{atm:,.0f}"); c2.metric("CE Premium",f"{ce:,.2f}"); c3.metric("PE Premium",f"{pe:,.2f}"); c4.metric("CE - PE Difference",f"{ce-pe:,.2f}")

    for title,symbol in [("1. NIFTY COI","NIFTY"),("2. NIFTY BANK COI","BANKNIFTY")]:
        st.subheader(title); hist=load_intraday_history(symbol) if live else load_intraday_history(symbol,latest_saved_trading_date(symbol)); fig=go.Figure()
        if not hist.empty: fig.add_trace(go.Scatter(x=hist.timestamp,y=hist.cumulative_coi,mode="lines+markers",name="COI"))
        else: fig.add_annotation(text="No intraday COI history available.",x=.5,y=.5,xref="paper",yref="paper",showarrow=False)
        fig.update_layout(height=400,xaxis_title="Time",yaxis_title="Cumulative COI",hovermode="x unified"); st.plotly_chart(fig,use_container_width=True)

    st.subheader("3. Overall Open Interest"); oi=overall_oi(nifty,bank); fig=go.Figure()
    for name,x,s in [("NIFTY CE","NIFTY","CE"),("NIFTY PE","NIFTY","PE"),("BANKNIFTY CE","BANKNIFTY","CE"),("BANKNIFTY PE","BANKNIFTY","PE")]: fig.add_trace(go.Bar(name=name,x=[x],y=[oi[x][s]]))
    fig.update_layout(barmode="group",height=450,yaxis_title="Open Interest",hovermode="x unified"); st.plotly_chart(fig,use_container_width=True)
    for title,data,orange in [("4. NIFTY Strike Price-wise OI",nifty,False),("5. NIFTY Bank Strike Price-wise OI",bank,True)]:
        st.subheader(title); d=strike_wise_oi(data,10); fig=go.Figure(); fig.add_trace(go.Bar(x=d.strikePrice,y=d.CE_OI,name="CE OI",marker_color="orange" if orange else None)); fig.add_trace(go.Bar(x=d.strikePrice,y=d.PE_OI,name="PE OI",marker_color="moccasin" if orange else None)); fig.update_layout(barmode="group",height=500,xaxis_title="Strike Price",yaxis_title="Open Interest",hovermode="x unified"); st.plotly_chart(fig,use_container_width=True)
    for title,data in [("6. NIFTY Max Pain",nifty),("7. NIFTY Bank Max Pain",bank)]:
        st.subheader(title); mp,pain=max_pain(data,True); pain=pain.sort_values("strikePrice").reset_index(drop=True); idx=pain.index[pain.strikePrice==mp][0]; pain=pain.iloc[max(0,idx-15):min(len(pain),idx+16)]; fig=go.Figure(); fig.add_trace(go.Bar(x=pain.strikePrice,y=pain.totalPain,name="Total Pain")); fig.add_vline(x=mp,line_dash="dash",line_color="red",annotation_text=f"Max Pain: {mp}",annotation_font_color="red"); fig.update_layout(height=450,xaxis_title="Strike Price",yaxis_title="Total Pain"); st.plotly_chart(fig,use_container_width=True)
    st.caption("09:15–15:30 IST: fresh NSE data and 3-minute refresh. Outside market hours: no NSE fetch; display the latest completed trading day's saved graphs and numbers. A new trading day starts a fresh COI series.")

if market_hours(ist_now()):
    @st.fragment(run_every="3m")
    def live_fragment(): render_dashboard()
    live_fragment()
else:
    render_dashboard()
