"""
Küresel Piyasa & Makro Nabzı — BIST'i yukarıdan-aşağı (top-down) bağlama oturtur.

Junior→senior farkı: bir hisseyi sadece kendi verisiyle değil, DÜNYA bağlamında
okumak. BIST; global risk iştahı, USD/TRY, ABD faizi, petrol ve yabancı akışına
son derece duyarlıdır.

İLKE: Piyasa fiyatı haberi zaten fiyatlar. VIX, USD/TRY, S&P, Brent — haberi RSS
başlığından daha hızlı ve dürüst kodlar. Bu yüzden "haberden haberdar olmak"ın
en sağlam yolu cross-asset tape'i (gerçek fiyatları) okumaktır. Kaynak: yfinance.
Veri yoksa "veri yok" der, uydurmaz. Kural-temelli, deterministik yorum.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# sembol: (ad, kategori, "seviye"mi yoksa "değişim"mi önemli)
_VARLIKLAR = {
    "^GSPC":    ("S&P 500 (ABD)",          "abd",      "deg"),
    "^IXIC":    ("Nasdaq (ABD tekno)",     "abd",      "deg"),
    "^VIX":     ("VIX (korku endeksi)",    "risk",     "seviye"),
    "^TNX":     ("ABD 10Y faiz",           "faiz",     "seviye"),
    "DX-Y.NYB": ("Dolar Endeksi (DXY)",    "kur",      "deg"),
    "TRY=X":    ("USD/TRY",                "kur",      "deg"),
    "BZ=F":     ("Brent petrol",           "emtia",    "deg"),
    "GC=F":     ("Altın",                  "emtia",    "deg"),
    "TUR":      ("Türkiye ETF (yabancı gözü)", "turkiye", "deg"),
    "EEM":      ("Gelişen Piyasalar ETF",  "em",       "deg"),
}


@dataclass
class VarlikVeri:
    sembol: str
    ad: str
    kategori: str
    onem: str
    son: Optional[float]
    degisim_pct: Optional[float]


@dataclass
class KureselNabiz:
    varliklar: list          # list[VarlikVeri]
    risk_skoru: int
    risk_etiket: str         # "Risk-ON" / "Nötr" / "Risk-OFF"
    bist_etkileri: list = field(default_factory=list)
    ok: bool = True


def _cek(sembol: str) -> Optional[dict]:
    """Bir sembol için son kapanış + günlük % (yfinance). Veri yoksa None."""
    try:
        import yfinance as yf
        df = yf.download(sembol, period="7d", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "get_level_values"):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        if len(close) < 2:
            return None
        son = float(close.iloc[-1])
        onceki = float(close.iloc[-2])
        deg = (son - onceki) / onceki * 100 if onceki else None
        return {"son": son, "deg": deg}
    except Exception:
        return None


def kuresel_nabiz() -> KureselNabiz:
    """Küresel varlıkları çeker, risk-on/off okur ve BIST etkilerini yorumlar."""
    varliklar: list[VarlikVeri] = []
    d: dict[str, dict] = {}
    for sem, (ad, kat, onem) in _VARLIKLAR.items():
        v = _cek(sem)
        d[sem] = v
        varliklar.append(VarlikVeri(
            sembol=sem, ad=ad, kategori=kat, onem=onem,
            son=(v["son"] if v else None),
            degisim_pct=(v["deg"] if v else None),
        ))

    # ── Risk-on / risk-off skoru (mevcut verilerden) ──
    risk = 0
    def deg(sem):
        return d[sem]["deg"] if d.get(sem) else None
    def son(sem):
        return d[sem]["son"] if d.get(sem) else None

    if deg("^GSPC") is not None:
        risk += 1 if deg("^GSPC") > 0 else -1
    vix = son("^VIX")
    if vix is not None:
        if vix < 16:   risk += 2
        elif vix < 20: risk += 1
        elif vix > 28: risk -= 2
        elif vix > 24: risk -= 1
    if deg("^VIX") is not None and deg("^VIX") > 6:
        risk -= 1
    if deg("TUR") is not None:
        risk += 1 if deg("TUR") > 0 else -1
    if deg("EEM") is not None:
        risk += 1 if deg("EEM") > 0 else -1
    if deg("TRY=X") is not None:      # USD/TRY ↑ = lira zayıf = BIST için risk-off
        if deg("TRY=X") > 0.5:  risk -= 1
        elif deg("TRY=X") < -0.3: risk += 1
    if deg("^TNX") is not None and deg("^TNX") > 3:
        risk -= 1

    if risk >= 2:
        etiket = "Risk-ON (açık) 🟢"
    elif risk <= -2:
        etiket = "Risk-OFF (temkinli) 🔴"
    else:
        etiket = "Nötr / karışık 🟡"

    # ── BIST etkileri (kural-temelli, gerçek değerlere dayalı) ──
    etkiler = []
    if vix is not None:
        if vix > 25:
            etkiler.append(f"⚠️ VIX {vix:.0f} yüksek — global satış baskısı BIST'e de yansıyabilir.")
        elif vix < 16:
            etkiler.append(f"✅ VIX {vix:.0f} düşük — risk iştahı açık, BIST için destekleyici zemin.")
    tr = deg("TRY=X")
    if tr is not None:
        if tr > 0.5:
            etkiler.append(f"⚠️ USD/TRY %{tr:+.1f} — lira zayıflıyor; yabancı çıkışı riski, ama ihracatçılar (THYAO, EREGL, TUPRS) görece korunur.")
        elif tr < -0.3:
            etkiler.append(f"✅ USD/TRY %{tr:+.1f} — lira güçleniyor; yabancı girişine olumlu zemin.")
    br = deg("BZ=F"); brs = son("BZ=F")
    if br is not None and abs(br) > 2:
        if br > 0:
            etkiler.append(f"⚠️ Brent %{br:+.1f} (≈{brs:.0f}$) — Türkiye enerji ithalatçısı; cari açık baskısı (TUPRS/PETKM hariç olumsuz).")
        else:
            etkiler.append(f"✅ Brent %{br:+.1f} — enerji maliyeti düşüyor, cari denge lehine.")
    tnx = deg("^TNX"); tnxs = son("^TNX")
    if tnx is not None and tnx > 2:
        etkiler.append(f"⚠️ ABD 10Y faiz artıyor (≈%{tnxs:.1f}) — gelişen piyasalardan sermaye çıkış eğilimi, BIST'e baskı.")
    tur = deg("TUR")
    if tur is not None:
        yon = "olumlu" if tur > 0 else "olumsuz"
        etkiler.append(f"🌍 Türkiye ETF (yabancı gözü) %{tur:+.1f} — yabancının Türkiye iştahı bugün {yon}.")
    if not etkiler:
        etkiler.append("Belirgin küresel baskı/destek sinyali yok; BIST'i içsel dinamikler yönlendirir.")

    return KureselNabiz(varliklar=varliklar, risk_skoru=risk,
                        risk_etiket=etiket, bist_etkileri=etkiler,
                        ok=any(v.son is not None for v in varliklar))


def kuresel_metni(kn: Optional[KureselNabiz] = None) -> str:
    """Küresel nabzı Telegram/panel metnine çevirir."""
    if kn is None:
        kn = kuresel_nabiz()
    if not kn.ok:
        return "🌍 KÜRESEL PİYASA\n\nVeri alınamadı (yfinance geçici erişim sorunu)."

    sat = [f"🌍 KÜRESEL PİYASA & MAKRO NABZI",
           f"Genel risk iştahı: {kn.risk_etiket}  (skor {kn.risk_skoru:+d})", ""]

    # Kategorilere göre grupla
    gruplar = [("📈 Global Borsalar", "abd"), ("😨 Risk", "risk"),
               ("💱 Kur", "kur"), ("🛢️ Emtia", "emtia"),
               ("🇹🇷 Türkiye/EM", None)]
    for baslik, kat in gruplar:
        if kat is None:
            uyeler = [v for v in kn.varliklar if v.kategori in ("turkiye", "em")]
        else:
            uyeler = [v for v in kn.varliklar if v.kategori == kat]
        satir = []
        for v in uyeler:
            if v.son is None:
                satir.append(f"{v.ad}: veri yok")
            elif v.onem == "seviye":
                dg = f" (%{v.degisim_pct:+.1f})" if v.degisim_pct is not None else ""
                satir.append(f"{v.ad}: {v.son:.1f}{dg}")
            else:
                dg = f"%{v.degisim_pct:+.1f}" if v.degisim_pct is not None else "—"
                satir.append(f"{v.ad}: {dg}")
        if satir:
            sat.append(f"{baslik}: " + " · ".join(satir))

    sat += ["", "🧭 BIST'e etkisi:"]
    for e in kn.bist_etkileri:
        sat.append(f"   {e}")

    sat += ["", "⚠️ Piyasa fiyatlarına dayalı kural-temelli okuma; kesin değildir, "
            "yatırım tavsiyesi değildir."]
    return "\n".join(sat)
