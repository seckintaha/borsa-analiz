"""
Streamlit panel (Aşama 0 + Aşama 1).

Çalıştırmak için proje kök klasöründe:
    pip install -r requirements.txt
    streamlit run app/panel.py

Sade ve net tutuldu: üstte arama, özet kartlar, grafik, dengeli özet, tarama.
Her sayının yanında kaynağı ve zaman damgası gösterilir.
"""

from __future__ import annotations
import sys, os

# Proje kokunu import yoluna ekle (app/ alt klasorunden calistirildigi icin)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from data.fetcher import fetch_history
from data.storage import init_db, save_prices
from analysis.indicators import add_indicators
from analysis.signals import evaluate
from analysis.screener import scan

st.set_page_config(page_title="Borsa Analiz Paneli", page_icon="📈", layout="wide")
init_db(config.DB_PATH)


@st.cache_data(ttl=300)
def _veri(sym, period, interval):
    fr = fetch_history(sym, period, interval)
    return fr  # FetchResult


def _grafik(df, sym):
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                        subplot_titles=(f"{sym} fiyat", "RSI", "MACD"))
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                  low=df["Low"], close=df["Close"], name="Fiyat"), row=1, col=1)
    for ad, renk in [("SMA20", "orange"), ("SMA50", "blue"), ("SMA200", "purple")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[ad], name=ad,
                      line=dict(width=1, color=renk)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                  line=dict(color="teal")), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD",
                  line=dict(color="blue")), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_sinyal"], name="Sinyal",
                  line=dict(color="orange")), row=3, col=1)
    fig.update_layout(height=720, xaxis_rangeslider_visible=False,
                      margin=dict(t=40, b=20))
    return fig


st.title("📈 Borsa Analiz Paneli")
st.caption("Global + BIST · Bilgilendirme amaçlıdır, yatırım tavsiyesi değildir.")

panel_sekme, tarama_sekme = st.tabs(["Panel", "Tarama"])

# ----------------------- PANEL -----------------------
with panel_sekme:
    with st.sidebar:
        st.header("Ayarlar")
        sym = st.text_input("Sembol", value="THYAO.IS",
                            help="BIST için sona .IS ekleyin (THYAO.IS). Global: AAPL")
        period = st.selectbox("Dönem", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
        interval = st.selectbox("Aralık", ["1d", "1wk", "1h"], index=0)

    sym = sym.strip().upper()
    fr = _veri(sym, period, interval)

    if not fr.ok:
        st.error(f"'{sym}' için veri alınamadı: {fr.note}")
        st.stop()

    # Veriyi sakla (kaynak + zaman damgasiyla)
    save_prices(config.DB_PATH, fr)

    df = add_indicators(fr.data)
    son = float(df["Close"].iloc[-1])
    onceki = float(df["Close"].iloc[-2])
    degisim = (son - onceki) / onceki * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("Son fiyat", f"{son:,.2f}", f"{degisim:+.2f}%")
    c2.metric("Dönem en yüksek", f"{float(df['High'].max()):,.2f}")
    c3.metric("Dönem en düşük", f"{float(df['Low'].min()):,.2f}")

    res = evaluate(df, thin_volume=config.SCREEN["thin_volume"])
    st.subheader(res.ozet)
    for n in res.notlar:
        st.write("• " + n)
    if res.ayi_senaryosu:
        st.markdown("**Ayı senaryosu (neden ters gidebilir):**")
        for a in res.ayi_senaryosu:
            st.write("– " + a)
    for b in res.bayraklar:
        st.warning(b)

    st.caption(f"Kaynak: {fr.source} · çekilme: {fr.fetched_at} · yatırım tavsiyesi değildir")
    st.plotly_chart(_grafik(df, sym), use_container_width=True)

# ----------------------- TARAMA -----------------------
with tarama_sekme:
    st.subheader("Gün sonu tarama — öne çıkanlar")
    st.caption(f"İzleme listesi: {len(config.WATCHLIST)} sembol")
    if st.button("Taramayı çalıştır"):
        with st.spinner("Taranıyor..."):
            rows = scan(config.WATCHLIST, config.SCREEN)
        tablo = []
        for r in rows:
            tablo.append({
                "Sembol": r.symbol,
                "Fiyat": r.son_fiyat if r.son_fiyat is not None else "—",
                "Değişim %": r.degisim_pct if r.degisim_pct is not None else "—",
                "Hacim x": r.hacim_kat if r.hacim_kat is not None else "—",
                "RSI": r.rsi if r.rsi is not None else "—",
                "Neden öne çıktı": ", ".join(r.gerekceler) if r.gerekceler else (r.not_ or "—"),
            })
        st.dataframe(pd.DataFrame(tablo), use_container_width=True, hide_index=True)
        st.caption("Gerekçesi olan satırlar üstte. 'Neden öne çıktı' boşsa o gün dikkat çeken bir durum yok.")
    else:
        st.info("Taramayı başlatmak için butona basın.")
