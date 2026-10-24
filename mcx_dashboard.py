"""MCX commodity dashboard helpers for the Streamlit app."""
import json
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import numpy as np

IST = ZoneInfo("Asia/Kolkata")
DB_URL_KEY = ("connections", "postgresql", "url")


def _read_mcx(symbol, limit=300):
    import psycopg2
    url = st.secrets[DB_URL_KEY[0]][DB_URL_KEY[1]][DB_URL_KEY[2]]
    with psycopg2.connect(url, connect_timeout=10) as con:
        df = pd.read_sql_query("""
          SELECT snapshot_time, trading_date, symbol, expiry_date, underlying_value,
                 row_count, summary_data, chain_data
          FROM mcx_option_chain_snapshots
          WHERE symbol=%s
          ORDER BY snapshot_time DESC LIMIT %s
        """, con, params=(symbol, int(limit)))
    if not df.empty:
        df["snapshot_time"] = pd.to_datetime(df["snapshot_time"], utc=True).dt.tz_convert(IST)
        df["trading_date"] = pd.to_datetime(df["trading_date"], errors="coerce").dt.date
    return df


@st.cache_data(ttl=600, show_spinner=False)
def load_mcx_latest(symbol):
    df = _read_mcx(symbol, 1)
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    raw = row.get("chain_data")
    if isinstance(raw, str): raw = json.loads(raw)
    if isinstance(raw, dict): raw = raw.get("Data", raw.get("data", []))
    chain = pd.DataFrame(raw or [])
    if chain.empty: return {"meta": row, "chain": chain}
    aliases = {
      "strikePrice": ["CE_StrikePrice", "PE_StrikePrice", "StrikePrice", "strikePrice"],
      "CE_OI": ["CE_OpenInterest", "CE_OI"],
      "CE_change_OI": ["CE_ChangeInOI", "CE_change_OI"],
      "CE_volume": ["CE_Volume", "CE_volume"],
      "CE_Premium": ["CE_LTP", "CE_Premium"],
      "PE_OI": ["PE_OpenInterest", "PE_OI"],
      "PE_change_OI": ["PE_ChangeInOI", "PE_change_OI"],
      "PE_volume": ["PE_Volume", "PE_volume"],
      "PE_Premium": ["PE_LTP", "PE_Premium"],
    }
    for dest, options in aliases.items():
        source = next((c for c in options if c in chain.columns), None)
        chain[dest] = pd.to_numeric(chain[source], errors="coerce") if source else np.nan
    chain["strikePrice"] = pd.to_numeric(chain["strikePrice"], errors="coerce")
    chain = chain.dropna(subset=["strikePrice"]).sort_values("strikePrice").drop_duplicates("strikePrice")
    spot = row.get("underlying_value")
    if spot is None or pd.isna(spot):
        for key in ["UnderlyingValue", "Underlying", "UnderlyingPrice", "SpotPrice", "underlyingValue"]:
            if key in pd.DataFrame(raw or []).columns:
                vals = pd.to_numeric(pd.DataFrame(raw)[key], errors="coerce").dropna()
                if not vals.empty: spot=float(vals.iloc[0]); break
    if spot is not None and not pd.isna(spot): chain["underlyingValue"] = float(spot)
    else: chain["underlyingValue"] = chain["strikePrice"].median()
    return {"meta": row, "chain": chain}


def _max_pain(chain):
    if chain.empty: return None, pd.DataFrame()
    strikes = np.sort(chain["strikePrice"].dropna().unique())
    calls = chain.groupby("strikePrice")["CE_OI"].sum(min_count=1).fillna(0)
    puts = chain.groupby("strikePrice")["PE_OI"].sum(min_count=1).fillna(0)
    rows=[]
    for settlement in strikes:
        call_pain=sum(max(0.0, settlement-k)*float(calls.get(k,0) or 0) for k in strikes)
        put_pain=sum(max(0.0, k-settlement)*float(puts.get(k,0) or 0) for k in strikes)
        rows.append((settlement, call_pain+put_pain))
    pain=pd.DataFrame(rows,columns=["strikePrice","totalPain"])
    return float(pain.loc[pain.totalPain.idxmin(),"strikePrice"]),pain


def render_mcx_commodity(symbol, label):
    st.subheader(f"{label} — MCX Option Chain")
    now = datetime.now(IST)
    if now.weekday() >= 5 or not (dt_time(9,0) <= now.time() <= dt_time(23,59)):
        st.caption("Outside the configured commodity session. Showing the latest stored snapshot, if available.")
    try:
        bundle = load_mcx_latest(symbol)
    except Exception as exc:
        st.error(f"Could not load MCX data from Supabase: {type(exc).__name__}: {exc}")
        return
    if not bundle:
        st.warning("No MCX snapshots found yet. Run the MCX collector and confirm the mcx_option_chain_snapshots table exists.")
        return
    meta, chain = bundle["meta"], bundle["chain"]
    stamp=meta.get("snapshot_time")
    st.caption(f"Source: MCX · Last saved snapshot: {stamp.strftime('%d-%b-%Y %H:%M:%S IST') if pd.notna(stamp) else '—'} · rows: {len(chain)}")
    if chain.empty:
        st.warning("A snapshot exists, but no strike rows could be parsed. Inspect the saved JSON response before relying on analytics.")
        with st.expander("Raw response summary"):
            st.json(meta.get("summary_data") or {})
        return
    spot=pd.to_numeric(chain["underlyingValue"],errors="coerce").dropna()
    spot=float(spot.iloc[0]) if not spot.empty else None
    strikes=chain["strikePrice"].dropna().unique()
    atm=float(min(strikes,key=lambda x:abs(x-spot))) if len(strikes) and spot is not None else (float(np.median(strikes)) if len(strikes) else None)
    atmrow=chain.loc[chain.strikePrice==atm].head(1)
    mp,pain=_max_pain(chain)
    ce_oi=chain.CE_OI.sum(min_count=1); pe_oi=chain.PE_OI.sum(min_count=1)
    cols=st.columns(6)
    metrics=[("Underlying", f"{spot:,.2f}" if spot is not None else "—"),
             ("Expiry", str(meta.get("expiry_date") or "—")),
             ("ATM Strike", f"{atm:,.2f}" if atm is not None else "—"),
             ("ATM CE Premium", f"{float(atmrow.CE_Premium.iloc[0]):,.2f}" if not atmrow.empty and pd.notna(atmrow.CE_Premium.iloc[0]) else "—"),
             ("ATM PE Premium", f"{float(atmrow.PE_Premium.iloc[0]):,.2f}" if not atmrow.empty and pd.notna(atmrow.PE_Premium.iloc[0]) else "—"),
             ("Max Pain", f"{mp:,.2f}" if mp is not None else "—")]
    for col,(name,value) in zip(cols,metrics): col.metric(name,value)
    c1,c2=st.columns(2)
    with c1:
        st.subheader("Open Interest by Strike")
        oi=chain[["strikePrice","CE_OI","PE_OI"]].copy()
        if atm is not None: oi=oi.iloc[np.argsort(np.abs(oi.strikePrice-atm))[:31]].sort_values("strikePrice")
        fig=go.Figure()
        fig.add_bar(x=oi.strikePrice,y=oi.CE_OI,name="Call OI")
        fig.add_bar(x=oi.strikePrice,y=oi.PE_OI,name="Put OI")
        fig.update_layout(barmode="group",height=380,xaxis_title="Strike Price",yaxis_title="Open Interest")
        st.plotly_chart(fig,use_container_width=True,key=f"{symbol}_oi")
    with c2:
        st.subheader("Change in OI by Strike")
        coi=chain[["strikePrice","CE_change_OI","PE_change_OI"]].copy()
        if atm is not None: coi=coi.iloc[np.argsort(np.abs(coi.strikePrice-atm))[:31]].sort_values("strikePrice")
        fig=go.Figure()
        fig.add_bar(x=coi.strikePrice,y=coi.CE_change_OI,name="Call Change OI")
        fig.add_bar(x=coi.strikePrice,y=coi.PE_change_OI,name="Put Change OI")
        fig.update_layout(barmode="group",height=380,xaxis_title="Strike Price",yaxis_title="Change in OI")
        st.plotly_chart(fig,use_container_width=True,key=f"{symbol}_coi")
    c3,c4=st.columns(2)
    with c3:
        st.subheader("Max Pain")
        if not pain.empty:
            if mp is not None:
                idx=int(np.argmin(np.abs(pain.strikePrice-mp)))
                pain=pain.iloc[max(0,idx-15):min(len(pain),idx+16)]
            fig=go.Figure(go.Bar(x=pain.strikePrice,y=pain.totalPain,name="Total Pain"))
            fig.add_vline(x=mp,line_color="red",line_dash="dash",annotation_text=f"Max Pain: {mp:,.2f}")
            fig.update_layout(height=350,xaxis_title="Strike Price",yaxis_title="Total Pain")
            st.plotly_chart(fig,use_container_width=True,key=f"{symbol}_maxpain")
    with c4:
        st.subheader("Option Chain")
        display=chain[[c for c in ["strikePrice","CE_OI","CE_change_OI","CE_volume","CE_Premium","PE_Premium","PE_volume","PE_change_OI","PE_OI"] if c in chain.columns]].copy()
        display=display.rename(columns={"strikePrice":"Strike","CE_OI":"CE OI","CE_change_OI":"CE Change OI","CE_volume":"CE Volume","CE_Premium":"CE LTP","PE_Premium":"PE LTP","PE_volume":"PE Volume","PE_change_OI":"PE Change OI","PE_OI":"PE OI"})
        st.dataframe(display,use_container_width=True,height=350,hide_index=True)
    st.caption(f"Total Call OI: {ce_oi:,.0f} · Total Put OI: {pe_oi:,.0f} · CE–PE OI difference: {ce_oi-pe_oi:,.0f}" if pd.notna(ce_oi) and pd.notna(pe_oi) else "Some OI fields are missing in the source response.")
