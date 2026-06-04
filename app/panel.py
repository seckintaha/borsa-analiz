"""
Streamlit panel (Aşama 0-9).

Çalıştırmak için proje kök klasöründe:
    pip install -r requirements.txt
    streamlit run app/panel.py

Sekmeler: Panel · Tarama · Portföy · Backtest · Tarihsel · Kalibrasyon · Risk
Sade ve net tutuldu; her sayının kaynağı ve zaman damgası gösterilir.
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

st.set_page_config(page_title="Borsa Analiz Paneli", page_icon="📈", layout="wide")
init_db(config.DB_PATH)

# --- Oturum durumu ---
if "portfolio" not in st.session_state:
    st.session_state.portfolio = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
if "kalibrasyon_tahminler" not in st.session_state:
    st.session_state.kalibrasyon_tahminler = []


@st.cache_data(ttl=300)
def _veri(sym, period, interval):
    return fetch_history(sym, period, interval)


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

# Kenar çubuğu tüm sekmeler için ortak
with st.sidebar:
    st.header("Ayarlar")
    sym = st.text_input("Sembol", value="THYAO.IS",
                        help="BIST için sona .IS ekleyin (THYAO.IS). Global: AAPL")
    period = st.selectbox("Dönem", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
    interval = st.selectbox("Aralık", ["1d", "1wk", "1h"], index=0)

sym = sym.strip().upper()
fr = _veri(sym, period, interval)

# Veri varsa kaydet ve göstergeleri hesapla (tüm sekmeler kullanır)
df = None
if fr.ok:
    save_prices(config.DB_PATH, fr)
    df = add_indicators(fr.data)

(panel_sekme, tarama_sekme, portfoy_sekme,
 backtest_sekme, tarihsel_sekme, kalibrasyon_sekme, risk_sekme) = st.tabs(
    ["Panel", "Tarama", "Portföy", "Backtest", "Tarihsel", "Kalibrasyon", "Risk"]
)

# ========== PANEL ==========
with panel_sekme:
    if not fr.ok:
        st.error(f"'{sym}' için veri alınamadı: {fr.note}")
    else:
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

# ========== TARAMA ==========
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

# ========== PORTFÖY ==========
with portfoy_sekme:
    st.subheader("Paper Portföy (sanal)")
    st.caption("Gerçek para işlemi yapılmaz. İşlem maliyetleri config.py'den uygulanır.")

    p = st.session_state.portfolio
    guncel_fiyat = float(df["Close"].iloc[-1]) if fr.ok else None
    guncel_fiyatlar = {sym: guncel_fiyat} if guncel_fiyat else {}

    ozet = p.ozet(guncel_fiyatlar)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Başlangıç", f"{ozet['baslangic']:,.0f} ₺")
    c2.metric("Nakit", f"{ozet['nakit']:,.0f} ₺")
    c3.metric("Güncel değer", f"{ozet['guncel_deger']:,.0f} ₺")
    c4.metric("Getiri", f"{ozet['getiri_pct']:+.2f}%")

    st.divider()
    st.markdown("**Alım işlemi**")
    ca1, ca2, ca3 = st.columns(3)
    with ca1:
        al_sym = st.text_input("Sembol (AL)", value=sym, key="al_sym")
        al_fiyat = st.number_input("Fiyat", min_value=0.01,
                                   value=guncel_fiyat or 1.0, step=0.01, key="al_fiyat")
    with ca2:
        al_tutar = st.number_input("Tutar (₺)", min_value=100.0,
                                   value=float(config.INITIAL_CAPITAL * config.RISK["pozisyon_pct"]),
                                   step=100.0, key="al_tutar")
        al_gerekce = st.text_input("Gerekçe (isteğe bağlı)", key="al_gerekce")
    with ca3:
        st.write("")
        st.write("")
        if st.button("Al"):
            try:
                adet = p.al(al_sym, al_fiyat, pd.Timestamp.now().date().isoformat(),
                            tutar=al_tutar, gerekce=al_gerekce)
                st.success(f"{adet:.2f} adet {al_sym.upper()} alındı.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    if p.pozisyonlar:
        st.divider()
        st.markdown("**Açık pozisyonlar**")
        poz_rows = [{"Sembol": s, "Adet": round(poz.adet, 2),
                     "Alış fiyatı": round(poz.alis_fiyat, 2),
                     "Alış tarihi": poz.alis_tarih, "Gerekçe": poz.gerekce}
                    for s, poz in p.pozisyonlar.items()]
        st.dataframe(pd.DataFrame(poz_rows), use_container_width=True, hide_index=True)

        st.markdown("**Satış işlemi**")
        cs1, cs2, cs3 = st.columns(3)
        with cs1:
            sat_sym = st.selectbox("Sembol (SAT)", list(p.pozisyonlar.keys()), key="sat_sym")
        with cs2:
            sat_fiyat = st.number_input("Satış fiyatı", min_value=0.01,
                                        value=guncel_fiyat or 1.0, step=0.01, key="sat_fiyat")
        with cs3:
            st.write("")
            st.write("")
            if st.button("Sat"):
                try:
                    gelir = p.sat(sat_sym, sat_fiyat, pd.Timestamp.now().date().isoformat())
                    st.success(f"{sat_sym} satıldı, gelir: {gelir:,.2f} ₺")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

        if fr.ok and p.islemler:
            st.divider()
            st.markdown("**Çok ufuklu getiri (ilk girişten itibaren)**")
            ilk_tarih = p.islemler[0].tarih
            try:
                getiriler = cok_ufuklu_getiri(fr.data["Close"], ilk_tarih, config.HORIZONS)
                g_rows = [{"Ufuk": ufuk,
                           "Getiri %": f"{v['getiri_pct']:+.2f}%" if v.get("getiri_pct") is not None else "veri yok",
                           "Tarih": v.get("tarih") or "—"}
                          for ufuk, v in getiriler.items()]
                st.dataframe(pd.DataFrame(g_rows), use_container_width=True, hide_index=True)
            except Exception:
                st.info("Çok ufuklu getiri hesaplanamadı (giriş tarihi veri aralığı dışında olabilir).")
    else:
        st.info("Henüz açık pozisyon yok.")

    if p.islemler:
        st.divider()
        st.markdown("**İşlem geçmişi**")
        islem_rows = [{"Tarih": i.tarih, "Sembol": i.symbol, "Yön": i.yon,
                       "Fiyat": round(i.fiyat, 2), "Adet": round(i.adet, 2),
                       "Tutar": round(i.tutar, 2)} for i in p.islemler]
        st.dataframe(pd.DataFrame(islem_rows), use_container_width=True, hide_index=True)

    if st.button("Portföyü sıfırla"):
        st.session_state.portfolio = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
        st.rerun()

# ========== BACKTEST ==========
with backtest_sekme:
    st.subheader("Backtest — SMA Kesişim Stratejisi")
    st.caption("50g > 200g ise long, değilse nakit. İşlem maliyetleri (komisyon + kayma) dahil. Yatırım tavsiyesi değildir.")

    if not fr.ok:
        st.warning(f"Veri yok: {fr.note}")
    else:
        test_orani = st.slider("Test dönemi oranı", 0.1, 0.5, 0.3, 0.05, key="bt_test_oran")

        if len(df) < 210:
            st.warning(f"Veri az ({len(df)} gün). SMA200 için en az 210 gün önerilir; sonuçlar güvenilmez.")

        egitim, test = train_test_bol(df, test_orani)
        r_e = backtest(egitim, strateji_sma_kesisim, costs=config.COSTS)
        r_t = backtest(test, strateji_sma_kesisim, costs=config.COSTS)

        col_e, col_t = st.columns(2)
        with col_e:
            st.markdown(f"**Eğitim dönemi** ({r_e.gun_sayisi} gün)")
            st.metric("Strateji", f"{r_e.getiri_pct:+.1f}%")
            st.metric("Benchmark (al-tut)", f"{r_e.benchmark_pct:+.1f}%")
            st.metric("Fark", f"{r_e.fark_pct:+.1f}%")
            st.metric("Max düşüş", f"{r_e.max_dusus_pct:.1f}%")
            st.metric("Sharpe", f"{r_e.sharpe:.2f}")
            st.metric("İşlem sayısı", r_e.islem_sayisi)
        with col_t:
            st.markdown(f"**Test dönemi / out-of-sample** ({r_t.gun_sayisi} gün)")
            st.metric("Strateji", f"{r_t.getiri_pct:+.1f}%")
            st.metric("Benchmark (al-tut)", f"{r_t.benchmark_pct:+.1f}%")
            st.metric("Fark", f"{r_t.fark_pct:+.1f}%")
            st.metric("Max düşüş", f"{r_t.max_dusus_pct:.1f}%")
            st.metric("Sharpe", f"{r_t.sharpe:.2f}")
            st.metric("İşlem sayısı", r_t.islem_sayisi)

        st.caption("Fark negatifse strateji benchmark'ı geçemiyor — bu dürüst bir sonuçtur. Geçmişte çalışan strateji ileride çalışmayabilir.")

# ========== TARİHSEL ==========
with tarihsel_sekme:
    st.subheader("Tarihsel Temel Oranlar")
    st.caption("'Benzer durumda ne oldu' sorusunu geçmiş veriyle yanıtlar. Az örnek varsa açıkça belirtilir.")

    if not fr.ok:
        st.warning(f"Veri yok: {fr.note}")
    else:
        esik = st.slider("Günlük sıçrama eşiği (%)", 1.0, 15.0,
                         float(config.HISTORICAL["sicrama_esigi_pct"]), 0.5, key="th_esik")

        dag = olay_calismasi(fr.data, esik_pct=esik, ileri_gun=config.HISTORICAL["ileri_gun"])
        st.markdown(f"**{sym}: %{esik:.0f}+ günlük sıçrama sonrası ne oldu?**")

        rows = []
        for ufuk, d in dag.items():
            if d.n == 0:
                rows.append({"Ufuk (gün)": ufuk, "n": 0, "Medyan %": "—",
                             "Ortalama %": "—", "Min %": "—", "Max %": "—",
                             "Pozitif oran": "—", "Güvenilir": "Hayır", "Not": d.not_})
            else:
                rows.append({
                    "Ufuk (gün)": ufuk, "n": d.n,
                    "Medyan %": f"{d.medyan_pct:+.1f}%",
                    "Ortalama %": f"{d.ortalama_pct:+.1f}%",
                    "Min %": f"{d.min_pct:+.1f}%",
                    "Max %": f"{d.max_pct:+.1f}%",
                    "Pozitif oran": f"{d.pozitif_orani:.0%}",
                    "Güvenilir": "Evet" if d.guvenilir else "Hayır",
                    "Not": d.not_ or "",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**Aylık mevsimsellik**")
        try:
            mvs = mevsimsellik_aylik(fr.data)
            if not mvs.empty:
                st.dataframe(mvs, use_container_width=True)
            else:
                st.info("Mevsimsellik için yeterli veri yok.")
        except Exception:
            st.info("Mevsimsellik hesaplanamadı (yeterli veri yok).")

        st.caption("Geçmiş performans gelecek sonuçları garanti etmez. Az örnek = güvenilmez.")

# ========== KALİBRASYON ==========
with kalibrasyon_sekme:
    st.subheader("Kalibrasyon — Sinyal İsabeti")
    st.caption("Her tahmin kaydedilir; ufuk dolunca gerçekle karşılaştırılır. Hedef hep haklı olmak değil, isabeti dürüstçe ölçmek.")

    tahminler = st.session_state.kalibrasyon_tahminler

    st.markdown("**Yeni tahmin kaydet**")
    ck1, ck2, ck3 = st.columns(3)
    with ck1:
        k_sym = st.text_input("Sembol", value=sym, key="k_sym")
        k_yon = st.selectbox("Yön", ["pozitif", "negatif"], key="k_yon")
    with ck2:
        k_sinyal = st.text_input("Sinyal tipi (ör. RSI_dusuk)", value="SMA_kesisim", key="k_sinyal")
        k_ufuk = st.number_input("Ufuk (gün)", min_value=1, value=14, key="k_ufuk")
    with ck3:
        k_tarih = st.text_input("Tarih", value=pd.Timestamp.now().date().isoformat(), key="k_tarih")
        st.write("")
        if st.button("Tahmin ekle"):
            st.session_state.kalibrasyon_tahminler.append(
                Tahmin(k_sym, k_tarih, k_yon, k_sinyal, int(k_ufuk))
            )
            st.success("Tahmin eklendi. Ufuk dolunca 'Gerçeği kaydet' ile güncelleyin.")

    if tahminler:
        st.divider()
        bekleyenler = [(i, t) for i, t in enumerate(tahminler) if t.gerceklesen_pct is None]
        if bekleyenler:
            st.markdown("**Gerçekleşeni kaydet**")
            secenekler = {f"{i}: {t.symbol} {t.yon} {t.sinyal_tipi} ({t.tarih})": i
                          for i, t in bekleyenler}
            secim = st.selectbox("Tahmin seç", list(secenekler.keys()), key="k_secim")
            gercek_pct = st.number_input("Gerçekleşen değişim %", step=0.1, key="k_gercek")
            if st.button("Gerçeği kaydet"):
                idx = secenekler[secim]
                st.session_state.kalibrasyon_tahminler[idx] = gercek_ekle(
                    st.session_state.kalibrasyon_tahminler[idx], gercek_pct
                )
                st.success("Kaydedildi.")
                st.rerun()

        sonuclar = kalibre_et(tahminler, min_ornek=10)
        if sonuclar:
            st.divider()
            st.markdown("**Kalibrasyon sonuçları**")
            k_rows = [{"Sinyal tipi": s.sinyal_tipi, "n": s.n,
                       "İsabet %": f"{s.isabet_orani*100:.0f}%" if s.isabet_orani is not None else "—",
                       "Yazı-tura farkı": f"{s.yazitura_farki:+.3f}" if s.yazitura_farki is not None else "—",
                       "Güvenilir": "Evet" if s.guvenilir else "Hayır",
                       "Not": s.not_ or ""}
                      for s in sonuclar]
            st.dataframe(pd.DataFrame(k_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Henüz değerlendirilebilir tahmin yok (gerçekleşen değer girilmemiş).")

        st.divider()
        st.markdown("**Tüm tahminler**")
        t_rows = [{"Sembol": t.symbol, "Tarih": t.tarih, "Yön": t.yon,
                   "Sinyal": t.sinyal_tipi, "Ufuk (gün)": t.ufuk_gun,
                   "Gerçekleşen %": t.gerceklesen_pct if t.gerceklesen_pct is not None else "bekliyor"}
                  for t in tahminler]
        st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)

        if st.button("Tüm tahminleri temizle"):
            st.session_state.kalibrasyon_tahminler = []
            st.rerun()
    else:
        st.info("Henüz tahmin yok. Yukarıdan yeni tahmin ekleyebilirsiniz.")

# ========== RİSK ==========
with risk_sekme:
    st.subheader("Risk Yönetimi")
    st.caption(
        f"Eşikler config.py'den — "
        f"pozisyon max: %{config.RISK['pozisyon_pct']*100:.0f} · "
        f"yoğunlaşma uyarı: %{config.RISK['yogunlasma_uyari_pct']*100:.0f} · "
        f"stop-loss: %{abs(config.RISK['stop_loss_pct'])*100:.0f}"
    )

    st.markdown("**Pozisyon büyüklüğü hesaplama**")
    cr1, cr2 = st.columns(2)
    with cr1:
        r_sermaye = st.number_input("Sermaye (₺)", min_value=1000.0,
                                    value=float(config.INITIAL_CAPITAL), step=1000.0, key="r_sermaye")
    with cr2:
        varsayilan_fiyat = float(df["Close"].iloc[-1]) if fr.ok else 100.0
        r_fiyat = st.number_input("Hisse fiyatı (₺)", min_value=0.01,
                                  value=varsayilan_fiyat, step=0.01, key="r_fiyat")

    pb = risk.pozisyon_buyuklugu(r_sermaye, r_fiyat, config.RISK["pozisyon_pct"])
    cm1, cm2, cm3 = st.columns(3)
    cm1.metric("Tahsis tutarı", f"{pb['tahsis_tutar']:,.0f} ₺")
    cm2.metric("Adet", str(pb["adet"]))
    cm3.metric("Gerçek tutar", f"{pb['gercek_tutar']:,.0f} ₺")

    p = st.session_state.portfolio
    if p.pozisyonlar:
        fiyatlar_bilinen = {sym: float(df["Close"].iloc[-1])} if fr.ok else {}
        poz_degerleri = {s: poz.adet * fiyatlar_bilinen.get(s, poz.alis_fiyat)
                        for s, poz in p.pozisyonlar.items()}

        st.divider()
        st.markdown("**Yoğunlaşma kontrolü**")
        uyarilar = risk.yogunlasma_kontrol(poz_degerleri, config.RISK["yogunlasma_uyari_pct"])
        if uyarilar:
            for u in uyarilar:
                st.warning(u)
        else:
            st.success("Yoğunlaşma riski yok.")

        st.divider()
        st.markdown("**Stop-loss kontrolü**")
        poz_dict = {s: {"alis_fiyat": poz.alis_fiyat} for s, poz in p.pozisyonlar.items()}
        stop_uyarilar = risk.stop_loss_kontrol(poz_dict, fiyatlar_bilinen, config.RISK["stop_loss_pct"])
        if stop_uyarilar:
            for u in stop_uyarilar:
                st.error(u)
        else:
            st.success("Stop-loss tetiklenmedi.")
    else:
        st.info("Portföy sekmesinden pozisyon eklenirse burada yoğunlaşma ve stop-loss analizi görünür.")

    st.divider()
    st.markdown("**Korelasyon matrisi**")
    st.caption(f"İzleme listesinin ilk 6 hissesi · 3 aylık günlük getiri · Yüksek korelasyon = çeşitlendirme azalır")
    if st.button("Korelasyon matrisini hesapla"):
        with st.spinner("Veriler çekiliyor..."):
            results = fetch_many(config.WATCHLIST[:6], period="3mo")
        gecerli = {s: r.data["Close"].rename(s) for s, r in results.items() if r.ok}
        if len(gecerli) >= 2:
            fiyat_df = pd.concat(list(gecerli.values()), axis=1).dropna()
            corr = risk.korelasyon_matrisi(fiyat_df)
            st.dataframe(corr, use_container_width=True)
        else:
            st.warning("Veri yok — en az 2 hisse için veri gerekmektedir.")
