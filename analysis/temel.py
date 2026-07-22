"""
Temel analiz: F/K, PD/DD, temettü, ROE, marj, büyüme (Görev #6, #8, #9).

Kaynak: TradingView temel verileri (tv_temel_tara). Gerçek rakamlar; veri
yoksa "veri yok" der, uydurmaz.

Komutlar:
  tek_hisse_temel  → /temel SEMBOL  (bir şirketin temel metrikleri)
  deger_taramasi   → /deger         (düşük değerli hisse taraması)
  buyume_temettu   → /buyume SEMBOL (büyüme mi temettü hissesi mi)
"""

from __future__ import annotations
from data.tv_scanner import tv_temel_tara, TVTemel


# TR yüksek enflasyon ortamında nominal çarpanlar çarpıktır (enflasyon
# muhasebesi / varlık yeniden değerleme). CPI SAYISI UYDURULMAZ — sadece
# değerlerin nominal olduğu ve göreli değerlendirme gerektiği belirtilir.
ENFLASYON_NOTU = (
    "ℹ️ TR yüksek enflasyonda: F/K, ROE, büyüme NOMİNAL değerlerdir; enflasyon "
    "bunları şişirir ve düşük F/K bazen enflasyon muhasebesi kaynaklıdır — "
    "sektör ortalamasıyla göreli değerlendir."
)


def _bist_ticker(sembol: str) -> str:
    kod = sembol.replace(".IS", "").upper()
    return f"BIST:{kod}"


def _sektor_gorel(t, tum_liste) -> list:
    """
    Hissenin F/K, PD/DD, ROE'sini KENDİ sektör medyanıyla kıyaslar. Enflasyon
    nötrdür: sektördeki herkes benzer şişer, göreli konum anlamlı kalır.
    """
    import statistics
    uyeler = [x for x in (tum_liste or [])
              if x.sektor == t.sektor and x.sembol != t.sembol]
    if len(uyeler) < 3:
        return []

    def _med(sec):
        v = [sec(x) for x in uyeler if sec(x) is not None and sec(x) > 0]
        return statistics.median(v) if len(v) >= 3 else None

    med_fk = _med(lambda x: x.fk)
    med_roe = _med(lambda x: x.roe)
    med_pddd = _med(lambda x: x.pddd)
    out = []
    if med_fk and t.fk and t.fk > 0:
        fark = (t.fk - med_fk) / med_fk * 100
        out.append(f"F/K {t.fk:.1f} · sektör medyanı {med_fk:.1f} → "
                   f"%{abs(fark):.0f} {'UCUZ' if fark < 0 else 'pahalı'}")
    if med_pddd and t.pddd and t.pddd > 0:
        fark = (t.pddd - med_pddd) / med_pddd * 100
        out.append(f"PD/DD {t.pddd:.2f} · sektör medyanı {med_pddd:.2f} → "
                   f"%{abs(fark):.0f} {'ucuz' if fark < 0 else 'pahalı'}")
    if med_roe is not None and t.roe is not None:
        fark = t.roe - med_roe
        out.append(f"ROE %{t.roe:.0f} · sektör medyanı %{med_roe:.0f} → "
                   f"{abs(fark):.0f} puan {'ÜSTÜNDE' if fark > 0 else 'altında'}")
    return out


# ── Tek hisse temel analiz (#8 sonuç raporları metrikleri) ────────────────────

def tek_hisse_temel(sembol: str) -> str:
    ok, hata, liste = tv_temel_tara(tickers=[_bist_ticker(sembol)])
    if not ok or not liste:
        return f"❌ {sembol.replace('.IS','')} için temel veri bulunamadı. ({hata})"
    t = liste[0]
    kod = t.sembol.replace(".IS", "")

    def f(v, son="", ondalik=2):
        return f"{v:.{ondalik}f}{son}" if v is not None else "veri yok"

    sat = [
        f"📑 {kod} — TEMEL ANALİZ",
        f"Sektör: {t.sektor}",
        f"💰 Fiyat: {f(t.fiyat)} · günlük {f(t.degisim_pct,'%',1) if t.degisim_pct is not None else '—'}",
        "",
        "📊 DEĞERLEME",
        f"   F/K (Fiyat/Kazanç): {f(t.fk)}" + _fk_yorum(t.fk),
        f"   PD/DD (Piyasa/Defter): {f(t.pddd)}" + _pddd_yorum(t.pddd),
        f"   Temettü verimi: {f(t.temettu_verim,'%')}",
        "",
        "📈 KÂRLILIK & BÜYÜME",
        f"   ROE (Özkaynak kârlılığı): {f(t.roe,'%')}" + _roe_yorum(t.roe),
        f"   Net kâr marjı: {f(t.net_marj,'%')}",
        f"   Hisse başı kâr (EPS): {f(t.eps)}",
        f"   Gelir büyümesi (yıllık): {f(t.gelir_buyume,'%')}",
    ]
    if t.piyasa_degeri:
        sat.append(f"   Piyasa değeri: {t.piyasa_degeri/1e9:.1f} milyar ₺")

    # Çeyrek momentum + bilanço tazeliği (verinin ne kadar güncel olduğunu ve
    # kârın hızlanıp yavaşladığını gösterir — TradingView gerçek verisi).
    try:
        from data.tv_scanner import tv_bilanco_tara
        from datetime import datetime as _dt
        okb, _hb, bl = tv_bilanco_tara(tickers=[_bist_ticker(sembol)])
        if okb and bl:
            b = bl[0]
            def _kirp(x):  # küçük bazdan hesaplanan uç %'yi profesyonelce göster
                return ">+200" if x > 200 else ("<-200" if x < -200 else f"{x:+.0f}")
            mom = []
            if b.eps_yoy is not None:
                yon = "hızlanıyor 📈" if b.eps_yoy > 5 else ("yavaşlıyor 📉" if b.eps_yoy < -5 else "yatay")
                mom.append(f"   Yıllık kâr büyümesi (EPS): %{_kirp(b.eps_yoy)} ({yon})")
            if b.eps_qoq is not None:
                mom.append(f"   Çeyreklik kâr değişimi (QoQ): %{_kirp(b.eps_qoq)}")
            if b.gelir_qoq is not None:
                mom.append(f"   Çeyreklik gelir değişimi: %{_kirp(b.gelir_qoq)}")
            if mom:
                sat += ["", "📊 ÇEYREK MOMENTUM"] + mom
            takvim = []
            if b.son_bilanco_ts:
                takvim.append(f"   Son bilanço: {_dt.fromtimestamp(b.son_bilanco_ts):%Y-%m-%d} "
                              "(veri buna dayanır)")
            if b.sonraki_bilanco_ts:
                nd = _dt.fromtimestamp(b.sonraki_bilanco_ts).date()
                gk = (nd - _dt.now().date()).days
                if gk >= 0:
                    uyari = " ⚠️ yakında — oynaklık riski" if gk <= 10 else ""
                    takvim.append(f"   Sonraki bilanço: {nd} (~{gk} gün sonra){uyari}")
            if takvim:
                sat += ["", "📅 BİLANÇO TAKVİMİ"] + takvim
    except Exception:
        pass

    # Sektör-göreli değerleme (enflasyon-nötr — sektör içinde herkes benzer şişer,
    # göreli konum daha anlamlıdır). Bir evren taraması ile sektör medyanı bulunur.
    try:
        ok2, _h2, tum = tv_temel_tara(limit=1000)
        gorel = _sektor_gorel(t, tum) if ok2 else None
        if gorel:
            sat += ["", f"🏭 SEKTÖRE GÖRE ({t.sektor})"]
            for g in gorel:
                sat.append(f"   {g}")
    except Exception:
        pass

    # Genel okuma
    sat += ["", "🧭 ÖZET YORUM", "   " + _genel_yorum(t)]
    sat += ["", ENFLASYON_NOTU]
    sat += ["", "⚠️ Temel veriler TradingView kaynaklıdır; yatırım tavsiyesi değildir. "
            "Detaylı teknik için /analiz " + kod]
    return "\n".join(sat)


def _fk_yorum(fk):
    if fk is None:
        return ""
    if fk < 0:
        return "  → şirket zarar ediyor (negatif)"
    if fk < 8:
        return "  → düşük (ucuz olabilir ya da risk fiyatlanıyor)"
    if fk > 25:
        return "  → yüksek (pahalı ya da büyüme bekleniyor)"
    return "  → makul aralık"


def _pddd_yorum(pddd):
    if pddd is None:
        return ""
    if pddd < 1:
        return "  → defter değerinin altında (potansiyel değer)"
    if pddd > 4:
        return "  → defter değerine göre pahalı"
    return ""


def _roe_yorum(roe):
    if roe is None:
        return ""
    if roe > 20:
        return "  → güçlü kârlılık"
    if roe < 5:
        return "  → zayıf kârlılık"
    return ""


def _genel_yorum(t: TVTemel) -> str:
    notlar = []
    if t.fk is not None and 0 < t.fk < 10 and t.pddd is not None and t.pddd < 1.5:
        notlar.append("Değerleme ucuz görünüyor (düşük F/K + düşük PD/DD)")
    if t.roe is not None and t.roe > 20:
        notlar.append("özkaynak kârlılığı yüksek")
    if t.temettu_verim is not None and t.temettu_verim > 4:
        notlar.append(f"iyi temettü veriyor (%{t.temettu_verim:.1f})")
    if t.gelir_buyume is not None and t.gelir_buyume > 20:
        notlar.append(f"hızlı büyüyor (gelir +%{t.gelir_buyume:.0f})")
    if t.fk is not None and t.fk < 0:
        notlar.append("şirket şu an zarar ediyor — dikkat")
    if not notlar:
        return "Temel metrikler karışık/nötr; sektör ortalamasıyla karşılaştır."
    return "; ".join(notlar) + "."


# ── Değer yatırımı taraması (#6) ──────────────────────────────────────────────

def deger_taramasi(n: int = 10, min_piyasa_degeri: float = 1e9) -> str:
    """
    Düşük değerli (value) hisseleri tarar: pozitif F/K < 12, PD/DD < 2,
    pozitif ROE. Likit olmayanları elemek için min piyasa değeri filtresi.
    """
    ok, hata, liste = tv_temel_tara(limit=1000)
    if not ok:
        return f"❌ Değer taraması yapılamadı: {hata}"

    adaylar = []
    for t in liste:
        if t.piyasa_degeri is None or t.piyasa_degeri < min_piyasa_degeri:
            continue
        if t.fk is None or t.fk <= 0 or t.fk > 12:
            continue
        if t.pddd is None or t.pddd > 2:
            continue
        if t.roe is None or t.roe < 8:
            continue
        # Değer skoru: düşük F/K + düşük PD/DD + yüksek ROE + temettü
        skor = 0.0
        skor += max(0, 12 - t.fk)
        skor += max(0, 2 - t.pddd) * 5
        skor += t.roe / 5
        if t.temettu_verim:
            skor += t.temettu_verim
        adaylar.append((skor, t))

    if not adaylar:
        return "🔍 Değer kriterlerini (F/K<12, PD/DD<2, ROE>8) karşılayan hisse bulunamadı."

    adaylar.sort(key=lambda x: -x[0])
    sat = [
        "💎 DEĞER YATIRIMI TARAMASI",
        "(Kriter: F/K<12 · PD/DD<2 · ROE>%8 · piyasa değeri>1 mlr)",
        "",
    ]
    for i, (skor, t) in enumerate(adaylar[:n], 1):
        kod = t.sembol.replace(".IS", "")
        tem = f" · temettü %{t.temettu_verim:.1f}" if t.temettu_verim else ""
        sat.append(f"{i}) {kod} ({t.sektor[:18]})")
        sat.append(f"   F/K {t.fk:.1f} · PD/DD {t.pddd:.2f} · ROE %{t.roe:.0f}{tem}")
    sat += ["", "💡 Değer yatırımı: piyasanın geçici olarak ucuzlattığı, sağlam "
            "bilançolu şirketleri al-tut mantığıyla bulmaya çalışır.",
            "⚠️ Düşük F/K bazen 'değer tuzağı' olabilir — sektör ve borç durumunu da bak. "
            "Yatırım tavsiyesi değildir."]
    return "\n".join(sat)


# ── Büyüme vs Temettü sınıflandırma (#9) ──────────────────────────────────────

def buyume_temettu(sembol: str) -> str:
    ok, hata, liste = tv_temel_tara(tickers=[_bist_ticker(sembol)])
    if not ok or not liste:
        return f"❌ {sembol.replace('.IS','')} verisi yok: {hata}"
    t = liste[0]
    kod = t.sembol.replace(".IS", "")

    buyume_skoru = 0
    temettu_skoru = 0
    if t.gelir_buyume is not None:
        if t.gelir_buyume > 25:
            buyume_skoru += 2
        elif t.gelir_buyume > 10:
            buyume_skoru += 1
    if t.fk is not None and t.fk > 25:
        buyume_skoru += 1   # yüksek F/K = büyüme beklentisi
    if t.temettu_verim is not None:
        if t.temettu_verim > 4:
            temettu_skoru += 2
        elif t.temettu_verim > 2:
            temettu_skoru += 1
    if t.fk is not None and 0 < t.fk < 12:
        temettu_skoru += 1   # düşük F/K çoğu zaman olgun/temettü şirketi

    if buyume_skoru > temettu_skoru:
        tip = "📈 BÜYÜME HİSSESİ eğilimli"
        aciklama = ("Kâr/geliri hızlı artıyor, kazancını yeniden yatırıma yönlendiriyor. "
                    "Avantaj: yüksek sermaye kazancı potansiyeli. Risk: pahalı çarpanlar, "
                    "büyüme yavaşlarsa sert düşüş.")
    elif temettu_skoru > buyume_skoru:
        tip = "💵 TEMETTÜ HİSSESİ eğilimli"
        aciklama = ("Olgun şirket, kârının bir kısmını temettü olarak dağıtıyor. "
                    "Avantaj: düzenli nakit akışı, daha düşük oynaklık. Risk: sınırlı "
                    "büyüme, faiz yükselince cazibe azalır.")
    else:
        tip = "⚖️ KARMA / NÖTR"
        aciklama = "Hem büyüme hem temettü özellikleri dengeli ya da veri yetersiz."

    return "\n".join([
        f"🔀 {kod} — BÜYÜME mi TEMETTÜ mü?",
        f"Sektör: {t.sektor}",
        "",
        f"Gelir büyümesi: {('%'+format(t.gelir_buyume,'.0f')) if t.gelir_buyume is not None else 'veri yok'}",
        f"Temettü verimi: {('%'+format(t.temettu_verim,'.1f')) if t.temettu_verim is not None else 'veri yok'}",
        f"F/K: {format(t.fk,'.1f') if t.fk is not None else 'veri yok'}",
        "",
        f"Sonuç: {tip}",
        aciklama,
        "",
        ENFLASYON_NOTU,
        "",
        "⚠️ Genel sınıflandırmadır, yatırım tavsiyesi değildir.",
    ])
