"""
Öneri / Tarama Sıralaması (Aşama 11).

Kullanıcı isteği: "şunu al, bunu al" diyen, tüm verileri/haberleri/analizleri/
grafikleri okuyup sıralı somut öneri veren bir katman.

Bu modül bunu **şeffaf** yapar:
- Deterministik skor (0–100): sinyal puanı + piyasa rejimi + dikkat bayrakları.
- Her adaya bir aksiyon etiketi: "Güçlü AL adayı / AL adayı / Nötr / İzle /
  Zayıf / Kaçın".
- Her öneri **gerekçe + ayı senaryosu + güven düzeyiyle** gelir; gerekçesiz "al"
  yoktur.
- Üstüne, tüm bağlamı okuyup sıralı bir öneri yazan opsiyonel AI yorum katmanı.

ÖNEMLİ DÜRÜSTLÜK NOTU: Skorlar teknik göstergelerin matematiksel çıktısıdır,
geleceği bilmez ve sık yanılır. Bu lisanslı yatırım danışmanlığı DEĞİLDİR.
Karar kullanıcıya aittir.
"""

from __future__ import annotations
from dataclasses import dataclass, field

import pandas as pd

from data.fetcher import fetch_many
from analysis.indicators import add_indicators
from analysis.signals import evaluate
from analysis import llm


@dataclass
class OneriSatir:
    symbol: str
    skor: int                  # 0–100
    aksiyon: str               # "Güçlü AL adayı" / "AL adayı" / "Nötr / İzle" / "Zayıf / Kaçın"
    son_fiyat: float | None
    degisim_pct: float | None  # periyot getirisi
    gerekceler: list = field(default_factory=list)
    ayi_senaryosu: list = field(default_factory=list)
    bayraklar: list = field(default_factory=list)
    guven: str = "düşük"       # "yüksek" / "orta" / "düşük"
    kaynak: str = ""
    zaman: str = ""
    not_: str = ""             # veri yoksa açıklama


def _aksiyon(skor: int, cfg: dict) -> str:
    if skor >= cfg["esik_guclu_al"]:
        return "Güçlü AL adayı"
    if skor >= cfg["esik_al"]:
        return "AL adayı"
    if skor >= cfg["esik_izle"]:
        return "Nötr / İzle"
    return "Zayıf / Kaçın"


def _guven(satir_sayisi: int, bayrak_sayisi: int) -> str:
    # Önce yalnızca veri uzunluğuna göre taban güven
    if satir_sayisi >= 200:
        g = "yüksek"
    elif satir_sayisi >= 60:
        g = "orta"
    else:
        g = "düşük"
    # Dikkat bayrağı (manipülasyon/ince hacim) varsa bir kademe düşür
    if bayrak_sayisi > 0:
        g = {"yüksek": "orta", "orta": "düşük", "düşük": "düşük"}[g]
    return g


def skorla(df: pd.DataFrame, cfg: dict, thin_volume: float,
           rejim: str = "") -> tuple[int, dict]:
    """
    Tek hisse için 0–100 skor üretir (saf, ağ gerektirmez).
    Dönüş: (skor, {gerekceler, ayi, bayraklar}).
    Skor şeffaftır: 50 taban + sinyal puanı*ağırlık + rejim ± bayrak cezası.
    """
    res = evaluate(df, thin_volume=thin_volume)
    skor = 50 + res.puan * cfg["sinyal_agirlik"]

    gerekceler = list(res.notlar)
    if rejim == "Boğa":
        skor += cfg["rejim_boga"]
        gerekceler.append(f"piyasa rejimi Boğa (+{cfg['rejim_boga']})")
    elif rejim == "Ayı":
        skor += cfg["rejim_ayi"]
        gerekceler.append(f"piyasa rejimi Ayı ({cfg['rejim_ayi']})")
    elif rejim:
        gerekceler.append(f"piyasa rejimi {rejim} (nötr etki)")

    skor += cfg["bayrak_cezasi"] * len(res.bayraklar)

    skor = int(max(0, min(100, round(skor))))
    return skor, {"gerekceler": gerekceler,
                  "ayi": res.ayi_senaryosu,
                  "bayraklar": res.bayraklar}


def oneri_tara(symbols, cfg: dict, thin_volume: float, rejim: str = "",
               period: str = "1mo") -> list[OneriSatir]:
    """
    Sembol listesini tarar, skorlar ve **skora göre azalan** sıralar.
    En üstte en yüksek skorlu "AL adayları" olur.
    """
    sonuc: list[OneriSatir] = []
    cekilen = fetch_many(symbols, period=period, interval="1d")

    for sym, fr in cekilen.items():
        if not fr.ok or fr.data is None or len(fr.data) < 20:
            sonuc.append(OneriSatir(
                sym, 0, "Veri yok", None, None,
                not_=fr.note or "yetersiz veri",
                kaynak=fr.source, zaman=fr.fetched_at))
            continue

        df = add_indicators(fr.data)
        son_fiyat = float(df["Close"].iloc[-1])
        ilk_fiyat = float(df["Close"].iloc[0])
        degisim = (son_fiyat - ilk_fiyat) / ilk_fiyat * 100 if ilk_fiyat else 0.0

        skor, ek = skorla(df, cfg, thin_volume, rejim=rejim)
        sonuc.append(OneriSatir(
            symbol=sym, skor=skor, aksiyon=_aksiyon(skor, cfg),
            son_fiyat=round(son_fiyat, 2), degisim_pct=round(degisim, 2),
            gerekceler=ek["gerekceler"], ayi_senaryosu=ek["ayi"],
            bayraklar=ek["bayraklar"],
            guven=_guven(len(df), len(ek["bayraklar"])),
            kaynak=fr.source, zaman=fr.fetched_at,
        ))

    # Önce veri olanlar, skora göre azalan
    sonuc.sort(key=lambda r: (r.aksiyon == "Veri yok", -r.skor))
    return sonuc


# ── AI yorum katmanı (tüm bağlamı okuyup sıralı öneri yazar) ───────────────────

ONERI_SISTEM = """Sen bir teknik tarama asistanısın. Sana, bir tarama motorunun \
şeffaf skorlarıyla sıraladığı hisse adaylarını ve piyasa rejimini veriyorum. \
Görevin, bu adayları kullanıcı için net ve sıralı biçimde değerlendirmek.

KURALLAR:
1. Sadece sana verilen skor/gerekçe/rejim/haber verisini kullan. Yeni rakam ya \
da haber UYDURMA.
2. Öne çıkan adayları sırala ve her biri için NEDEN öne çıktığını kısaca söyle.
3. HER aday için bir de RİSK / ayı senaryosu söyle — gerekçesiz "al" yazma.
4. Skoru düşük / bayraklı (manipülasyon, ince hacim) olanları "dikkat/kaçın" \
diye ayır.
5. Güven düzeyini (yüksek/orta/düşük) dikkate al; düşük güvenli adayda bunu belirt.
6. Türkçe, sade, abartısız yaz.
7. Sonunda tek satır: "Bu teknik bir taramadır, lisanslı yatırım danışmanlığı \
değildir; karar size aittir ve göstergeler sık yanılır."
"""


def _yorum_metni(satirlar: list[OneriSatir], rejim_ozeti: str, en_iyi_n: int) -> str:
    p = [f"Piyasa rejimi: {rejim_ozeti or 'bilinmiyor'}", "", "Adaylar (skora göre sıralı):"]
    for r in satirlar[:en_iyi_n]:
        if r.aksiyon == "Veri yok":
            continue
        satir = (f"- {r.symbol}: skor {r.skor}/100, {r.aksiyon}, "
                 f"güven {r.guven}, periyot getirisi {r.degisim_pct:+.1f}%")
        if r.gerekceler:
            satir += " | gerekçe: " + "; ".join(r.gerekceler[:4])
        if r.bayraklar:
            satir += " | DİKKAT: " + "; ".join(r.bayraklar)
        p.append(satir)
    return ("Aşağıdaki taranmış adayları değerlendir. Veri uydurma; her adayın "
            "riskini de söyle.\n\n" + "\n".join(p))


def ai_yorum(satirlar: list[OneriSatir], rejim_ozeti: str = "",
             en_iyi_n: int = 6, model: str = "claude-opus-4-8",
             max_tokens: int = 1500, api_key: str | None = None):
    """
    Skorlanmış adayları Claude'a verip sıralı, gerekçeli bir öneri yazısı alır.
    Anahtar/kütüphane yoksa uydurmaz; llm.LLMSentez(ok=False) döner.
    """
    metin = _yorum_metni(satirlar, rejim_ozeti, en_iyi_n)
    return llm.cevapla(ONERI_SISTEM, metin, model=model,
                       max_tokens=max_tokens, api_key=api_key)


# ── Yerel öneri yazarı (API ANAHTARI GEREKMEZ) ────────────────────────────────

def yerel_yorum(satirlar: list[OneriSatir], rejim_ozeti: str = "",
                en_iyi_n: int = 6) -> str:
    """
    Skorlanmış adaylardan, hiçbir API gerektirmeden sıralı + gerekçeli bir
    Türkçe öneri yazısı üretir (Markdown). Her aday gerekçe + ayı senaryosu +
    güven düzeyiyle gelir; sonunda dürüstlük notu vardır.
    """
    verili = [r for r in satirlar if r.aksiyon != "Veri yok"]
    guclu = [r for r in verili if r.aksiyon == "Güçlü AL adayı"]
    al = [r for r in verili if r.aksiyon == "AL adayı"]
    izle = [r for r in verili if r.aksiyon == "Nötr / İzle"]
    kacin = [r for r in verili if r.aksiyon == "Zayıf / Kaçın"]
    adaylar = (guclu + al)[:en_iyi_n]

    p = []
    if rejim_ozeti:
        p.append(f"**Piyasa durumu:** {rejim_ozeti}")
        p.append("")

    if adaylar:
        p.append("### 🟢 Öne çıkan adaylar (skora göre)")
        for i, r in enumerate(adaylar, 1):
            satir = f"**{i}. {r.symbol}** — {r.aksiyon}, skor **{r.skor}/100**, güven: {r.guven}"
            p.append(satir)
            if r.gerekceler:
                p.append(f"   - **Neden:** {'; '.join(r.gerekceler[:4])}")
            if r.ayi_senaryosu:
                p.append(f"   - **Ama dikkat:** {'; '.join(r.ayi_senaryosu)}")
            if r.bayraklar:
                p.append(f"   - ⚠️ **Bayrak:** {'; '.join(r.bayraklar)}")
            p.append("")
    else:
        p.append("### 🟡 Şu an güçlü bir AL adayı yok")
        p.append("Hiçbir hisse 'AL adayı' eşiğini geçmedi — piyasa zayıf, "
                 "yatay ya da veri yetersiz olabilir. Bu da bir bilgidir; "
                 "zorlama gerek yok.")
        p.append("")

    if izle:
        adlar = ", ".join(f"{r.symbol} ({r.skor})" for r in izle[:8])
        p.append(f"**🟡 İzleme listesi (nötr):** {adlar}")
        p.append("")

    if kacin:
        adlar = ", ".join(f"{r.symbol} ({r.skor})" for r in kacin[:8])
        p.append(f"**🔴 Şimdilik uzak durulacaklar:** {adlar}")
        p.append("")

    # Güven uyarısı: tüm adaylar düşük güvenliyse (ör. 1 aylık kısa pencere)
    if adaylar and all(r.guven == "düşük" for r in adaylar):
        p.append("> ⏳ **Not:** Tüm adayların güveni *düşük* — seçtiğin pencere "
                 "kısa olabilir. Daha güvenilir sıralama için 6 ay / 1 yıl dene.")
        p.append("")

    p.append("---")
    p.append("_Bu teknik bir taramadır; skorlar göstergelerin matematiksel "
             "çıktısıdır ve **sık yanılır**. Lisanslı yatırım danışmanlığı "
             "değildir — karar senindir._")
    return "\n".join(p)
