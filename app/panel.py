"""
Streamlit panel — Borsa Analiz Sistemi
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
from data.fetcher import fetch_history, fetch_many
from data.storage import init_db, save_prices
from analysis.indicators import add_indicators
from analysis.signals import evaluate
from analysis.screener import scan
from analysis.historical import olay_calismasi, mevsimsellik_aylik
from analysis.calibration import Tahmin, gercek_ekle, kalibre_et
from analysis import risk
from portfolio.paper import PaperPortfolio, cok_ufuklu_getiri
from backtest.engine import backtest, train_test_bol, strateji_sma_kesisim

st.set_page_config(
    page_title="Borsa Analiz",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db(config.DB_PATH)

if "portfolio" not in st.session_state:
    st.session_state.portfolio = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
if "kalibrasyon_tahminler" not in st.session_state:
    st.session_state.kalibrasyon_tahminler = []


# ── Veri fonksiyonları ──────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _veri(sym: str, period: str, interval: str):
    return fetch_history(sym, period, interval)

@st.cache_data(ttl=300)
def _izleme_listesi_ozet() -> list[dict]:
    """Tüm watchlist hisselerinin anlık özeti — tek seferde çekilir."""
    results = fetch_many(config.WATCHLIST, period="3mo")
    rows = []
    for s, r in results.items():
        if not r.ok:
            rows.append({"Sembol": s, "Fiyat": "—", "Günlük %": "—",
                         "RSI": "—", "Trend": "—", "Durum": "⚠️ veri yok"})
            continue
        df = add_indicators(r.data)
        son    = float(df["Close"].iloc[-1])
        onceki = float(df["Close"].iloc[-2])
        degisim = (son - onceki) / onceki * 100
        rsi   = df["RSI"].iloc[-1]
        sma20 = df["SMA20"].iloc[-1]
        sma50 = df["SMA50"].iloc[-1]

        if pd.notna(sma20) and pd.notna(sma50):
            trend = "↑ Yukarı" if sma20 > sma50 else "↓ Aşağı"
        else:
            trend = "—"

        if pd.notna(rsi):
            if rsi >= 70:   durum = "🔴 Aşırı alım"
            elif rsi <= 30: durum = "🟢 Aşırı satım"
            else:           durum = "⚪ Nötr"
        else:
            durum = "—"

        rows.append({
            "Sembol":   s,
            "Fiyat":    f"{son:,.2f}",
            "Günlük %": f"{degisim:+.2f}%",
            "RSI":      f"{rsi:.0f}" if pd.notna(rsi) else "—",
            "Trend":    trend,
            "Durum":    durum,
        })
    return rows


# ── Grafik ──────────────────────────────────────────────────────────────────

def _grafik(df: pd.DataFrame, sym: str):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
        subplot_titles=(f"{sym} Fiyat", "RSI (14)", "MACD"),
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="Fiyat",
    ), row=1, col=1)
    for ad, renk in [("SMA20", "#f59e0b"), ("SMA50", "#3b82f6"), ("SMA200", "#8b5cf6")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[ad], name=ad,
                      line=dict(width=1.2, color=renk)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"],
                  name="RSI", line=dict(color="#14b8a6", width=1.5)), row=2, col=1)
    for y, color in [(70, "rgba(239,68,68,0.4)"), (30, "rgba(34,197,94,0.4)")]:
        fig.add_hline(y=y, line_dash="dot", line_color=color, row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"],
                  name="MACD", line=dict(color="#3b82f6", width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_sinyal"],
                  name="Sinyal", line=dict(color="#f97316", width=1.5)), row=3, col=1)
    fig.add_trace(go.Bar(
        x=df.index,
        y=df["MACD"] - df["MACD_sinyal"],
        name="Histogram",
        marker_color=["#22c55e" if v >= 0 else "#ef4444"
                      for v in (df["MACD"] - df["MACD_sinyal"])],
    ), row=3, col=1)
    fig.update_layout(
        height=700, xaxis_rangeslider_visible=False,
        margin=dict(t=30, b=10, l=0, r=0),
        legend=dict(orientation="h", y=1.02),
        plot_bgcolor="white",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    return fig


# ── Kenar çubuğu ────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📈 Borsa Analiz")
    st.divider()

    st.subheader("🔍 Hisse Seç")
    OZEL = "✏️  Özel sembol gir..."
    secenekler = config.WATCHLIST + [OZEL]
    secim = st.selectbox(
        "İzleme listesi",
        secenekler,
        help="Listede yoksa en alttaki 'Özel' seçeneğini kullan",
    )
    if secim == OZEL:
        ozel_sym = st.text_input(
            "Sembol", placeholder="ör. BIMAS.IS  |  AMZN  |  TSLA",
            help="BIST hisseleri için sona .IS ekle",
        )
        sym = ozel_sym.strip().upper() if ozel_sym.strip() else ""
    else:
        sym = secim

    st.divider()
    st.subheader("⚙️ Grafik Ayarları")
    period   = st.selectbox("Dönem",  ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
    interval = st.selectbox("Aralık", ["1d", "1wk"], index=0)
    st.divider()
    st.caption("Veriler yfinance'den çekilir · 5 dk önbelleklenir")
    st.caption("Yatırım tavsiyesi değildir.")


# ── Veri yükle ──────────────────────────────────────────────────────────────

fr = _veri(sym, period, interval) if sym else None
df = None
if fr and fr.ok:
    save_prices(config.DB_PATH, fr)
    df = add_indicators(fr.data)


# ── Sekmeler ────────────────────────────────────────────────────────────────

(tab_panel, tab_liste, tab_portfoy,
 tab_backtest, tab_tarihsel, tab_kalibrasyon, tab_risk) = st.tabs([
    "📊 Panel", "📋 İzleme Listesi", "💼 Portföy",
    "🔬 Backtest", "📅 Tarihsel", "🎯 Kalibrasyon", "⚠️ Risk",
])


# ══════════════════════════════════════════════════════════════════════════════
# PANEL
# ══════════════════════════════════════════════════════════════════════════════
with tab_panel:
    if not sym:
        st.info("Sol taraftan bir hisse seç veya özel sembol gir.")
    elif not fr or not fr.ok:
        st.error(f"**'{sym}'** için veri alınamadı.")
        st.markdown(f"> {fr.note if fr else 'Sembol boş'}")
        st.markdown("**İpuçları:**")
        st.markdown("- BIST hisseleri için sona **.IS** ekle → `THYAO.IS`")
        st.markdown("- Büyük harf kullan → `AAPL` değil `aapl` olmaz")
        st.markdown("- Sembolün doğruluğunu [finance.yahoo.com](https://finance.yahoo.com)'da kontrol et")
    else:
        son     = float(df["Close"].iloc[-1])
        onceki  = float(df["Close"].iloc[-2])
        degisim = (son - onceki) / onceki * 100
        rsi_son = df["RSI"].iloc[-1]

        # ── Başlık + metrikler ──────────────────────────────────────────────
        st.markdown(f"## {sym}")
        st.caption(f"Kaynak: {fr.source} · Son güncelleme: {fr.fetched_at[:10]}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Son Fiyat",      f"{son:,.2f}",                      f"{degisim:+.2f}%")
        c2.metric("Dönem En Yüksek",f"{float(df['High'].max()):,.2f}")
        c3.metric("Dönem En Düşük", f"{float(df['Low'].min()):,.2f}")
        c4.metric("RSI (14)",       f"{rsi_son:.1f}" if pd.notna(rsi_son) else "—")

        # ── Sinyal özeti ────────────────────────────────────────────────────
        res = evaluate(df, thin_volume=config.SCREEN["thin_volume"])
        renk = {"Göstergeler ağırlıklı pozitif": "🟢",
                "Göstergeler ağırlıklı negatif": "🔴"}.get(res.ozet, "🟡")
        st.markdown(f"### {renk} {res.ozet}")

        col_notlar, col_ayi = st.columns(2)
        with col_notlar:
            st.markdown("**Gösterge notları**")
            for n in res.notlar:
                st.write(f"• {n}")
        with col_ayi:
            if res.ayi_senaryosu:
                st.markdown("**Dikkat — neden ters gidebilir?**")
                for a in res.ayi_senaryosu:
                    st.write(f"– {a}")

        for b in res.bayraklar:
            st.warning(b)

        # ── Grafik ─────────────────────────────────────────────────────────
        st.plotly_chart(_grafik(df, sym), use_container_width=True)

        # ── Bollinger bantları özeti ────────────────────────────────────────
        bb_ust = df["BB_ust"].iloc[-1]
        bb_alt = df["BB_alt"].iloc[-1]
        if pd.notna(bb_ust) and pd.notna(bb_alt):
            with st.expander("📐 Bollinger Bantları"):
                b1, b2, b3 = st.columns(3)
                b1.metric("Üst Bant",  f"{bb_ust:,.2f}")
                b2.metric("Son Fiyat", f"{son:,.2f}")
                b3.metric("Alt Bant",  f"{bb_alt:,.2f}")
                if son > bb_ust:
                    st.warning("Fiyat üst bandın üzerinde — aşırı alım bölgesi olabilir.")
                elif son < bb_alt:
                    st.success("Fiyat alt bandın altında — aşırı satım bölgesi olabilir.")


# ══════════════════════════════════════════════════════════════════════════════
# İZLEME LİSTESİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_liste:
    st.markdown("## 📋 İzleme Listesi")
    st.caption(f"{len(config.WATCHLIST)} hisse · 3 aylık veri · 5 dk önbellek · Yatırım tavsiyesi değildir")

    with st.spinner("Veriler yükleniyor..."):
        ozet_rows = _izleme_listesi_ozet()

    df_ozet = pd.DataFrame(ozet_rows)
    st.dataframe(df_ozet, use_container_width=True, hide_index=True, height=350)

    st.markdown("---")
    st.markdown("#### Durum Rehberi")
    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.markdown("🔴 **Aşırı alım** — RSI ≥ 70, düzeltme gelebilir")
    col_r2.markdown("🟢 **Aşırı satım** — RSI ≤ 30, toparlanma potansiyeli")
    col_r3.markdown("⚪ **Nötr** — RSI 30–70 arası, belirgin sinyal yok")

    st.markdown("#### Trend Açıklaması")
    st.markdown("- **↑ Yukarı** — SMA20 > SMA50 (kısa vadeli momentum yukarı)")
    st.markdown("- **↓ Aşağı** — SMA20 < SMA50 (kısa vadeli momentum aşağı)")
    st.caption("Trend, SMA200 için yeterli veri olmadığında SMA20/50 karşılaştırması kullanır.")


# ══════════════════════════════════════════════════════════════════════════════
# PORTFÖY
# ══════════════════════════════════════════════════════════════════════════════
with tab_portfoy:
    st.markdown("## 💼 Paper Portföy (Sanal)")
    st.caption("Gerçek para işlemi yapılmaz. İşlem maliyetleri (komisyon + kayma) uygulanır.")

    p = st.session_state.portfolio
    guncel_fiyat = float(df["Close"].iloc[-1]) if (fr and fr.ok) else None
    guncel_fiyatlar = {sym: guncel_fiyat} if guncel_fiyat and sym else {}

    ozet = p.ozet(guncel_fiyatlar)

    # Özet kartlar
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Başlangıç Sermayesi", f"{ozet['baslangic']:,.0f} ₺")
    c2.metric("Nakit",               f"{ozet['nakit']:,.0f} ₺")
    c3.metric("Portföy Değeri",      f"{ozet['guncel_deger']:,.0f} ₺")
    c4.metric("Toplam Getiri",       f"{ozet['getiri_pct']:+.2f}%")

    # Açık pozisyonlar — kar/zarar göster
    if p.pozisyonlar:
        st.divider()
        st.markdown("### Açık Pozisyonlar")
        poz_rows = []
        for s, poz in p.pozisyonlar.items():
            guncel = guncel_fiyatlar.get(s, None)
            if guncel:
                kz_pct = (guncel - poz.alis_fiyat) / poz.alis_fiyat * 100
                kz_tl  = (guncel - poz.alis_fiyat) * poz.adet
                durum  = "✅ Kârda" if kz_pct >= 0 else "🔴 Zararda"
            else:
                kz_pct, kz_tl, durum = None, None, "—"

            poz_rows.append({
                "Sembol":      s,
                "Adet":        round(poz.adet, 2),
                "Alış Fiyatı": round(poz.alis_fiyat, 2),
                "Güncel Fiyat":f"{guncel:,.2f}" if guncel else "—",
                "K/Z %":       f"{kz_pct:+.2f}%" if kz_pct is not None else "—",
                "K/Z ₺":       f"{kz_tl:+,.0f} ₺" if kz_tl is not None else "—",
                "Durum":       durum,
                "Alış Tarihi": poz.alis_tarih,
            })
        st.dataframe(pd.DataFrame(poz_rows), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Alım İşlemi")
    ca1, ca2, ca3 = st.columns([2, 2, 1])
    with ca1:
        al_sym   = st.text_input("Sembol", value=sym or "", key="al_sym",
                                 placeholder="ör. THYAO.IS")
        al_fiyat = st.number_input("Fiyat (₺)", min_value=0.01,
                                   value=guncel_fiyat or 1.0, step=0.01, key="al_fiyat")
    with ca2:
        al_tutar   = st.number_input("Tutar (₺)", min_value=100.0,
                                     value=float(config.INITIAL_CAPITAL * config.RISK["pozisyon_pct"]),
                                     step=100.0, key="al_tutar")
        al_gerekce = st.text_input("Gerekçe (isteğe bağlı)", key="al_gerekce")
    with ca3:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("✅ Al", use_container_width=True):
            try:
                adet = p.al(al_sym.strip().upper(), al_fiyat,
                            pd.Timestamp.now().date().isoformat(),
                            tutar=al_tutar, gerekce=al_gerekce)
                st.success(f"{adet:.2f} adet alındı.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    if p.pozisyonlar:
        st.markdown("### Satış İşlemi")
        cs1, cs2, cs3 = st.columns([2, 2, 1])
        with cs1:
            sat_sym = st.selectbox("Pozisyon", list(p.pozisyonlar.keys()), key="sat_sym")
        with cs2:
            sat_fiyat = st.number_input("Satış Fiyatı (₺)", min_value=0.01,
                                        value=guncel_fiyat or 1.0, step=0.01, key="sat_fiyat")
        with cs3:
            st.markdown("&nbsp;", unsafe_allow_html=True)
            st.markdown("&nbsp;", unsafe_allow_html=True)
            if st.button("🔴 Sat", use_container_width=True):
                try:
                    gelir = p.sat(sat_sym, sat_fiyat, pd.Timestamp.now().date().isoformat())
                    st.success(f"Satıldı — gelir: {gelir:,.2f} ₺")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        if fr and fr.ok and p.islemler:
            st.divider()
            st.markdown("### Çok Ufuklu Getiri")
            st.caption("İlk alım tarihinden itibaren farklı vadeler")
            try:
                getiriler = cok_ufuklu_getiri(fr.data["Close"], p.islemler[0].tarih, config.HORIZONS)
                g_rows = [{"Vade": ufuk,
                           "Getiri %": f"{v['getiri_pct']:+.2f}%" if v.get("getiri_pct") is not None else "veri yok",
                           "Tarih": v.get("tarih") or "—"}
                          for ufuk, v in getiriler.items()]
                st.dataframe(pd.DataFrame(g_rows), use_container_width=True, hide_index=True)
            except Exception:
                st.info("Hesaplanamadı — giriş tarihi seçilen dönem dışında olabilir.")

    if p.islemler:
        with st.expander(f"📜 İşlem Geçmişi ({len(p.islemler)} işlem)"):
            islem_rows = [{"Tarih": i.tarih, "Sembol": i.symbol, "Yön": i.yon,
                           "Fiyat": round(i.fiyat, 2), "Adet": round(i.adet, 2),
                           "Tutar": round(i.tutar, 2), "Gerekçe": i.gerekce}
                          for i in p.islemler]
            st.dataframe(pd.DataFrame(islem_rows), use_container_width=True, hide_index=True)

    st.divider()
    if st.button("🗑️ Portföyü Sıfırla", type="secondary"):
        st.session_state.portfolio = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown("## 🔬 Backtest — SMA Kesişim Stratejisi")
    st.caption("50 günlük > 200 günlük ise long, değilse nakit. İşlem maliyetleri dahil.")

    if not sym:
        st.info("Sol taraftan bir hisse seç.")
    elif not fr or not fr.ok:
        st.warning(f"'{sym}' için veri alınamadı: {fr.note if fr else ''}")
    else:
        if len(df) < 210:
            st.warning(f"Veri az ({len(df)} gün) — SMA200 için 210+ gün önerilir, sonuçlar güvenilmez.")

        test_orani = st.slider("Test dönemi oranı (out-of-sample)", 0.1, 0.5, 0.3, 0.05)

        egitim, test = train_test_bol(df, test_orani)
        r_e = backtest(egitim, strateji_sma_kesisim, costs=config.COSTS)
        r_t = backtest(test,   strateji_sma_kesisim, costs=config.COSTS)

        col_e, col_t = st.columns(2)
        for col, r, baslik in [
            (col_e, r_e, f"Eğitim ({r_e.gun_sayisi} gün)"),
            (col_t, r_t, f"Test / Out-of-sample ({r_t.gun_sayisi} gün)"),
        ]:
            with col:
                st.markdown(f"**{baslik}**")
                m1, m2 = st.columns(2)
                m1.metric("Strateji",      f"{r.getiri_pct:+.1f}%")
                m2.metric("Al-tut",        f"{r.benchmark_pct:+.1f}%")
                st.metric("Fark (strateji − al-tut)", f"{r.fark_pct:+.1f}%",
                          delta_color="normal")
                st.metric("Max Düşüş",     f"{r.max_dusus_pct:.1f}%")
                st.metric("Sharpe",        f"{r.sharpe:.2f}")
                st.metric("İşlem Sayısı",  r.islem_sayisi)

        st.info("ℹ️ Fark negatifse strateji basit al-tutu geçemiyor — bu dürüst bir sonuçtur. Geçmiş performans geleceği garantilemez.")


# ══════════════════════════════════════════════════════════════════════════════
# TARİHSEL
# ══════════════════════════════════════════════════════════════════════════════
with tab_tarihsel:
    st.markdown("## 📅 Tarihsel Temel Oranlar")
    st.caption("'Bu hisse benzer durumda ne yapmış?' sorusunu gerçek geçmiş veriyle yanıtlar.")

    if not sym:
        st.info("Sol taraftan bir hisse seç.")
    elif not fr or not fr.ok:
        st.warning(f"Veri alınamadı: {fr.note if fr else ''}")
    else:
        esik = st.slider(
            "Günlük sıçrama eşiği (%)",
            1.0, 15.0, float(config.HISTORICAL["sicrama_esigi_pct"]), 0.5,
        )

        dag = olay_calismasi(fr.data, esik_pct=esik, ileri_gun=config.HISTORICAL["ileri_gun"])

        st.markdown(f"### {sym}: %{esik:.0f}+ günlük yükseliş sonrası ne oldu?")

        rows = []
        for ufuk, d in dag.items():
            if d.n == 0:
                rows.append({"Ufuk": f"{ufuk} gün", "Örnek (n)": 0,
                             "Medyan": "—", "Ort.": "—", "Min": "—", "Max": "—",
                             "Pozitif Oran": "—", "Güvenilir": "❌ Hayır", "Not": d.not_})
            else:
                rows.append({
                    "Ufuk":         f"{ufuk} gün",
                    "Örnek (n)":    d.n,
                    "Medyan":       f"{d.medyan_pct:+.1f}%",
                    "Ort.":         f"{d.ortalama_pct:+.1f}%",
                    "Min":          f"{d.min_pct:+.1f}%",
                    "Max":          f"{d.max_pct:+.1f}%",
                    "Pozitif Oran": f"{d.pozitif_orani:.0%}",
                    "Güvenilir":    "✅ Evet" if d.guvenilir else "⚠️ Az örnek",
                    "Not":          d.not_ or "",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Aylık Mevsimsellik")
        st.caption("Hangi ay tarihsel olarak daha iyi performans göstermiş?")
        try:
            mvs = mevsimsellik_aylik(fr.data)
            if not mvs.empty:
                st.dataframe(mvs, use_container_width=True)
            else:
                st.info("Yeterli veri yok (en az 2 yıl önerilir).")
        except Exception:
            st.info("Hesaplanamadı — yeterli veri yok.")

        st.caption("⚠️ Az örnek = güvenilmez. Geçmiş performans geleceği garantilemez.")


# ══════════════════════════════════════════════════════════════════════════════
# KALİBRASYON
# ══════════════════════════════════════════════════════════════════════════════
with tab_kalibrasyon:
    st.markdown("## 🎯 Kalibrasyon — Sinyal İsabeti")
    st.caption("Tahminlerini kaydet, ufuk dolunca gerçekle karşılaştır. Hedef: isabeti dürüstçe ölçmek.")

    tahminler = st.session_state.kalibrasyon_tahminler

    with st.expander("➕ Yeni Tahmin Ekle", expanded=not bool(tahminler)):
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            k_sym    = st.text_input("Sembol", value=sym or "", key="k_sym")
            k_yon    = st.selectbox("Tahmin yönü", ["pozitif", "negatif"], key="k_yon")
        with ck2:
            k_sinyal = st.text_input("Sinyal tipi", value="SMA_kesisim",
                                     placeholder="ör. RSI_dusuk, MACD_kesisim", key="k_sinyal")
            k_ufuk   = st.number_input("Ufuk (gün)", min_value=1, value=14, key="k_ufuk")
        with ck3:
            k_tarih  = st.text_input("Tarih", value=pd.Timestamp.now().date().isoformat(), key="k_tarih")
        if st.button("Tahmin Ekle", type="primary"):
            st.session_state.kalibrasyon_tahminler.append(
                Tahmin(k_sym.strip().upper(), k_tarih, k_yon, k_sinyal, int(k_ufuk))
            )
            st.success("Eklendi. Ufuk dolunca aşağıdan gerçekleşeni gir.")
            st.rerun()

    if not tahminler:
        st.info("Henüz tahmin yok. Yukarıdan ekleyebilirsin.")
    else:
        bekleyenler = [(i, t) for i, t in enumerate(tahminler) if t.gerceklesen_pct is None]
        if bekleyenler:
            st.divider()
            st.markdown("### Gerçekleşeni Kaydet")
            secenekler = {f"{t.symbol} · {t.yon} · {t.sinyal_tipi} ({t.tarih})": i
                          for i, t in bekleyenler}
            secim_k = st.selectbox("Hangi tahmin?", list(secenekler.keys()), key="k_secim")
            gercek_pct = st.number_input("Gerçekleşen değişim %", step=0.1, key="k_gercek")
            if st.button("Kaydet", type="primary"):
                idx = secenekler[secim_k]
                st.session_state.kalibrasyon_tahminler[idx] = gercek_ekle(
                    st.session_state.kalibrasyon_tahminler[idx], gercek_pct
                )
                st.success("Kaydedildi.")
                st.rerun()

        sonuclar = kalibre_et(tahminler, min_ornek=10)
        if sonuclar:
            st.divider()
            st.markdown("### Kalibrasyon Sonuçları")
            k_rows = [{
                "Sinyal Tipi":    s.sinyal_tipi,
                "Tahmin Sayısı":  s.n,
                "İsabet %":       f"{s.isabet_orani*100:.0f}%" if s.isabet_orani is not None else "—",
                "Yazı-tura Farkı":f"{s.yazitura_farki:+.3f}" if s.yazitura_farki is not None else "—",
                "Güvenilir":      "✅ Evet" if s.guvenilir else "⚠️ Az örnek",
                "Not":            s.not_ or "",
            } for s in sonuclar]
            st.dataframe(pd.DataFrame(k_rows), use_container_width=True, hide_index=True)

        with st.expander(f"📋 Tüm Tahminler ({len(tahminler)})"):
            t_rows = [{"Sembol": t.symbol, "Tarih": t.tarih, "Yön": t.yon,
                       "Sinyal": t.sinyal_tipi, "Ufuk": f"{t.ufuk_gun}g",
                       "Gerçekleşen": f"{t.gerceklesen_pct:+.1f}%" if t.gerceklesen_pct is not None else "⏳ bekliyor"}
                      for t in tahminler]
            st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)

        if st.button("🗑️ Tüm Tahminleri Temizle", type="secondary"):
            st.session_state.kalibrasyon_tahminler = []
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# RİSK
# ══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown("## ⚠️ Risk Yönetimi")

    # Pozisyon büyüklüğü hesaplama
    st.markdown("### Pozisyon Büyüklüğü Hesaplama")
    st.caption(f"Tek pozisyona sermayenin en fazla %{config.RISK['pozisyon_pct']*100:.0f}'i ayrılır (config.py)")

    cr1, cr2 = st.columns(2)
    with cr1:
        r_sermaye = st.number_input("Toplam Sermaye (₺)", min_value=1000.0,
                                    value=float(config.INITIAL_CAPITAL), step=1000.0)
    with cr2:
        varsayilan = float(df["Close"].iloc[-1]) if (fr and fr.ok) else 100.0
        r_fiyat = st.number_input("Hisse Fiyatı (₺)", min_value=0.01,
                                  value=varsayilan, step=0.01)

    pb = risk.pozisyon_buyuklugu(r_sermaye, r_fiyat, config.RISK["pozisyon_pct"])
    cm1, cm2, cm3 = st.columns(3)
    cm1.metric("Tahsis Tutarı",  f"{pb['tahsis_tutar']:,.0f} ₺")
    cm2.metric("Alınabilir Adet", str(pb["adet"]))
    cm3.metric("Gerçek Tutar",   f"{pb['gercek_tutar']:,.0f} ₺")

    # Portföy analizi
    p = st.session_state.portfolio
    if p.pozisyonlar:
        fiyatlar_bilinen = {sym: float(df["Close"].iloc[-1])} if (fr and fr.ok and sym) else {}
        poz_degerleri = {s: poz.adet * fiyatlar_bilinen.get(s, poz.alis_fiyat)
                        for s, poz in p.pozisyonlar.items()}

        col_y, col_s = st.columns(2)
        with col_y:
            st.markdown("### Yoğunlaşma Kontrolü")
            st.caption(f"Eşik: tek hisse portföyün %{config.RISK['yogunlasma_uyari_pct']*100:.0f}'inden fazlasını oluşturmasın")
            uyarilar = risk.yogunlasma_kontrol(poz_degerleri, config.RISK["yogunlasma_uyari_pct"])
            if uyarilar:
                for u in uyarilar: st.warning(u)
            else:
                st.success("✅ Yoğunlaşma riski yok.")

        with col_s:
            st.markdown("### Stop-Loss Kontrolü")
            st.caption(f"Eşik: %{abs(config.RISK['stop_loss_pct'])*100:.0f} zararda otomatik çıkış önerisi")
            poz_dict = {s: {"alis_fiyat": poz.alis_fiyat} for s, poz in p.pozisyonlar.items()}
            stop_uyarilar = risk.stop_loss_kontrol(poz_dict, fiyatlar_bilinen, config.RISK["stop_loss_pct"])
            if stop_uyarilar:
                for u in stop_uyarilar: st.error(u)
            else:
                st.success("✅ Stop-loss tetiklenmedi.")
    else:
        st.info("Portföy sekmesinden pozisyon eklenince burada yoğunlaşma ve stop-loss analizi görünür.")

    # Korelasyon matrisi
    st.divider()
    st.markdown("### Korelasyon Matrisi")
    st.caption("Hisseler birbirinden ne kadar bağımsız? Yüksek korelasyon = çeşitlendirme azalır.")
    if st.button("Hesapla (izleme listesinin ilk 6 hissesi)"):
        with st.spinner("Veriler çekiliyor..."):
            results = fetch_many(config.WATCHLIST[:6], period="3mo")
        gecerli = {s: r.data["Close"].rename(s) for s, r in results.items() if r.ok}
        if len(gecerli) >= 2:
            fiyat_df = pd.concat(list(gecerli.values()), axis=1).dropna()
            corr = risk.korelasyon_matrisi(fiyat_df)
            st.dataframe(corr, use_container_width=True)
            st.caption("1.00 = tam korele (aynı yönde hareket), 0 = bağımsız, -1 = ters korele")
        else:
            st.warning("Yeterli veri alınamadı.")
