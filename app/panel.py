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

DB = config.DB_PATH
init_db(DB)

# ── Kalıcı watchlist — DB yoksa config.py varsayılanı ──────────────────────
if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist(DB) or list(config.WATCHLIST)

# ── Kalıcı portföy — DB'den yükle ──────────────────────────────────────────
if "portfolio" not in st.session_state:
    st.session_state.portfolio = load_portfolio(DB)

# ── Kalıcı kalibrasyon — DB'den yükle ───────────────────────────────────────
if "tahminler" not in st.session_state:
    st.session_state.tahminler = load_tahminler(DB)


# ── Veri fonksiyonları ───────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _veri(sym: str, period: str, interval: str):
    return fetch_history(sym, period, interval)

@st.cache_data(ttl=300)
def _liste_ozet(watchlist_key: str) -> list[dict]:
    """watchlist_key: virgülle ayrılmış semboller (cache key için)."""
    symbols = [s for s in watchlist_key.split(",") if s]
    results = fetch_many(symbols, period="3mo")
    rows = []
    for s, r in results.items():
        if not r.ok:
            rows.append({"Sembol": s, "Fiyat": "—", "Günlük %": "—",
                         "RSI": "—", "Trend": "—", "Durum": "⚠️ veri yok"})
            continue
        df = add_indicators(r.data)
        son = float(df["Close"].iloc[-1])
        onceki = float(df["Close"].iloc[-2])
        degisim = (son - onceki) / onceki * 100
        rsi   = df["RSI"].iloc[-1]
        sma20 = df["SMA20"].iloc[-1]
        sma50 = df["SMA50"].iloc[-1]
        trend = ("↑ Yukarı" if sma20 > sma50 else "↓ Aşağı") if (pd.notna(sma20) and pd.notna(sma50)) else "—"
        if pd.notna(rsi):
            durum = "🔴 Aşırı alım" if rsi >= 70 else ("🟢 Aşırı satım" if rsi <= 30 else "⚪ Nötr")
        else:
            durum = "—"
        rows.append({"Sembol": s, "Fiyat": f"{son:,.2f}", "Günlük %": f"{degisim:+.2f}%",
                     "RSI": f"{rsi:.0f}" if pd.notna(rsi) else "—", "Trend": trend, "Durum": durum})
    return rows


# ── Grafik ───────────────────────────────────────────────────────────────────

def _grafik(df: pd.DataFrame, sym: str):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
        subplot_titles=(f"{sym} Fiyat + Hareketli Ortalamalar", "RSI (14)", "MACD"),
    )
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                  low=df["Low"], close=df["Close"], name="Fiyat"), row=1, col=1)
    for ad, renk in [("SMA20","#f59e0b"),("SMA50","#3b82f6"),("SMA200","#8b5cf6")]:
        fig.add_trace(go.Scatter(x=df.index, y=df[ad], name=ad,
                      line=dict(width=1.2, color=renk)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                  line=dict(color="#14b8a6", width=1.5)), row=2, col=1)
    for y, c in [(70,"rgba(239,68,68,0.5)"),(30,"rgba(34,197,94,0.5)")]:
        fig.add_hline(y=y, line_dash="dot", line_color=c, row=2, col=1)
    hist = df["MACD"] - df["MACD_sinyal"]
    fig.add_trace(go.Bar(x=df.index, y=hist, name="Histogram",
                  marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in hist]), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD"], name="MACD",
                  line=dict(color="#3b82f6",width=1.5)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MACD_sinyal"], name="Sinyal",
                  line=dict(color="#f97316",width=1.5)), row=3, col=1)
    fig.update_layout(height=680, xaxis_rangeslider_visible=False,
                      margin=dict(t=30,b=10,l=0,r=0),
                      legend=dict(orientation="h",y=1.02),
                      plot_bgcolor="white")
    fig.update_xaxes(showgrid=True, gridcolor="#f1f5f9")
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    return fig


# ── Kenar çubuğu ─────────────────────────────────────────────────────────────

watchlist = st.session_state.watchlist

with st.sidebar:
    st.title("📈 Borsa Analiz")
    st.divider()

    # Sembol seçimi
    st.subheader("🔍 Hisse Seç")
    OZEL = "✏️  Özel sembol gir..."
    secenekler = watchlist + [OZEL]
    secim = st.selectbox("İzleme listesi", secenekler,
                         help="Listede yoksa 'Özel sembol gir' seçeneğini kullan")
    if secim == OZEL:
        ozel_sym = st.text_input("Sembol yaz", placeholder="BIMAS.IS · AMZN · TSLA",
                                 help="BIST hisseleri için sona .IS ekle")
        sym = ozel_sym.strip().upper() if ozel_sym.strip() else ""
    else:
        sym = secim

    st.divider()

    # İzleme listesi yönetimi
    with st.expander("📝 İzleme Listesini Düzenle"):
        st.caption("Ekle veya çıkar — değişiklikler kaydedilir")
        yeni = st.text_input("Ekle", placeholder="ör. BIMAS.IS", key="wl_ekle")
        if st.button("➕ Ekle", use_container_width=True):
            s = yeni.strip().upper()
            if s and s not in watchlist:
                watchlist.append(s)
                save_watchlist(DB, watchlist)
                st.session_state.watchlist = watchlist
                st.rerun()
        if watchlist:
            cikar = st.selectbox("Çıkar", watchlist, key="wl_cikar")
            if st.button("➖ Çıkar", use_container_width=True):
                watchlist.remove(cikar)
                save_watchlist(DB, watchlist)
                st.session_state.watchlist = watchlist
                st.rerun()

    st.divider()
    st.subheader("⚙️ Grafik Ayarları")
    period   = st.selectbox("Dönem",  ["1mo","3mo","6mo","1y","2y","5y"], index=3)
    interval = st.selectbox("Aralık", ["1d","1wk"], index=0)
    st.divider()
    st.caption("Veriler yfinance'den · 5 dk önbellek")
    st.caption("Yatırım tavsiyesi değildir.")


# ── Veri yükle ───────────────────────────────────────────────────────────────

fr = _veri(sym, period, interval) if sym else None
df = None
if fr and fr.ok:
    save_prices(DB, fr)
    df = add_indicators(fr.data)


# ── Sekmeler ─────────────────────────────────────────────────────────────────

(tab_panel, tab_liste, tab_portfoy,
 tab_backtest, tab_tarihsel, tab_kalibrasyon,
 tab_risk, tab_ogren) = st.tabs([
    "📊 Panel", "📋 İzleme Listesi", "💼 Portföy",
    "🔬 Backtest", "📅 Tarihsel", "🎯 Kalibrasyon",
    "⚠️ Risk", "📚 Nasıl Çalışır?",
])


# ══════════════════════════════════════════════════════════════════════════════
# 📊 PANEL
# ══════════════════════════════════════════════════════════════════════════════
with tab_panel:
    if not sym:
        st.info("Sol taraftan bir hisse seç veya sembol yaz.")
    elif not fr or not fr.ok:
        st.error(f"**'{sym}'** için veri alınamadı.")
        if fr: st.markdown(f"> {fr.note}")
        st.markdown("**İpuçları:** BIST için sona `.IS` ekle (THYAO.IS) · Büyük harf kullan · Yahoo Finance'de sembolü doğrula")
    else:
        son     = float(df["Close"].iloc[-1])
        onceki  = float(df["Close"].iloc[-2])
        degisim = (son - onceki) / onceki * 100
        rsi_son = df["RSI"].iloc[-1]

        st.markdown(f"## {sym}")
        st.caption(f"Kaynak: {fr.source} · {fr.meta.get('satir',0)} günlük veri · Son: {fr.fetched_at[:10]}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Son Fiyat",       f"{son:,.2f}", f"{degisim:+.2f}%")
        c2.metric("Dönem En Yüksek", f"{float(df['High'].max()):,.2f}")
        c3.metric("Dönem En Düşük",  f"{float(df['Low'].min()):,.2f}")
        c4.metric("RSI",             f"{rsi_son:.1f}" if pd.notna(rsi_son) else "—",
                  help="14 günlük RSI. 70+ aşırı alım, 30- aşırı satım. 📚 sekmesinde detaylı açıklama var.")

        res = evaluate(df, thin_volume=config.SCREEN["thin_volume"])
        renk = {"Göstergeler ağırlıklı pozitif":"🟢","Göstergeler ağırlıklı negatif":"🔴"}.get(res.ozet,"🟡")
        st.markdown(f"### {renk} {res.ozet}")

        col_n, col_a = st.columns(2)
        with col_n:
            st.markdown("**Gösterge notları**")
            for n in res.notlar: st.write(f"• {n}")
        with col_a:
            if res.ayi_senaryosu:
                st.markdown("**Dikkat — neden ters gidebilir?**")
                for a in res.ayi_senaryosu: st.write(f"– {a}")
        for b in res.bayraklar: st.warning(b)

        st.plotly_chart(_grafik(df, sym), use_container_width=True)

        with st.expander("📐 Bollinger Bantları"):
            bb_u = df["BB_ust"].iloc[-1]; bb_a = df["BB_alt"].iloc[-1]
            if pd.notna(bb_u):
                b1, b2, b3 = st.columns(3)
                b1.metric("Üst Bant", f"{bb_u:,.2f}")
                b2.metric("Son Fiyat",f"{son:,.2f}")
                b3.metric("Alt Bant", f"{bb_a:,.2f}")
                if son > bb_u:   st.warning("Fiyat üst bandın üzerinde — olası aşırı alım.")
                elif son < bb_a: st.success("Fiyat alt bandın altında — olası aşırı satım.")
                else:            st.info("Fiyat bantlar içinde — nötr bölge.")
            st.caption("Bollinger nedir? 📚 sekmesine bak.")

        st.caption("Yatırım tavsiyesi değildir. Bilgilendirme amaçlıdır.")


# ══════════════════════════════════════════════════════════════════════════════
# 📋 İZLEME LİSTESİ
# ══════════════════════════════════════════════════════════════════════════════
with tab_liste:
    st.markdown("## 📋 İzleme Listesi")
    st.caption(f"{len(watchlist)} hisse · 3 aylık veri · 5 dk önbellek")

    wl_key = ",".join(watchlist)
    with st.spinner("Veriler yükleniyor..."):
        ozet_rows = _liste_ozet(wl_key)

    st.dataframe(pd.DataFrame(ozet_rows), use_container_width=True, hide_index=True, height=380)

    with st.expander("Durum ve Trend Rehberi"):
        col1, col2, col3 = st.columns(3)
        col1.markdown("🔴 **Aşırı alım** — RSI ≥ 70\nDüzeltme gelebilir")
        col2.markdown("🟢 **Aşırı satım** — RSI ≤ 30\nToparlanma potansiyeli")
        col3.markdown("⚪ **Nötr** — RSI 30–70 arası\nBelirgin sinyal yok")
        st.markdown("**↑ Yukarı trend:** SMA20 > SMA50 — kısa vadeli momentum yukarı")
        st.markdown("**↓ Aşağı trend:** SMA20 < SMA50 — kısa vadeli momentum aşağı")
        st.caption("Detaylı gösterge açıklamaları için 📚 sekmesine bak.")


# ══════════════════════════════════════════════════════════════════════════════
# 💼 PORTFÖY
# ══════════════════════════════════════════════════════════════════════════════
with tab_portfoy:
    st.markdown("## 💼 Paper Portföy")
    st.caption("Sanal para ile gerçek piyasa fiyatlarında alım-satım. Komisyon ve kayma maliyeti dahil.")

    p = st.session_state.portfolio
    guncel_f = float(df["Close"].iloc[-1]) if (fr and fr.ok) else None
    gf = {sym: guncel_f} if (guncel_f and sym) else {}
    ozet = p.ozet(gf)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Başlangıç Sermayesi", f"{ozet['baslangic']:,.0f} ₺")
    c2.metric("Nakit",               f"{ozet['nakit']:,.0f} ₺")
    c3.metric("Portföy Değeri",      f"{ozet['guncel_deger']:,.0f} ₺")
    c4.metric("Toplam Getiri",       f"{ozet['getiri_pct']:+.2f}%")

    # ── Açık pozisyonlar + K/Z ──
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
                kz_pct = kz_tl = None; durum = "—"
            poz_rows.append({
                "Sembol":       s,
                "Adet":         round(poz.adet, 2),
                "Alış Fiyatı":  round(poz.alis_fiyat, 2),
                "Güncel":       f"{g:,.2f}" if g else "—",
                "K/Z %":        f"{kz_pct:+.2f}%" if kz_pct is not None else "—",
                "K/Z ₺":        f"{kz_tl:+,.0f} ₺" if kz_tl is not None else "—",
                "Durum":        durum,
                "Alış Tarihi":  poz.alis_tarih,
            })
        st.dataframe(pd.DataFrame(poz_rows), use_container_width=True, hide_index=True)

    # ── Alım ──
    st.divider()
    st.markdown("### Alım İşlemi")
    ca1, ca2, ca3 = st.columns([2, 2, 1])
    with ca1:
        al_sym   = st.text_input("Sembol", value=sym or "", key="al_sym", placeholder="THYAO.IS")
        al_fiyat = st.number_input("Fiyat (₺)", min_value=0.01, value=guncel_f or 1.0, step=0.01, key="al_fiyat")
    with ca2:
        al_tutar   = st.number_input("Tutar (₺)", min_value=100.0,
                                     value=float(config.INITIAL_CAPITAL * config.RISK["pozisyon_pct"]),
                                     step=100.0, key="al_tutar")
        al_gerekce = st.text_input("Gerekçe (isteğe bağlı)", key="al_gerekce")
    with ca3:
        st.write(""); st.write("")
        if st.button("✅ Al", use_container_width=True):
            try:
                tarih = pd.Timestamp.now().date().isoformat()
                s_upper = al_sym.strip().upper()
                adet = p.al(s_upper, al_fiyat, tarih, tutar=al_tutar, gerekce=al_gerekce)
                # Ham fiyatı kaydet; load_portfolio replay'de _efektif_alis tekrar uygulanır
                save_islem(DB, s_upper, "AL", tarih, al_fiyat, adet, al_tutar, al_gerekce)
                st.success(f"{adet:.2f} adet {s_upper} alındı.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    # ── Satım ──
    if p.pozisyonlar:
        st.markdown("### Satış İşlemi")
        cs1, cs2, cs3 = st.columns([2, 2, 1])
        with cs1:
            sat_sym   = st.selectbox("Pozisyon", list(p.pozisyonlar.keys()), key="sat_sym")
        with cs2:
            sat_fiyat = st.number_input("Satış Fiyatı (₺)", min_value=0.01, value=guncel_f or 1.0, step=0.01, key="sat_fiyat")
        with cs3:
            st.write(""); st.write("")
            if st.button("🔴 Sat", use_container_width=True):
                try:
                    tarih = pd.Timestamp.now().date().isoformat()
                    adet_once = p.pozisyonlar[sat_sym].adet
                    gelir = p.sat(sat_sym, sat_fiyat, tarih)
                    # Ham fiyatı kaydet; load_portfolio replay'de _efektif_satis tekrar uygulanır
                    save_islem(DB, sat_sym, "SAT", tarih, sat_fiyat, adet_once, gelir)
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
            rows = [{"Tarih": i.tarih, "Sembol": i.symbol, "Yön": i.yon,
                     "Fiyat": round(i.fiyat,2), "Adet": round(i.adet,2),
                     "Tutar": round(i.tutar,2), "Gerekçe": i.gerekce}
                    for i in p.islemler]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    if st.button("🗑️ Portföyü Sıfırla (kalıcı sil)", type="secondary"):
        temizle_portfolio(DB)
        st.session_state.portfolio = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# 🔬 BACKTEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown("## 🔬 Backtest — SMA Kesişim Stratejisi")

    with st.expander("Bu sekme ne yapıyor?"):
        st.markdown("""
Bir **alım-satım stratejisini geçmişe uygular** ve sonuçları ölçer.

**Kullanılan strateji:** SMA50 > SMA200 ise "long" (tutuyorum), değilse "nakit" (satıyorum).

**Eğitim / Test ayrımı:** Veriyi ikiye böler. Eğitim kısmında strateji iyi görünebilir
çünkü o veriye zaten "bakarak" üretildi. Test kısmı (out-of-sample) gerçek ölçüttür —
strateji hiç görmediği veride ne yapıyor?

**Benchmark:** Basit "al ve tut" stratejisi. Çoğu aktif strateji bunu geçemez —
bu dürüst bir gerçektir.
        """)

    if not sym:
        st.info("Sol taraftan bir hisse seç.")
    elif not fr or not fr.ok:
        st.warning(f"Veri alınamadı: {fr.note if fr else ''}")
    else:
        if len(df) < 210:
            st.warning(f"Veri az ({len(df)} gün) — SMA200 için 210+ gün önerilir.")

        test_orani = st.slider("Test dönemi oranı", 0.1, 0.5, 0.3, 0.05)
        egitim, test = train_test_bol(df, test_orani)
        r_e = backtest(egitim, strateji_sma_kesisim, costs=config.COSTS)
        r_t = backtest(test,   strateji_sma_kesisim, costs=config.COSTS)

        col_e, col_t = st.columns(2)
        for col, r, baslik in [(col_e, r_e, f"Eğitim ({r_e.gun_sayisi} gün)"),
                               (col_t, r_t, f"Test / Out-of-sample ({r_t.gun_sayisi} gün)")]:
            with col:
                st.markdown(f"**{baslik}**")
                m1, m2 = st.columns(2)
                m1.metric("Strateji", f"{r.getiri_pct:+.1f}%")
                m2.metric("Al-tut",   f"{r.benchmark_pct:+.1f}%")
                st.metric("Fark", f"{r.fark_pct:+.1f}%")
                st.metric("Max Düşüş", f"{r.max_dusus_pct:.1f}%")
                st.metric("Sharpe",    f"{r.sharpe:.2f}")
                st.metric("İşlem",     r.islem_sayisi)

        st.info("ℹ️ Fark negatif = strateji basit al-tutu geçemiyor. Bu çok yaygındır — dürüst sonuç budur.")


# ══════════════════════════════════════════════════════════════════════════════
# 📅 TARİHSEL
# ══════════════════════════════════════════════════════════════════════════════
with tab_tarihsel:
    st.markdown("## 📅 Tarihsel Temel Oranlar")

    with st.expander("Bu sekme ne yapıyor?"):
        st.markdown("""
**'Bu hisse benzer durumda ne yapmış?'** sorusunu gerçek geçmiş veriyle yanıtlar.

Örneğin: "THYAO günde %8+ yükseldiğinde, sonraki 5-20 günde ne olmuş?"

**Önemli uyarılar:**
- Az örnek (n < 10) = güvenilmez. Her zaman "Güvenilir" sütununu kontrol et.
- Korelasyon nedensellik değildir. "Ocak'ta yükselmiş" = "Ocak'ta yükselecek" demek değildir.
- Geçmiş performans geleceği garantilemez.
        """)

    if not sym:
        st.info("Sol taraftan bir hisse seç.")
    elif not fr or not fr.ok:
        st.warning(f"Veri alınamadı: {fr.note if fr else ''}")
    else:
        esik = st.slider("Günlük sıçrama eşiği (%)", 1.0, 15.0,
                         float(config.HISTORICAL["sicrama_esigi_pct"]), 0.5)
        dag = olay_calismasi(fr.data, esik_pct=esik, ileri_gun=config.HISTORICAL["ileri_gun"])
        st.markdown(f"### {sym}: %{esik:.0f}+ günlük yükseliş sonrası ne oldu?")

        rows = []
        for ufuk, d in dag.items():
            if d.n == 0:
                rows.append({"Ufuk": f"{ufuk} gün", "n": 0, "Medyan": "—",
                             "Ort.": "—", "Min": "—", "Max": "—",
                             "Pozitif Oran": "—", "Güvenilir": "❌", "Not": d.not_})
            else:
                rows.append({"Ufuk": f"{ufuk} gün", "n": d.n,
                             "Medyan":        f"{d.medyan_pct:+.1f}%",
                             "Ort.":          f"{d.ortalama_pct:+.1f}%",
                             "Min":           f"{d.min_pct:+.1f}%",
                             "Max":           f"{d.max_pct:+.1f}%",
                             "Pozitif Oran":  f"{d.pozitif_orani:.0%}",
                             "Güvenilir":     "✅" if d.guvenilir else "⚠️ Az örnek",
                             "Not":           d.not_ or ""})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Aylık Mevsimsellik")
        st.caption("Hangi ay tarihsel olarak daha iyi olmuş? En az 2 yıl veri önerilir.")
        try:
            mvs = mevsimsellik_aylik(fr.data)
            st.dataframe(mvs if not mvs.empty else pd.DataFrame(), use_container_width=True)
            if mvs.empty: st.info("Yeterli veri yok.")
        except Exception:
            st.info("Hesaplanamadı.")

        st.caption("⚠️ Az örnek = güvenilmez. Geçmiş performans geleceği garantilemez.")


# ══════════════════════════════════════════════════════════════════════════════
# 🎯 KALİBRASYON
# ══════════════════════════════════════════════════════════════════════════════
with tab_kalibrasyon:
    st.markdown("## 🎯 Kalibrasyon — Sinyal İsabeti")
    st.caption("Tahminlerin kalıcı olarak kaydedilir. Sayfa yenilense de silinmez.")

    with st.expander("Bu sekme ne yapıyor?"):
        st.markdown("""
**Kendi tahminlerini takip etmen için bir not defteri.**

1. "Bu hisse 14 gün içinde yükselir" gibi bir tahmin yapıyorsun
2. Tahminini buraya kaydediyorsun
3. 14 gün sonra gerçekleşeni giriyorsun
4. Sistem isabetini hesaplıyor ve yazı-tura (%50) ile karşılaştırıyor

**Neden önemli?** Çoğu insan tahminlerini hatırlarken isabetlileri hatırlar,
hatalıları unutur. Bu sekme seni dürüst tutar.
        """)

    tahminler = st.session_state.tahminler

    with st.expander("➕ Yeni Tahmin Ekle", expanded=not bool(tahminler)):
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            k_sym    = st.text_input("Sembol", value=sym or "", key="k_sym")
            k_yon    = st.selectbox("Tahmin yönü", ["pozitif","negatif"], key="k_yon")
        with ck2:
            k_sinyal = st.text_input("Sinyal tipi", value="SMA_kesisim",
                                     placeholder="RSI_dusuk · MACD_kesisim", key="k_sinyal")
            k_ufuk   = st.number_input("Ufuk (gün)", min_value=1, value=14, key="k_ufuk")
        with ck3:
            k_tarih  = st.text_input("Tarih", value=pd.Timestamp.now().date().isoformat(), key="k_tarih")
        if st.button("Tahmin Ekle", type="primary"):
            t = Tahmin(k_sym.strip().upper(), k_tarih, k_yon, k_sinyal, int(k_ufuk))
            db_id = save_tahmin(DB, t)
            t.db_id = db_id
            st.session_state.tahminler.append(t)
            st.success("Eklendi ve kaydedildi.")
            st.rerun()

    if not tahminler:
        st.info("Henüz tahmin yok. Yukarıdan ekle.")
    else:
        bekleyenler = [(i, t) for i, t in enumerate(tahminler) if t.gerceklesen_pct is None]
        if bekleyenler:
            st.divider()
            st.markdown("### Gerçekleşeni Gir")
            secenekler = {f"{t.symbol} · {t.yon} · {t.sinyal_tipi} ({t.tarih})": (i, t)
                          for i, t in bekleyenler}
            secim_k = st.selectbox("Hangi tahmin?", list(secenekler.keys()), key="k_secim")
            gercek_pct = st.number_input("Gerçekleşen değişim %", step=0.1, key="k_gercek")
            if st.button("Kaydet", type="primary"):
                idx, t = secenekler[secim_k]
                update_tahmin_gercek(DB, t.db_id, gercek_pct)
                st.session_state.tahminler[idx] = gercek_ekle(t, gercek_pct)
                st.success("Kaydedildi.")
                st.rerun()

        sonuclar = kalibre_et(tahminler, min_ornek=10)
        if sonuclar:
            st.divider()
            st.markdown("### Kalibrasyon Sonuçları")
            k_rows = [{"Sinyal": s.sinyal_tipi, "n": s.n,
                       "İsabet %": f"{s.isabet_orani*100:.0f}%" if s.isabet_orani is not None else "—",
                       "Yazı-tura farkı": f"{s.yazitura_farki:+.3f}" if s.yazitura_farki is not None else "—",
                       "Güvenilir": "✅" if s.guvenilir else "⚠️ Az örnek",
                       "Not": s.not_ or ""}
                      for s in sonuclar]
            st.dataframe(pd.DataFrame(k_rows), use_container_width=True, hide_index=True)

        with st.expander(f"📋 Tüm Tahminler ({len(tahminler)})"):
            t_rows = [{"Sembol": t.symbol, "Tarih": t.tarih, "Yön": t.yon,
                       "Sinyal": t.sinyal_tipi, "Ufuk": f"{t.ufuk_gun}g",
                       "Gerçekleşen": f"{t.gerceklesen_pct:+.1f}%" if t.gerceklesen_pct is not None else "⏳ bekliyor"}
                      for t in tahminler]
            st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)

        if st.button("🗑️ Tüm Tahminleri Sil (kalıcı)", type="secondary"):
            temizle_tahminler(DB)
            st.session_state.tahminler = []
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ⚠️ RİSK
# ══════════════════════════════════════════════════════════════════════════════
with tab_risk:
    st.markdown("## ⚠️ Risk Yönetimi")
    st.caption(f"Eşikler — pozisyon max: %{config.RISK['pozisyon_pct']*100:.0f} · "
               f"yoğunlaşma uyarı: %{config.RISK['yogunlasma_uyari_pct']*100:.0f} · "
               f"stop-loss: %{abs(config.RISK['stop_loss_pct'])*100:.0f}")

    st.markdown("### Pozisyon Büyüklüğü Hesaplama")
    st.caption("'Bu hisseden kaç TL almalıyım?' — tek pozisyon için sermayenin belirli bir yüzdesini kullan")
    cr1, cr2 = st.columns(2)
    with cr1:
        r_sermaye = st.number_input("Toplam Sermaye (₺)", min_value=1000.0,
                                    value=float(config.INITIAL_CAPITAL), step=1000.0)
    with cr2:
        varsayilan = float(df["Close"].iloc[-1]) if (fr and fr.ok) else 100.0
        r_fiyat = st.number_input("Hisse Fiyatı (₺)", min_value=0.01, value=varsayilan, step=0.01)

    pb = risk.pozisyon_buyuklugu(r_sermaye, r_fiyat, config.RISK["pozisyon_pct"])
    cm1, cm2, cm3 = st.columns(3)
    cm1.metric("Tahsis Tutarı",   f"{pb['tahsis_tutar']:,.0f} ₺")
    cm2.metric("Alınabilir Adet", str(pb["adet"]))
    cm3.metric("Gerçek Tutar",    f"{pb['gercek_tutar']:,.0f} ₺")

    p = st.session_state.portfolio
    if p.pozisyonlar:
        fiyatlar_bilinen = {sym: float(df["Close"].iloc[-1])} if (fr and fr.ok and sym) else {}
        poz_deg = {s: poz.adet * fiyatlar_bilinen.get(s, poz.alis_fiyat) for s, poz in p.pozisyonlar.items()}

        col_y, col_s = st.columns(2)
        with col_y:
            st.markdown("### Yoğunlaşma Kontrolü")
            uyarilar = risk.yogunlasma_kontrol(poz_deg, config.RISK["yogunlasma_uyari_pct"])
            for u in uyarilar: st.warning(u)
            if not uyarilar: st.success("✅ Yoğunlaşma riski yok.")
        with col_s:
            st.markdown("### Stop-Loss Kontrolü")
            poz_dict = {s: {"alis_fiyat": poz.alis_fiyat} for s, poz in p.pozisyonlar.items()}
            stop_uyarilar = risk.stop_loss_kontrol(poz_dict, fiyatlar_bilinen, config.RISK["stop_loss_pct"])
            for u in stop_uyarilar: st.error(u)
            if not stop_uyarilar: st.success("✅ Stop-loss tetiklenmedi.")
    else:
        st.info("Portföy sekmesinden pozisyon eklenince burada analiz görünür.")

    st.divider()
    st.markdown("### Korelasyon Matrisi")
    st.caption("Hisseler aynı yönde mi hareket ediyor? Yüksek korelasyon = çeşitlendirme azalır.")
    if st.button("Hesapla"):
        with st.spinner("Veriler çekiliyor..."):
            results = fetch_many(watchlist[:6], period="3mo")
        gecerli = {s: r.data["Close"].rename(s) for s, r in results.items() if r.ok}
        if len(gecerli) >= 2:
            fiyat_df = pd.concat(list(gecerli.values()), axis=1).dropna()
            corr = risk.korelasyon_matrisi(fiyat_df)
            st.dataframe(corr, use_container_width=True)
            st.caption("1.00 = tam aynı yönde · 0 = bağımsız · -1.00 = tam ters yönde")
        else:
            st.warning("Yeterli veri alınamadı.")


# ══════════════════════════════════════════════════════════════════════════════
# 📚 NASIL ÇALIŞIR?
# ══════════════════════════════════════════════════════════════════════════════
with tab_ogren:
    st.markdown("## 📚 Göstergeler Nasıl Okunur?")
    st.caption("Bu sekme sana yatırım tavsiyesi vermez — göstergelerin ne anlama geldiğini açıklar.")

    with st.expander("📈 Hareketli Ortalamalar (SMA20 · SMA50 · SMA200)", expanded=True):
        st.markdown("""
**Ne yapar?** Son N günün kapanış fiyatının ortalamasını alır. Günlük dalgalanmaları yumuşatır.

| Gösterge | Hesap | Ne gösterir |
|----------|-------|-------------|
| SMA20 | Son 20 günün ortalaması | Kısa vadeli eğilim |
| SMA50 | Son 50 günün ortalaması | Orta vadeli eğilim |
| SMA200 | Son 200 günün ortalaması | Uzun vadeli eğilim |

**Popüler sinyaller:**
- **Altın Kesişim:** SMA50, SMA200'ün *üstüne* çıkarsa → genel yükseliş eğilimi
- **Ölüm Kesişimi:** SMA50, SMA200'ün *altına* inerse → genel düşüş eğilimi

⚠️ **Dikkat:** Kesişim sinyalleri gecikmeli gelir (lagging indicator). Fiyat zaten hareket etmiştir.
        """)

    with st.expander("📊 RSI — Göreceli Güç Endeksi"):
        st.markdown("""
**Ne yapar?** Son 14 günde fiyatın ne kadar hızlı ve hangi yönde hareket ettiğini ölçer. 0–100 arası değer.

| Değer | Anlam |
|-------|-------|
| ≥ 70 | **Aşırı alım** — çok hızlı yükseldi, düzeltme gelebilir |
| 30–70 | **Nötr** — belirgin sinyal yok |
| ≤ 30 | **Aşırı satım** — çok hızlı düştü, toparlanma gelebilir |

⚠️ Aşırı alım = "hemen sat" değildir. Güçlü trendlerde RSI uzun süre 70+ kalabilir.
        """)

    with st.expander("📉 MACD"):
        st.markdown("""
**Ne yapar?** İki farklı hızda hareketli ortalama arasındaki farkı ölçer.

- **MACD çizgisi:** EMA12 − EMA26
- **Sinyal çizgisi:** MACD'nin 9 günlük ortalaması
- **Histogram:** MACD − Sinyal

**Okuma:**
- MACD, sinyal çizgisinin *üstüne* çıkarsa → kısa vadeli momentum pozitife döndü
- MACD, sinyal çizgisinin *altına* inerse → kısa vadeli momentum negatife döndü
- Histogram sıfır çizgisini geçerken bu sinyaller oluşur

⚠️ MACD da gecikmeli bir göstergedir. Tek başına karar vermek için yeterli değildir.
        """)

    with st.expander("📐 Bollinger Bantları"):
        st.markdown("""
**Ne yapar?** Fiyatın istatistiksel olarak "normal" aralığını gösterir.

- **Orta bant:** SMA20
- **Üst bant:** SMA20 + 2 standart sapma
- **Alt bant:** SMA20 − 2 standart sapma

Fiyatların yaklaşık %95'i bantlar arasında kalır.

**Okuma:**
- Fiyat üst banda ulaşırsa → olası aşırı alım
- Fiyat alt banda ulaşırsa → olası aşırı satım
- Bantlar daralırsa → düşük oynaklık, genellikle büyük bir hareket öncesi sessizlik
        """)

    with st.expander("📋 Nasıl Başlamalıyım? — Adım Adım"):
        st.markdown("""
1. **İzleme Listesi** sekmesine git — takip ettiğin hisselerin genel durumuna bak
2. İlgini çeken bir hisse seç (sol taraftaki dropdown'dan)
3. **Panel** sekmesinde grafiği incele — fiyat, SMA'lar, RSI, MACD'e bak
4. **Tarihsel** sekmesinde "Benzer durumlarda ne olmuş?" sorusunu sor
5. **Backtest** sekmesinde bir stratejinin geçmişte ne kadar işe yaradığını test et
6. **Kalibrasyon** sekmesinde tahminlerini kaydet ve isabetini takip et

**Altın kural:** Hiçbir gösterge tek başına güvenilir değildir.
Birden fazla gösterge aynı yönü gösteriyorsa bu daha güçlü bir sinyaldir.
Ama yine de: **Bu bir yatırım tavsiyesi değildir.**
        """)

    st.info("💡 Her sekmede 'Bu sekme ne yapıyor?' açıklamasını bul — göstergelerin ne anlama geldiği orada da açıklanıyor.")
