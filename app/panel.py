"""
Borsa Analiz Paneli
Çalıştır: streamlit run app/panel.py
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
from data.fetcher import fetch_many
from data.access import veri_getir
from data.storage import (
    init_db, save_prices,
    save_islem, load_portfolio, temizle_portfolio,
    save_tahmin, update_tahmin_gercek, load_tahminler, temizle_tahminler,
    load_watchlist, save_watchlist,
)
from analysis.indicators import add_indicators
from analysis.signals import evaluate
from analysis.screener import scan
from analysis.historical import olay_calismasi, mevsimsellik_aylik
from analysis.calibration import Tahmin, gercek_ekle, kalibre_et, genel_ozet
from analysis import risk
from analysis import macro
from analysis import news
from analysis import llm
from portfolio.paper import PaperPortfolio, cok_ufuklu_getiri
from backtest.engine import backtest, train_test_bol, strateji_sma_kesisim

st.set_page_config(
    page_title="Borsa Analiz",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB = config.DB_PATH
init_db(DB)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist(DB) or list(config.WATCHLIST)
if "portfolio" not in st.session_state:
    st.session_state.portfolio = load_portfolio(DB)
if "tahminler" not in st.session_state:
    st.session_state.tahminler = load_tahminler(DB)


# ── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _veri(sym: str, period: str, interval: str):
    # Canlı veri + DB önbellek yedeği + kalite/güncellik denetimi
    return veri_getir(DB, sym, period, interval,
                      db_yedek=config.VERI["db_yedek"],
                      max_deneme=config.VERI["max_deneme"],
                      bekleme_sn=config.VERI["bekleme_sn"],
                      bayat_gun=config.VERI["bayat_gun"],
                      bosluk_gun=config.VERI["bosluk_gun"])

@st.cache_data(ttl=300)
def _liste_ozet(wl_key: str) -> list[dict]:
    symbols = [s for s in wl_key.split(",") if s]
    results = fetch_many(symbols, period="3mo")
    rows = []
    for s, r in results.items():
        if not r.ok:
            rows.append({"Sembol": s, "Fiyat": "—", "Günlük %": "—",
                         "RSI": "—", "Trend": "—", "Durum": "⚠️ Veri yok"})
            continue
        df = add_indicators(r.data)
        son    = float(df["Close"].iloc[-1])
        onceki = float(df["Close"].iloc[-2])
        degisim = (son - onceki) / onceki * 100
        rsi   = df["RSI"].iloc[-1]
        sma20 = df["SMA20"].iloc[-1]
        sma50 = df["SMA50"].iloc[-1]
        trend = ("↑ Yukarı" if sma20 > sma50 else "↓ Aşağı") \
                if (pd.notna(sma20) and pd.notna(sma50)) else "—"
        durum = ("🔴 Aşırı alım" if rsi >= 70 else
                 "🟢 Aşırı satım" if rsi <= 30 else "⚪ Nötr") \
                if pd.notna(rsi) else "—"
        rows.append({"Sembol": s, "Fiyat": f"{son:,.2f}",
                     "Günlük %": f"{degisim:+.2f}%",
                     "RSI": f"{rsi:.0f}" if pd.notna(rsi) else "—",
                     "Trend": trend, "Durum": durum})
    return rows

@st.cache_data(ttl=900)
def _piyasa_ozeti(piyasa: str) -> pd.DataFrame:
    """Günlük / haftalık / aylık değişimi hesaplar, sıralı DataFrame döndürür."""
    symbols = config.PIYASA_BIST if piyasa == "BIST" else config.PIYASA_GLOBAL
    results = fetch_many(symbols, period="1mo")
    rows = []
    for s, r in results.items():
        if not r.ok or len(r.data) < 5:
            continue
        c = r.data["Close"].astype(float)
        son = float(c.iloc[-1])
        gunluk  = (son - float(c.iloc[-2])) / float(c.iloc[-2]) * 100
        haftalik = (son - float(c.iloc[-6])) / float(c.iloc[-6]) * 100 \
                   if len(c) >= 6 else None
        aylik   = (son - float(c.iloc[0]))  / float(c.iloc[0])  * 100
        rows.append({
            "Sembol":    s,
            "Fiyat":     f"{son:,.2f}",
            "_gunluk":   gunluk,
            "_haftalik": haftalik,
            "_aylik":    aylik,
            "Günlük %":  f"{gunluk:+.2f}%",
            "Haftalık %": f"{haftalik:+.2f}%" if haftalik is not None else "—",
            "Aylık %":   f"{aylik:+.2f}%",
        })
    return pd.DataFrame(rows)

def _grafik(df: pd.DataFrame, sym: str) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
        subplot_titles=(f"{sym} — Fiyat ve Hareketli Ortalamalar", "RSI (14)", "MACD"),
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="Fiyat",
    ), row=1, col=1)
    for ad, renk in [("SMA20", "#f59e0b"), ("SMA50", "#3b82f6"), ("SMA200", "#8b5cf6")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[ad], name=ad,
                      line=dict(width=1.3, color=renk)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                  line=dict(color="#14b8a6", width=1.5)), row=2, col=1)
    for y, c in [(70, "rgba(239,68,68,0.5)"), (30, "rgba(34,197,94,0.5)")]:
        fig.add_hline(y=y, line_dash="dot", line_color=c, row=2, col=1)
    hist = df["MACD"] - df["MACD_sinyal"]
    fig.add_trace(go.Bar(x=df.index, y=hist, name="Histogram",
                  marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in hist]),
                  row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD",
                  line=dict(color="#3b82f6", width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_sinyal"], name="Sinyal",
                  line=dict(color="#f97316", width=1.5)), row=3, col=1)
    fig.update_layout(height=680, xaxis_rangeslider_visible=False,
                      margin=dict(t=30, b=10, l=0, r=0),
                      legend=dict(orientation="h", y=1.02),
                      plot_bgcolor="white")
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    return fig


# ── Kenar çubuğu ─────────────────────────────────────────────────────────────

watchlist = st.session_state.watchlist

with st.sidebar:
    st.title("📈 Borsa Analiz")
    st.divider()

    # ── Hisse seç ──────────────────────────────────────────────────────────
    st.subheader("🔍 Hisse Seç")
    OZEL = "✏️  Özel sembol gir..."
    secenekler = watchlist + [OZEL]
    secim = st.selectbox("İzleme listenizden seçin", secenekler,
                         help="Listede yoksa en alttaki 'Özel sembol gir' seçeneğini kullanın")
    if secim == OZEL:
        ozel_sym = st.text_input("Sembol yazın",
                                 placeholder="Ör: BIMAS.IS  |  AMZN  |  TSLA",
                                 help="BIST hisseleri için sona .IS ekleyin (THYAO.IS)")
        sym = ozel_sym.strip().upper() if ozel_sym.strip() else ""
    else:
        sym = secim

    st.divider()

    # ── İzleme listesi yönetimi ─────────────────────────────────────────────
    with st.expander("📝 İzleme Listesini Düzenle"):
        st.caption("Mevcut listeniz:")
        if watchlist:
            cols = st.columns(2)
            for i, s in enumerate(watchlist):
                if cols[i % 2].button(f"❌ {s}", key=f"cikar_{s}", use_container_width=True):
                    watchlist.remove(s)
                    save_watchlist(DB, watchlist)
                    st.session_state.watchlist = watchlist
                    st.rerun()
        else:
            st.info("Liste boş.")

        st.divider()
        st.caption("Popüler hisselerden ekleyin:")

        for kategori, hisseler in config.POPULER_HISSELER.items():
            with st.expander(kategori):
                cols = st.columns(2)
                kat_slug = kategori.replace(" ", "_").replace("—", "").replace("&", "")
                for i, h in enumerate(hisseler):
                    zaten_var = h in watchlist
                    etiket = f"✅ {h}" if zaten_var else f"➕ {h}"
                    if cols[i % 2].button(etiket, key=f"ekle_{kat_slug}_{h}",
                                          use_container_width=True,
                                          disabled=zaten_var):
                        watchlist.append(h)
                        save_watchlist(DB, watchlist)
                        st.session_state.watchlist = watchlist
                        st.rerun()

        st.divider()
        st.caption("Listede olmayan sembol ekleyin:")
        yeni = st.text_input("Sembol", placeholder="Ör: HEKTS.IS", key="wl_ozel_ekle")
        if st.button("➕ Ekle", use_container_width=True, key="wl_ozel_btn"):
            s = yeni.strip().upper()
            if s and s not in watchlist:
                watchlist.append(s)
                save_watchlist(DB, watchlist)
                st.session_state.watchlist = watchlist
                st.rerun()
            elif s in watchlist:
                st.warning(f"{s} zaten listede.")

    st.divider()
    st.subheader("⚙️ Grafik Ayarları")
    donem_map    = {"1 Ay": "1mo", "3 Ay": "3mo", "6 Ay": "6mo",
                    "1 Yıl": "1y", "2 Yıl": "2y", "5 Yıl": "5y"}
    aralik_map   = {"Günlük": "1d", "Haftalık": "1wk"}
    period       = donem_map[st.selectbox("Dönem",  list(donem_map.keys()), index=3)]
    interval     = aralik_map[st.selectbox("Aralık", list(aralik_map.keys()), index=0)]
    st.divider()
    st.caption("Veri kaynağı: Yahoo Finance (yfinance)")
    st.caption("Her 5 dakikada bir güncellenir.")
    st.caption("⚠️ Yatırım tavsiyesi değildir.")


# ── Veri yükle ────────────────────────────────────────────────────────────────

fr = _veri(sym, period, interval) if sym else None
df = None
if fr and fr.ok:
    save_prices(DB, fr)
    df = add_indicators(fr.data)


# ── Sekmeler ──────────────────────────────────────────────────────────────────

(tab_panel, tab_liste, tab_piyasa, tab_rejim, tab_haber, tab_ai, tab_portfoy,
 tab_backtest, tab_tarihsel, tab_kalibrasyon,
 tab_risk, tab_otomasyon, tab_ogren) = st.tabs([
    "📊 Hisse Detayı",
    "📋 İzleme Listesi",
    "🔥 Piyasa Özeti",
    "🌐 Piyasa Rejimi",
    "📰 Haber & KAP",
    "🤖 AI Sentez",
    "💼 Sanal Portföy",
    "🔬 Strateji Testi",
    "📅 Tarihsel Analiz",
    "🎯 Tahmin Takibi",
    "⚠️ Risk Hesaplama",
    "⏰ Otomasyon",
    "📚 Gösterge Rehberi",
])


# ══════════════════════════════════════════════════════════════════════════════
# 📊 HİSSE DETAYI
# ══════════════════════════════════════════════════════════════════════════════
with tab_panel:
    if not sym:
        st.info("👈 Sol taraftan bir hisse seçin veya sembol yazın.")
    elif not fr or not fr.ok:
        st.error(f"**'{sym}'** için veri alınamadı.")
        if fr: st.markdown(f"> {fr.note}")
        st.markdown("""
**Olası nedenler:**
- BIST hisseleri için sembolün sonuna **.IS** ekleyin → `THYAO.IS`
- Sembolün doğru yazıldığından emin olun (büyük harf)
- [finance.yahoo.com](https://finance.yahoo.com) üzerinden sembolü doğrulayın
        """)
    else:
        son     = float(df["Close"].iloc[-1])
        onceki  = float(df["Close"].iloc[-2])
        degisim = (son - onceki) / onceki * 100
        rsi_son = df["RSI"].iloc[-1]

        st.markdown(f"## {sym}")
        _kaynak_ad = "Yahoo Finance (yfinance)" if fr.source == "yfinance" else fr.source
        st.caption(
            f"Kaynak: {_kaynak_ad} · "
            f"{fr.meta.get('satir', 0)} günlük veri · "
            f"Temettü/bölünme düzeltmeli · "
            f"Son veri: {fr.meta.get('son_tarih', fr.fetched_at[:10])}"
        )
        if fr.bayat:
            st.warning("⏳ Bu veri güncel olmayabilir (bayat) — "
                       "delisting, tatil ya da durmuş veri akışı olabilir.")
        for _u in getattr(fr, "uyarilar", []):
            st.caption("⚠️ " + _u)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Son Fiyat",        f"{son:,.2f}", f"{degisim:+.2f}%")
        c2.metric("Dönem En Yüksek",  f"{float(df['High'].max()):,.2f}")
        c3.metric("Dönem En Düşük",   f"{float(df['Low'].min()):,.2f}")
        c4.metric("RSI (14)",         f"{rsi_son:.1f}" if pd.notna(rsi_son) else "—",
                  help="14 günlük RSI. 70 ve üzeri aşırı alım, 30 ve altı aşırı satım.")

        res = evaluate(df, thin_volume=config.SCREEN["thin_volume"])
        renk = {"Göstergeler ağırlıklı pozitif": "🟢",
                "Göstergeler ağırlıklı negatif": "🔴"}.get(res.ozet, "🟡")
        st.markdown(f"### {renk} {res.ozet}")

        col_n, col_a = st.columns(2)
        with col_n:
            st.markdown("**Teknik gösterge notları**")
            for n in res.notlar:
                st.write(f"• {n}")
        with col_a:
            if res.ayi_senaryosu:
                st.markdown("**Dikkat — neden ters gidebilir?**")
                for a in res.ayi_senaryosu:
                    st.write(f"– {a}")
        for b in res.bayraklar:
            st.warning(b)

        st.plotly_chart(_grafik(df, sym), use_container_width=True)

        with st.expander("📐 Bollinger Bantları detayı"):
            bb_u = df["BB_ust"].iloc[-1]
            bb_a = df["BB_alt"].iloc[-1]
            if pd.notna(bb_u):
                b1, b2, b3 = st.columns(3)
                b1.metric("Üst Bant",   f"{bb_u:,.2f}")
                b2.metric("Son Fiyat",  f"{son:,.2f}")
                b3.metric("Alt Bant",   f"{bb_a:,.2f}")
                if son > bb_u:
                    st.warning("Fiyat üst bandın üzerinde — aşırı alım bölgesi olabilir.")
                elif son < bb_a:
                    st.success("Fiyat alt bandın altında — aşırı satım bölgesi olabilir.")
                else:
                    st.info("Fiyat bantlar arasında — nötr bölge.")
            st.caption("Bollinger bantları nedir? 📚 Gösterge Rehberi sekmesine bakın.")

        st.caption("Bilgilendirme amaçlıdır. Yatırım tavsiyesi değildir.")


# ══════════════════════════════════════════════════════════════════════════════
# 📋 İZLEME LİSTESİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_liste:
    st.markdown("## 📋 İzleme Listesi")
    st.caption(
        f"{len(watchlist)} hisse · 3 aylık veri · "
        "Her 5 dakikada bir güncellenir · Yatırım tavsiyesi değildir"
    )

    if not watchlist:
        st.info("👈 Sol taraftaki 'İzleme Listesini Düzenle' bölümünden hisse ekleyin.")
    else:
        with st.spinner("Veriler yükleniyor..."):
            wl_key = ",".join(watchlist)
            ozet_rows = _liste_ozet(wl_key)

        st.dataframe(
            pd.DataFrame(ozet_rows),
            use_container_width=True, hide_index=True, height=400,
        )

        with st.expander("Durum sütunları ne anlama gelir?"):
            col1, col2, col3 = st.columns(3)
            col1.markdown("🔴 **Aşırı alım**\nRSI ≥ 70 → Fiyat hızlı yükseldi, düzeltme gelebilir")
            col2.markdown("🟢 **Aşırı satım**\nRSI ≤ 30 → Fiyat hızlı düştü, toparlanma gelebilir")
            col3.markdown("⚪ **Nötr**\nRSI 30–70 arası, belirgin sinyal yok")
            st.markdown("**↑ Yukarı trend:** SMA20 > SMA50 — kısa vadeli momentum yukarı yönlü")
            st.markdown("**↓ Aşağı trend:** SMA20 < SMA50 — kısa vadeli momentum aşağı yönlü")
            st.caption("Detaylı açıklamalar için 📚 Gösterge Rehberi sekmesine bakın.")


# ══════════════════════════════════════════════════════════════════════════════
# 🔥 PİYASA ÖZETİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_piyasa:
    st.markdown("## 🔥 Piyasa Özeti")
    st.caption("Günlük, haftalık ve aylık performans sıralaması · Yahoo Finance verileri")

    p_col1, p_col2 = st.columns([1, 3])
    with p_col1:
        piyasa_sec = st.radio("Piyasa", ["BIST", "Global"], horizontal=False)
    with p_col2:
        donem_sec = st.radio("Dönem", ["Günlük", "Haftalık", "Aylık"], horizontal=True)

    donem_kolon = {"Günlük": "_gunluk", "Haftalık": "_haftalik", "Aylık": "_aylik"}[donem_sec]
    donem_gorsel = {"Günlük": "Günlük %", "Haftalık": "Haftalık %", "Aylık": "Aylık %"}[donem_sec]

    with st.spinner(f"{piyasa_sec} verileri çekiliyor..."):
        df_piyasa = _piyasa_ozeti(piyasa_sec)

    if df_piyasa.empty:
        st.warning("Veri alınamadı. Lütfen bir süre sonra tekrar deneyin.")
    else:
        df_piyasa = df_piyasa.dropna(subset=[donem_kolon])
        df_sira   = df_piyasa.sort_values(donem_kolon, ascending=False)

        # ── En çok artan / azalan kartlar ─────────────────────────────────
        col_art, col_az = st.columns(2)

        with col_art:
            st.markdown(f"### 📈 En Çok Artan — {donem_sec}")
            top5 = df_sira.head(5)
            for _, row in top5.iterrows():
                val = row[donem_kolon]
                st.metric(
                    label=row["Sembol"],
                    value=row["Fiyat"],
                    delta=f"{val:+.2f}%",
                )

        with col_az:
            st.markdown(f"### 📉 En Çok Azalan — {donem_sec}")
            bot5 = df_sira.tail(5).iloc[::-1]
            for _, row in bot5.iterrows():
                val = row[donem_kolon]
                st.metric(
                    label=row["Sembol"],
                    value=row["Fiyat"],
                    delta=f"{val:+.2f}%",
                )

        # ── Tüm hisseler tablosu ───────────────────────────────────────────
        st.divider()
        st.markdown(f"### Tüm {piyasa_sec} Hisseleri — {donem_sec} Performansı")

        goster_kolon = ["Sembol", "Fiyat", "Günlük %", "Haftalık %", "Aylık %"]
        st.dataframe(
            df_sira[goster_kolon].reset_index(drop=True),
            use_container_width=True, hide_index=True,
        )

        st.caption(
            f"Kaynak: Yahoo Finance · {len(df_sira)} hisse · "
            "Haftalık = son 5 işlem günü · Aylık = son ~21 işlem günü"
        )
        st.caption("⚠️ Yatırım tavsiyesi değildir. Veriler bilgilendirme amaçlıdır.")


# ══════════════════════════════════════════════════════════════════════════════
# 💼 SANAL PORTFÖY
# ══════════════════════════════════════════════════════════════════════════════
with tab_portfoy:
    st.markdown("## 💼 Sanal Portföy")
    st.caption(
        "Gerçek para işlemi yapılmaz. Gerçek piyasa fiyatlarıyla sanal alım-satım. "
        "Komisyon (%0.2) ve kayma (%0.1) maliyeti dahildir."
    )

    p = st.session_state.portfolio
    guncel_f = float(df["Close"].iloc[-1]) if (fr and fr.ok) else None
    gf = {sym: guncel_f} if (guncel_f and sym) else {}
    ozet = p.ozet(gf)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Başlangıç Sermayesi", f"{ozet['baslangic']:,.0f} ₺")
    c2.metric("Nakit",               f"{ozet['nakit']:,.0f} ₺")
    c3.metric("Toplam Değer",        f"{ozet['guncel_deger']:,.0f} ₺")
    c4.metric("Toplam Getiri",       f"{ozet['getiri_pct']:+.2f}%")

    if p.pozisyonlar:
        st.divider()
        st.markdown("### Açık Pozisyonlar")
        poz_rows = []
        for s, poz in p.pozisyonlar.items():
            g = gf.get(s)
            if g:
                kz_pct = (g - poz.alis_fiyat) / poz.alis_fiyat * 100
                kz_tl  = (g - poz.alis_fiyat) * poz.adet
                durum  = "✅ Kârda" if kz_pct >= 0 else "🔴 Zararda"
            else:
                kz_pct = kz_tl = None
                durum  = "—"
            poz_rows.append({
                "Sembol":       s,
                "Adet":         round(poz.adet, 2),
                "Alış Fiyatı":  round(poz.alis_fiyat, 2),
                "Güncel Fiyat": f"{g:,.2f}" if g else "—",
                "Kâr/Zarar %":  f"{kz_pct:+.2f}%" if kz_pct is not None else "—",
                "Kâr/Zarar ₺":  f"{kz_tl:+,.0f} ₺" if kz_tl is not None else "—",
                "Durum":        durum,
                "Alış Tarihi":  poz.alis_tarih,
            })
        st.dataframe(pd.DataFrame(poz_rows), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Alım İşlemi")
    ca1, ca2, ca3 = st.columns([2, 2, 1])
    with ca1:
        al_sym   = st.text_input("Sembol", value=sym or "",
                                 key="al_sym", placeholder="Ör: THYAO.IS")
        al_fiyat = st.number_input("Fiyat (₺)", min_value=0.01,
                                   value=guncel_f or 1.0, step=0.01, key="al_fiyat")
    with ca2:
        al_tutar = st.number_input(
            "Tutar (₺)", min_value=100.0,
            value=float(config.INITIAL_CAPITAL * config.RISK["pozisyon_pct"]),
            step=100.0, key="al_tutar",
            help=f"Önerilen: sermayenin %{config.RISK['pozisyon_pct']*100:.0f}'i",
        )
        al_gerekce = st.text_input("Gerekçe (isteğe bağlı)", key="al_gerekce",
                                   placeholder="Ör: RSI 28 — aşırı satım")
    with ca3:
        st.write(""); st.write("")
        if st.button("✅ Satın Al", use_container_width=True):
            try:
                tarih   = pd.Timestamp.now().date().isoformat()
                s_upper = al_sym.strip().upper()
                adet    = p.al(s_upper, al_fiyat, tarih,
                               tutar=al_tutar, gerekce=al_gerekce)
                save_islem(DB, s_upper, "AL", tarih, al_fiyat,
                           adet, al_tutar, al_gerekce)
                st.success(f"{adet:.2f} adet {s_upper} alındı.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    if p.pozisyonlar:
        st.markdown("### Satış İşlemi")
        cs1, cs2, cs3 = st.columns([2, 2, 1])
        with cs1:
            sat_sym   = st.selectbox("Pozisyon seçin",
                                     list(p.pozisyonlar.keys()), key="sat_sym")
        with cs2:
            sat_fiyat = st.number_input("Satış Fiyatı (₺)", min_value=0.01,
                                        value=guncel_f or 1.0, step=0.01, key="sat_fiyat")
        with cs3:
            st.write(""); st.write("")
            if st.button("🔴 Sat", use_container_width=True):
                try:
                    tarih     = pd.Timestamp.now().date().isoformat()
                    adet_once = p.pozisyonlar[sat_sym].adet
                    gelir     = p.sat(sat_sym, sat_fiyat, tarih)
                    save_islem(DB, sat_sym, "SAT", tarih, sat_fiyat,
                               adet_once, gelir)
                    st.success(f"Satıldı — elde edilen: {gelir:,.2f} ₺")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        if fr and fr.ok and p.islemler:
            st.divider()
            st.markdown("### Farklı Vadeler İçin Getiri")
            st.caption("İlk alım tarihinden itibaren hissenin farklı sürelerdeki performansı")
            try:
                getiriler = cok_ufuklu_getiri(
                    fr.data["Close"], p.islemler[0].tarih, config.HORIZONS,
                )
                g_rows = [
                    {"Vade": ufuk,
                     "Getiri": f"{v['getiri_pct']:+.2f}%" if v.get("getiri_pct") is not None else "Veri yok",
                     "Tarih": v.get("tarih") or "—"}
                    for ufuk, v in getiriler.items()
                ]
                st.dataframe(pd.DataFrame(g_rows), use_container_width=True, hide_index=True)
            except Exception:
                st.info("Hesaplanamadı — giriş tarihi seçilen dönem dışında olabilir.")

    if p.islemler:
        with st.expander(f"📜 İşlem Geçmişi ({len(p.islemler)} işlem)"):
            islem_rows = [
                {"Tarih": i.tarih, "Sembol": i.symbol, "Yön": i.yon,
                 "Fiyat": round(i.fiyat, 2), "Adet": round(i.adet, 2),
                 "Tutar": round(i.tutar, 2), "Gerekçe": i.gerekce}
                for i in p.islemler
            ]
            st.dataframe(pd.DataFrame(islem_rows), use_container_width=True, hide_index=True)

    st.divider()
    if st.button("🗑️ Portföyü Sıfırla (kalıcı)", type="secondary"):
        temizle_portfolio(DB)
        st.session_state.portfolio = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# 🔬 STRATEJİ TESTİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown("## 🔬 Strateji Testi (Backtest)")

    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown("""
Seçtiğiniz hisse üzerinde **geçmişte bir strateji uygulasaydınız ne olurdu?**
sorusunu gerçek verilerle yanıtlar.

**Kullanılan strateji:** 50 günlük ortalama, 200 günlük ortalamanın üstüne çıktığında al;
altına düştüğünde sat (SMA Kesişim Stratejisi).

**Neden iki bölüme ayrılır?**
- **Eğitim dönemi:** Stratejinin geliştirildiği dönem. Bu dönemde iyi görünmesi yanıltıcı olabilir.
- **Test dönemi:** Stratejinin hiç görmediği veriler üzerindeki gerçek performansı.

**Karşılaştırma (benchmark):** Basit al-ve-tut stratejisi. Çoğu aktif strateji
uzun vadede bunu geçemez — bu sektörde bilinen bir gerçektir.
        """)

    if not sym:
        st.info("👈 Sol taraftan bir hisse seçin.")
    elif not fr or not fr.ok:
        st.warning(f"Veri alınamadı: {fr.note if fr else ''}")
    else:
        if len(df) < 210:
            st.warning(
                f"Veri az ({len(df)} gün). SMA200 hesabı için en az 210 gün önerilir. "
                "Sonuçlar güvenilmez olabilir."
            )

        test_orani = st.slider(
            "Test dönemi oranı",
            0.1, 0.5, 0.3, 0.05,
            help="Verinin bu kadarı test için ayrılır. %30 = son 3 yılın 1 yılı",
        )
        egitim, test = train_test_bol(df, test_orani)
        r_e = backtest(egitim, strateji_sma_kesisim, costs=config.COSTS)
        r_t = backtest(test,   strateji_sma_kesisim, costs=config.COSTS)

        col_e, col_t = st.columns(2)
        for col, r, baslik in [
            (col_e, r_e, f"Eğitim Dönemi ({r_e.gun_sayisi} gün)"),
            (col_t, r_t, f"Test Dönemi — Gerçek Ölçüt ({r_t.gun_sayisi} gün)"),
        ]:
            with col:
                st.markdown(f"**{baslik}**")
                m1, m2 = st.columns(2)
                m1.metric("Strateji Getirisi",  f"{r.getiri_pct:+.1f}%")
                m2.metric("Al-Tut Getirisi",    f"{r.benchmark_pct:+.1f}%")
                st.metric("Fark",               f"{r.fark_pct:+.1f}%")
                st.metric("Maksimum Düşüş",     f"{r.max_dusus_pct:.1f}%",
                          help="Zirve noktasından en derin düşüşe kadar olan kayıp")
                st.metric("Sharpe Oranı",       f"{r.sharpe:.2f}",
                          help="Risk başına getiri. 1'in üzeri iyi, negatif kötü")
                st.metric("İşlem Sayısı",       r.islem_sayisi)

        st.info(
            "ℹ️ Fark negatifse strateji basit al-tutu geçemiyor. "
            "Bu çok yaygındır ve dürüst bir sonuçtur. "
            "Geçmişteki performans geleceği garanti etmez."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 📅 TARİHSEL ANALİZ
# ══════════════════════════════════════════════════════════════════════════════
with tab_tarihsel:
    st.markdown("## 📅 Tarihsel Analiz")

    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown("""
**'Bu hisse benzer durumlarda nasıl davranmış?'** sorusunu gerçek geçmiş veriyle yanıtlar.

Örnek: *"THYAO günde %8 ve üzeri yükseldiğinde, sonraki 5–20 günde ne olmuş?"*

**Dikkat edilmesi gerekenler:**
- Örnek sayısı az (n < 10) ise sonuçlar güvenilmezdir — "Güvenilir" sütununu mutlaka kontrol edin.
- Korelasyon nedensellik değildir. "Ocak'ta yükselmiş" = "bu yıl Ocak'ta yükselecek" demek değildir.
- Geçmiş performans geleceği garanti etmez.
        """)

    if not sym:
        st.info("👈 Sol taraftan bir hisse seçin.")
    elif not fr or not fr.ok:
        st.warning(f"Veri alınamadı: {fr.note if fr else ''}")
    else:
        esik = st.slider(
            "Günlük sıçrama eşiği (%)",
            1.0, 15.0,
            float(config.HISTORICAL["sicrama_esigi_pct"]), 0.5,
            help="Bu yüzdenin üzerinde yükselen günler analiz edilir",
        )
        dag = olay_calismasi(fr.data, esik_pct=esik,
                             ileri_gun=config.HISTORICAL["ileri_gun"])
        st.markdown(f"### {sym}: Günde %{esik:.0f}+ Yükseliş Sonrası Ne Olmuş?")

        rows = []
        for ufuk, d in dag.items():
            if d.n == 0:
                rows.append({
                    "Süre": f"{ufuk} gün sonra", "Örnek Sayısı": 0,
                    "Medyan": "—", "Ortalama": "—", "En Az": "—", "En Fazla": "—",
                    "Pozitif Oran": "—", "Güvenilir": "❌ Hayır", "Not": d.not_,
                })
            else:
                rows.append({
                    "Süre":          f"{ufuk} gün sonra",
                    "Örnek Sayısı":  d.n,
                    "Medyan":        f"{d.medyan_pct:+.1f}%",
                    "Ortalama":      f"{d.ortalama_pct:+.1f}%",
                    "En Az":         f"{d.min_pct:+.1f}%",
                    "En Fazla":      f"{d.max_pct:+.1f}%",
                    "Pozitif Oran":  f"{d.pozitif_orani:.0%}",
                    "Güvenilir":     "✅ Evet" if d.guvenilir else "⚠️ Az örnek",
                    "Not":           d.not_ or "",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Aylık Mevsimsellik")
        st.caption("Hangi ay tarihsel olarak daha iyi performans göstermiş? (En az 2 yıl veri önerilir)")
        try:
            mvs = mevsimsellik_aylik(fr.data)
            if not mvs.empty:
                st.dataframe(mvs, use_container_width=True)
            else:
                st.info("Yeterli veri yok. Daha uzun bir dönem seçmeyi deneyin.")
        except Exception:
            st.info("Mevsimsellik hesaplanamadı. Yeterli veri olmayabilir.")

        st.caption("⚠️ Az örnek = güvenilmez. Geçmiş performans geleceği garanti etmez.")


# ══════════════════════════════════════════════════════════════════════════════
# 🎯 TAHMİN TAKİBİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_kalibrasyon:
    st.markdown("## 🎯 Tahmin Takibi")
    st.caption("Tahminleriniz kalıcı olarak kaydedilir. Sayfa kapansa da silinmez.")

    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown("""
**Kendi alım-satım tahminlerinizi kaydetmeniz ve isabetinizi ölçmeniz için bir not defteri.**

Nasıl çalışır:
1. "Bu hisse 14 gün içinde yükselir" gibi bir tahmin yapın
2. Tahmininizi buraya kaydedin
3. 14 gün sonra gerçekleşeni girin
4. Sistem isabetinizi hesaplar ve **yazı-tura (%50)** ile karşılaştırır

**Neden önemli?** Çoğu insan isabetli tahminlerini hatırlar, hatalılarını unutur.
Bu sekme gerçekçi bir özdeğerlendirme yapmanıza yardımcı olur.
        """)

    tahminler = st.session_state.tahminler

    with st.expander("➕ Yeni Tahmin Kaydet", expanded=not bool(tahminler)):
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            k_sym  = st.text_input("Sembol", value=sym or "", key="k_sym")
            k_yon  = st.selectbox("Tahmin yönü",
                                  ["Yükselir (pozitif)", "Düşer (negatif)"],
                                  key="k_yon")
            k_yon_val = "pozitif" if "pozitif" in k_yon else "negatif"
        with ck2:
            k_sinyal = st.text_input("Sinyal türü",
                                     value="SMA_kesisim",
                                     placeholder="Ör: RSI_dusuk, MACD_yukari",
                                     key="k_sinyal",
                                     help="Bu tahmini yaparken hangi göstergeyi kullandınız?")
            k_ufuk = st.number_input("Kaç gün içinde?",
                                     min_value=1, value=14, key="k_ufuk")
        with ck3:
            k_tarih = st.text_input("Tahmin tarihi",
                                    value=pd.Timestamp.now().date().isoformat(),
                                    key="k_tarih")
        if st.button("Tahmini Kaydet", type="primary"):
            t     = Tahmin(k_sym.strip().upper(), k_tarih, k_yon_val, k_sinyal, int(k_ufuk))
            db_id = save_tahmin(DB, t)
            t.db_id = db_id
            st.session_state.tahminler.append(t)
            st.success("Tahmin kaydedildi. Süre dolunca 'Gerçekleşeni Gir' bölümünden güncelleyin.")
            st.rerun()

    if not tahminler:
        st.info("Henüz kaydedilmiş tahmin yok. Yukarıdan ekleyebilirsiniz.")
    else:
        bekleyenler = [(i, t) for i, t in enumerate(tahminler)
                       if t.gerceklesen_pct is None]
        if bekleyenler:
            st.divider()
            st.markdown("### Gerçekleşeni Gir")
            st.caption("Süresi dolan tahminler için gerçekleşen fiyat değişimini girin")
            secenekler = {
                f"{t.symbol} — {t.yon} — {t.sinyal_tipi} ({t.tarih}, {t.ufuk_gun}g)": (i, t)
                for i, t in bekleyenler
            }
            secim_k    = st.selectbox("Hangi tahmin?", list(secenekler.keys()), key="k_secim")
            gercek_pct = st.number_input("Gerçekleşen fiyat değişimi (%)",
                                         step=0.1, key="k_gercek",
                                         help="Ör: +5.3 veya -2.1")
            if st.button("Kaydet", type="primary"):
                idx, t = secenekler[secim_k]
                update_tahmin_gercek(DB, t.db_id, gercek_pct)
                st.session_state.tahminler[idx] = gercek_ekle(t, gercek_pct)
                st.success("Kaydedildi.")
                st.rerun()

        sonuclar = kalibre_et(tahminler, min_ornek=10)
        if sonuclar:
            st.divider()
            st.markdown("### İsabet Analizi")
            st.caption("Yazı-tura (%50) temel alınır — üstündeyseniz sinyaliniz değer katıyor")
            k_rows = [
                {
                    "Sinyal Türü":    s.sinyal_tipi,
                    "Tahmin Sayısı":  s.n,
                    "İsabet Oranı":   f"%{s.isabet_orani*100:.0f}" if s.isabet_orani is not None else "—",
                    "Yazı-Tura Farkı": f"{s.yazitura_farki:+.3f}" if s.yazitura_farki is not None else "—",
                    "Güvenilir":      "✅ Evet" if s.guvenilir else "⚠️ Henüz az örnek",
                    "Not":            s.not_ or "",
                }
                for s in sonuclar
            ]
            st.dataframe(pd.DataFrame(k_rows), use_container_width=True, hide_index=True)

        with st.expander(f"📋 Tüm Tahminler ({len(tahminler)})"):
            t_rows = [
                {
                    "Sembol": t.symbol, "Tarih": t.tarih, "Yön": t.yon,
                    "Sinyal": t.sinyal_tipi, "Süre": f"{t.ufuk_gun} gün",
                    "Sonuç": (f"{t.gerceklesen_pct:+.1f}%"
                              if t.gerceklesen_pct is not None else "⏳ Bekleniyor"),
                }
                for t in tahminler
            ]
            st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)

        if st.button("🗑️ Tüm Tahminleri Sil (kalıcı)", type="secondary"):
            temizle_tahminler(DB)
            st.session_state.tahminler = []
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ RİSK HESAPLAMA
# ══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown("## ⚠️ Risk Hesaplama")
    st.caption(
        f"Ayarlar: Tek pozisyon max %{config.RISK['pozisyon_pct']*100:.0f} · "
        f"Yoğunlaşma uyarısı %{config.RISK['yogunlasma_uyari_pct']*100:.0f} · "
        f"Zarar durdur %{abs(config.RISK['stop_loss_pct'])*100:.0f}"
    )

    st.markdown("### Bu Hisseden Kaç TL Almalıyım?")
    st.caption(
        "Tek bir pozisyona sermayenizin belirli bir yüzdesini koymanız "
        "riski yayar. Varsayılan: sermayenin %10'u."
    )
    cr1, cr2 = st.columns(2)
    with cr1:
        r_sermaye = st.number_input("Toplam Sermayeniz (₺)", min_value=1_000.0,
                                    value=float(config.INITIAL_CAPITAL), step=1_000.0)
    with cr2:
        varsayilan = float(df["Close"].iloc[-1]) if (fr and fr.ok) else 100.0
        r_fiyat = st.number_input("Hisse Fiyatı (₺)", min_value=0.01,
                                  value=varsayilan, step=0.01)

    pb = risk.pozisyon_buyuklugu(r_sermaye, r_fiyat, config.RISK["pozisyon_pct"])
    cm1, cm2, cm3 = st.columns(3)
    cm1.metric("Tahsis Edilecek Tutar",  f"{pb['tahsis_tutar']:,.0f} ₺")
    cm2.metric("Alınabilecek Adet",      str(pb["adet"]))
    cm3.metric("Gerçek Tahsis",          f"{pb['gercek_tutar']:,.0f} ₺")

    p = st.session_state.portfolio
    if p.pozisyonlar:
        fiyatlar_bilinen = {sym: float(df["Close"].iloc[-1])} \
                           if (fr and fr.ok and sym) else {}
        poz_deg = {
            s: poz.adet * fiyatlar_bilinen.get(s, poz.alis_fiyat)
            for s, poz in p.pozisyonlar.items()
        }

        col_y, col_s = st.columns(2)
        with col_y:
            st.markdown("### Yoğunlaşma Kontrolü")
            st.caption("Tek hisse portföyünüzün çok büyük bir kısmını oluşturmamalıdır")
            uyarilar = risk.yogunlasma_kontrol(poz_deg, config.RISK["yogunlasma_uyari_pct"])
            for u in uyarilar:
                st.warning(u)
            if not uyarilar:
                st.success("✅ Yoğunlaşma riski yok.")

        with col_s:
            st.markdown("### Zarar Durdur Kontrolü")
            st.caption(f"Alış fiyatından %{abs(config.RISK['stop_loss_pct'])*100:.0f} "
                       "düşüş yaşanırsa uyarı verilir")
            poz_dict      = {s: {"alis_fiyat": poz.alis_fiyat}
                             for s, poz in p.pozisyonlar.items()}
            stop_uyarilar = risk.stop_loss_kontrol(
                poz_dict, fiyatlar_bilinen, config.RISK["stop_loss_pct"],
            )
            for u in stop_uyarilar:
                st.error(u)
            if not stop_uyarilar:
                st.success("✅ Zarar durdur seviyesi aşılmadı.")
    else:
        st.info("💡 Sanal Portföy sekmesinden pozisyon eklenince burada yoğunlaşma "
                "ve zarar durdur analizi görünür.")

    st.divider()
    st.markdown("### Hisseler Arası Korelasyon")
    st.caption(
        "İzleme listenizdeki hisseler ne kadar birbirine bağlı hareket ediyor? "
        "Yüksek korelasyon = çeşitlendirme etkisi azalır."
    )
    if st.button("Korelasyonu Hesapla (ilk 6 hisse)"):
        with st.spinner("Veriler çekiliyor..."):
            results = fetch_many(watchlist[:6], period="3mo")
        gecerli = {s: r.data["Close"].rename(s)
                   for s, r in results.items() if r.ok}
        if len(gecerli) >= 2:
            fiyat_df = pd.concat(list(gecerli.values()), axis=1).dropna()
            corr     = risk.korelasyon_matrisi(fiyat_df)
            st.dataframe(corr, use_container_width=True)
            st.caption(
                "1.00 = tam aynı yönde hareket · "
                "0.00 = birbirinden bağımsız · "
                "-1.00 = tam ters yönde hareket"
            )
        else:
            st.warning("En az 2 hisse için veri gerekiyor.")


# ══════════════════════════════════════════════════════════════════════════════
# 📚 GÖSTERGE REHBERİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_ogren:
    st.markdown("## 📚 Gösterge Rehberi")
    st.caption("Bu sekme yatırım tavsiyesi vermez — göstergelerin ne anlama geldiğini açıklar.")

    with st.expander("📈 Hareketli Ortalamalar (SMA20 · SMA50 · SMA200)", expanded=True):
        st.markdown("""
**Ne işe yarar?** Son N günün kapanış fiyatlarının ortalamasını alır.
Günlük dalgalanmaları yumuşatarak genel trendi görmeyi sağlar.

| Gösterge | Hesap | Ne gösterir |
|----------|-------|-------------|
| SMA20 | Son 20 günün ortalaması | Kısa vadeli eğilim |
| SMA50 | Son 50 günün ortalaması | Orta vadeli eğilim |
| SMA200 | Son 200 günün ortalaması | Uzun vadeli eğilim |

**Sık kullanılan sinyaller:**
- **Altın Kesişim:** SMA50, SMA200'ün *üstüne* çıkarsa → uzun vadeli yükseliş eğilimi başladı
- **Ölüm Kesişimi:** SMA50, SMA200'ün *altına* inerse → uzun vadeli düşüş eğilimi başladı

⚠️ **Önemli:** Bu sinyaller *gecikmeli* çalışır. Fiyat zaten hareket etmiştir.
Tek başına yeterli değildir.
        """)

    with st.expander("📊 RSI — Göreceli Güç Endeksi"):
        st.markdown("""
**Ne işe yarar?** Son 14 günde fiyatın ne kadar hızlı ve hangi yönde değiştiğini ölçer.
0 ile 100 arasında değer alır.

| Değer | Anlam |
|-------|-------|
| 70 ve üzeri | **Aşırı alım** — Fiyat hızlı yükseldi, kısa vadede düzeltme gelebilir |
| 30 ile 70 arası | **Nötr** — Belirgin sinyal yok |
| 30 ve altı | **Aşırı satım** — Fiyat hızlı düştü, kısa vadede toparlanma gelebilir |

⚠️ **Önemli:** "Aşırı alım" direkt "sat" sinyali değildir. Güçlü yükseliş trendlerinde
RSI uzun süre 70 üzerinde kalabilir.
        """)

    with st.expander("📉 MACD"):
        st.markdown("""
**Ne işe yarar?** İki farklı hızda hareketli ortalama arasındaki farkı ölçerek
momentumun yönünü gösterir.

- **MACD çizgisi:** 12 günlük üstel ortalama eksi 26 günlük üstel ortalama
- **Sinyal çizgisi:** MACD'nin 9 günlük üstel ortalaması
- **Histogram:** MACD ile Sinyal arasındaki fark

**Nasıl okunur:**
- MACD, sinyal çizgisinin *üstüne* çıkarsa → Kısa vadeli momentum yukarı döndü
- MACD, sinyal çizgisinin *altına* inerse → Kısa vadeli momentum aşağı döndü
- Histogram sıfırı yukarı geçerse → Alım sinyali (sıfırı aşağı geçerse satım)

⚠️ MACD da gecikmeli bir göstergedir. RSI ve fiyat hareketiyle birlikte kullanılmalıdır.
        """)

    with st.expander("📐 Bollinger Bantları"):
        st.markdown("""
**Ne işe yarar?** Fiyatın istatistiksel olarak "normal" hareket aralığını gösterir.

- **Orta bant:** 20 günlük hareketli ortalama (SMA20)
- **Üst bant:** SMA20 + 2 standart sapma
- **Alt bant:** SMA20 − 2 standart sapma

Tarihsel verilere göre fiyatların yaklaşık %95'i bantlar arasında kalır.

**Nasıl okunur:**
- Fiyat üst banda ulaşırsa → Olası aşırı alım bölgesi
- Fiyat alt banda ulaşırsa → Olası aşırı satım bölgesi
- Bantlar daraldığında → Düşük oynaklık dönemi; genellikle büyük bir hareket öncesinde görülür
        """)

    with st.expander("🚀 Paneli Nasıl Kullanmalıyım? — Adım Adım Başlangıç"):
        st.markdown("""
**1. Başlangıç:**
İzleme listesine takip etmek istediğiniz hisseleri ekleyin
(Sol menü → İzleme Listesini Düzenle).

**2. Günlük kontrol:**
- **Piyasa Özeti** sekmesinde günlük en çok artanlar ve azalanlar
- **İzleme Listesi** sekmesinde portföyünüzdeki hisselerin durumu

**3. Hisse inceleme:**
- **Hisse Detayı** sekmesinde grafik, RSI, MACD ve sinyal özeti
- Grafik üzerinde SMA20/50/200 kesişimlerine bakın
- Bollinger bantlarında fiyatın konumuna bakın

**4. Geçmişi anlama:**
- **Tarihsel Analiz** sekmesinde "Bu hisse benzer durumlarda ne yapmış?"
- Aylık mevsimsellik tablosuna bakın

**5. Strateji test etme:**
- **Strateji Testi** sekmesinde SMA kesişim stratejisini gerçek veriyle test edin

**6. Kendinizi ölçün:**
- **Tahmin Takibi** sekmesinde tahminlerinizi kaydedin ve isabetinizi takip edin

---
**Altın kural:** Hiçbir gösterge tek başına yeterli değildir.
Birden fazla gösterge aynı yönü işaret ediyorsa sinyal daha anlamlıdır.

*Bu panel bilgilendirme amaçlıdır. Yatırım tavsiyesi değildir.*
        """)

    st.info(
        "💡 Her sekmede 'Bu sekme ne işe yarar?' bölümünü açın — "
        "o sekmenin amacı ve nasıl kullanılacağı orada açıklanıyor."
    )


# ── Aşama 4/6/7 için yardımcılar ──────────────────────────────────────────────

@st.cache_data(ttl=600)
def _rejim_veri(endeks: str):
    return veri_getir(DB, endeks, period="2y", interval="1d",
                      db_yedek=config.VERI["db_yedek"],
                      bayat_gun=config.VERI["bayat_gun"])

@st.cache_data(ttl=600)
def _coklu_close(wl_key: str) -> dict:
    symbols = [s for s in wl_key.split(",") if s]
    out = {}
    for s, r in fetch_many(symbols, period="6mo").items():
        if r.ok and r.data is not None:
            out[s] = r.data["Close"]
    return out

@st.cache_data(ttl=600)
def _hisse_haber(symbol: str, limit: int):
    return news.hisse_haberleri(symbol, limit=limit)

@st.cache_data(ttl=600)
def _piyasa_haber(rss_key: str, limit: int):
    return news.piyasa_akisi(dict(config.HABER["rss_feeds"]), limit=limit)


# ══════════════════════════════════════════════════════════════════════════════
# 🌐 PİYASA REJİMİ (Aşama 7)
# ══════════════════════════════════════════════════════════════════════════════
with tab_rejim:
    st.markdown("## 🌐 Piyasa Rejimi")
    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown(
            "Tek hisseden önce **piyasanın genel havasını** okur. Boğa "
            "piyasasında zayıf hisse bile taşınır; ayı piyasasında güçlü hisse "
            "bile satılır. Endeksin trendini ve oynaklığını sınıflar — gelecek "
            "tahmini değil, **mevcut durumun** dürüst etiketidir."
        )

    endeks = config.MACRO["rejim_endeksi"]
    st.caption(f"Rejim endeksi: {endeks} · 2 yıllık veri · Yatırım tavsiyesi değildir")
    fr_e = _rejim_veri(endeks)
    if not fr_e.ok or fr_e.data is None:
        st.error(f"Rejim endeksi alınamadı: {fr_e.note}")
    else:
        r = macro.rejim_tespit(
            fr_e.data,
            oynaklik_penceresi=config.MACRO["oynaklik_penceresi"],
            yatay_band_pct=config.MACRO["yatay_band_pct"],
            yuksek_oynaklik_p=config.MACRO["yuksek_oynaklik_p"],
            dusuk_oynaklik_p=config.MACRO["dusuk_oynaklik_p"],
        )
        if r.rejim == "belirsiz":
            st.warning(r.not_)
        else:
            renk = {"Boğa": "🟢", "Ayı": "🔴", "Yatay": "🟡"}.get(r.rejim, "⚪")
            st.markdown(f"### {renk} {r.rejim} · oynaklık: {r.oynaklik}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Fiyat", f"{r.fiyat:,.0f}")
            m2.metric("50g ort.", f"{r.sma50:,.0f}" if r.sma50 else "—")
            m3.metric("200g ort.", f"{r.sma200:,.0f}" if r.sma200 else "—")
            m4.metric("Zirveden", f"{r.zirveden_dusus_pct:+.1f}%"
                      if r.zirveden_dusus_pct is not None else "—")
            st.markdown("**Gerekçeler**")
            for n in r.notlar:
                st.write(f"• {n}")

        # Piyasa genişliği (breadth) — izleme listesi üzerinden
        if watchlist:
            with st.spinner("Piyasa genişliği hesaplanıyor..."):
                closes = _coklu_close(",".join(watchlist))
            g = macro.piyasa_genisligi(closes, pencere=50)
            if g["oran"] is not None:
                st.markdown("---")
                st.markdown(
                    f"**Piyasa genişliği:** {g['ustte']}/{g['toplam']} hisse "
                    f"50 günlük ortalamasının üzerinde (%{g['oran']*100:.0f})"
                )
                st.caption(
                    "Geniş katılım (çoğu hisse ortalamasının üstünde) sağlıklı "
                    "yükseliş işaretidir; az hisseyle yükselen piyasa kırılgandır."
                )
    st.caption("Bilgilendirme amaçlıdır. Yatırım tavsiyesi değildir.")


# ══════════════════════════════════════════════════════════════════════════════
# 📰 HABER & KAP (Aşama 4)
# ══════════════════════════════════════════════════════════════════════════════
with tab_haber:
    st.markdown("## 📰 Haber & KAP")
    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown(
            "Seçili hissenin **son haberlerini** (yfinance) ve config'e "
            "eklediğiniz **RSS/KAP akışlarını** gösterir. Her haber kaynağa ve "
            "yayın zamanına bağlıdır; veri yoksa açıkça belirtilir. Haberler ham "
            "bilgidir, hiçbiri yatırım tavsiyesi değildir."
        )

    st.markdown(f"### {sym or '—'} ile ilgili haberler" if sym else "### Hisse haberleri")
    if not sym:
        st.info("👈 Sol taraftan bir hisse seçin.")
    else:
        with st.spinner("Haberler çekiliyor..."):
            hs = _hisse_haber(sym, config.HABER["hisse_basina_limit"])
        if not hs.ok:
            st.warning(hs.not_)
        else:
            for h in hs.kayitlar:
                zaman = (h.zaman or "")[:16].replace("T", " ")
                _link = h.link if news._http_url_mu(h.link or "") else ""
                baslik = f"[{h.baslik}]({_link})" if _link else h.baslik
                st.markdown(f"**{baslik}**")
                st.caption(f"{h.kaynak} · {zaman}")

    st.markdown("---")
    st.markdown("### Genel piyasa / KAP akışı")
    if not config.HABER["rss_feeds"]:
        st.info(
            "RSS akışı yapılandırılmamış. `config.py` içindeki "
            "`HABER['rss_feeds']` sözlüğüne ad: URL ekleyin "
            "(örn. KAP veya bir finans haber RSS adresi)."
        )
    else:
        with st.spinner("Akış çekiliyor..."):
            ps = _piyasa_haber(",".join(config.HABER["rss_feeds"]),
                               config.HABER["rss_basina_limit"])
        if not ps.ok:
            st.warning(ps.not_)
        else:
            if ps.not_:
                st.caption("⚠️ " + ps.not_)
            for h in ps.kayitlar:
                zaman = (h.zaman or "")[:16].replace("T", " ")
                _link = h.link if news._http_url_mu(h.link or "") else ""
                baslik = f"[{h.baslik}]({_link})" if _link else h.baslik
                st.markdown(f"**{baslik}**")
                st.caption(f"{h.kaynak} · {zaman}")
    st.caption("Haberler ham bilgidir; doğruluğu garanti edilmez, tavsiye değildir.")


# ══════════════════════════════════════════════════════════════════════════════
# 🤖 AI SENTEZ (Aşama 6)
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown("## 🤖 AI Sentez")
    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown(
            "Diğer sekmelerin **zaten hesapladığı** sayıları (sinyal, tarihsel "
            "oranlar, piyasa rejimi, kalibrasyon, haber başlıkları) Claude'a "
            "verip dengeli bir Türkçe özete çevirir. Model **yeni veri "
            "uydurmaz** ve **AL/SAT tavsiyesi vermez** — sadece eldeki çıktıları "
            "sadeleştirir ve her olumlu noktaya ayı senaryosu ekler.\n\n"
            "Çalışması için ortam değişkeni gerekir: `ANTHROPIC_API_KEY`."
        )

    if not sym or df is None:
        st.info("👈 Önce bir hisse seçin (bağlam buradan toplanır).")
    else:
        res = evaluate(df, thin_volume=config.SCREEN["thin_volume"])

        # Bağlamı topla
        baglam = {
            "symbol": sym,
            "fiyat": round(float(df["Close"].iloc[-1]), 2),
            "sinyal_ozet": res.ozet,
            "sinyal_notlar": res.notlar,
            "ayi_senaryosu": res.ayi_senaryosu,
            "bayraklar": res.bayraklar,
        }
        # Piyasa rejimi
        fr_e = _rejim_veri(config.MACRO["rejim_endeksi"])
        if fr_e.ok and fr_e.data is not None:
            baglam["rejim"] = macro.ozetle(macro.rejim_tespit(fr_e.data))
        # Tarihsel oranlar
        try:
            from analysis.historical import ozetle as _hozet
            dag = olay_calismasi(df, esik_pct=config.HISTORICAL["sicrama_esigi_pct"],
                                 ileri_gun=config.HISTORICAL["ileri_gun"])
            baglam["tarihsel"] = [_hozet(d) for d in dag.values()]
        except Exception:
            pass
        # Kalibrasyon
        tahminler = st.session_state.get("tahminler", [])
        if tahminler:
            baglam["kalibrasyon"] = genel_ozet(kalibre_et(tahminler, min_ornek=20))
        # Haber başlıkları
        hs = _hisse_haber(sym, 5)
        if hs.ok:
            baglam["haber_basliklari"] = [h.baslik for h in hs.kayitlar]

        with st.expander("Claude'a gönderilecek bağlam (şeffaflık)"):
            st.code(llm.baglam_metni(baglam) or "(bağlam boş)", language="markdown")

        if st.button("🤖 Sentezi oluştur", type="primary"):
            with st.spinner("Claude düşünüyor..."):
                s = llm.sentezle(baglam, model=config.LLM["model"],
                                 max_tokens=config.LLM["max_tokens"])
            if s.ok:
                st.markdown(s.metin)
                st.caption(f"Model: {s.model}")
            else:
                st.warning(s.not_)
                if "anahtar" in s.not_ or "API" in s.not_:
                    st.code("export ANTHROPIC_API_KEY=sk-ant-...", language="bash")
                    st.caption("anthropic kütüphanesi gerekiyorsa: pip install anthropic")
    st.caption("Üretilen metin yatırım tavsiyesi değildir.")


# ══════════════════════════════════════════════════════════════════════════════
# ⏰ OTOMASYON (Aşama 10)
# ══════════════════════════════════════════════════════════════════════════════
with tab_otomasyon:
    st.markdown("## ⏰ Otomasyon")
    with st.expander("Bu sekme ne işe yarar?"):
        st.markdown(
            "İzleme listesini tarar, piyasa rejimini okur ve `raporlar/` altına "
            "**tarihli bir Markdown rapor** yazar. Buradan tek seferlik "
            "çalıştırabilir; her gün otomatik çalışması için aşağıdaki cron "
            "komutunu kullanabilirsiniz."
        )

    st.caption(f"{len(watchlist)} hisse taranacak · rejim: "
               f"{config.MACRO['rejim_endeksi']} · Yatırım tavsiyesi değildir")

    if st.button("▶️ Gün sonu taramasını çalıştır", type="primary"):
        from automation.scheduler import calistir
        with st.spinner("Taranıyor (canlı veri çekiliyor)..."):
            ozet = calistir(
                db_path=DB, watchlist=watchlist, screen_cfg=config.SCREEN,
                macro_cfg=config.MACRO,
                rapor_klasoru=config.OTOMASYON["rapor_klasoru"],
            )
        st.success(f"Bitti — {ozet['taranan']} hisse tarandı, "
                   f"{ozet['one_cikan']} öne çıkan.")
        st.markdown(f"**Rejim:** {ozet['rejim']}")
        st.markdown(f"**Rapor dosyası:** `{ozet['rapor_yolu']}`")
        try:
            with open(ozet["rapor_yolu"], encoding="utf-8") as f:
                st.markdown(f.read())
        except OSError:
            pass

    st.markdown("---")
    st.markdown("**Her gün otomatik çalıştırma (cron, hafta içi 18:30):**")
    st.code(
        "30 18 * * 1-5  cd /yol/borsa-analiz && "
        ".venv/bin/python -m automation.run",
        language="bash",
    )
    st.caption("Komut satırından: `python -m automation.run`")
