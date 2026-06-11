"""
Tüm BIST evrenini tarayan ana motor.

TradingView scanner ile 500 hisseyi TEK istekte çeker (fiyat, hacim, RSI,
MACD, EMA). Ayrıntılı yfinance analizi için yalnızca üst N aday seçilir.
Bu yaklaşım hem hızlı hem de doğru sonuç verir.

Mimari:
  1. tv_tara()     → 500 hisse için temel göstergeler (tek HTTP)
  2. sinyal_filtre → Teknik kriterlere göre sırala/filtrele
  3. [opsiyonel] yfinance ile üst N adaya tam indikatör (ADX, ek doğrulama)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from data.tv_scanner import tv_tara, TVSatir, sinyal_puan


@dataclass
class BistSatir:
    sembol: str
    ad: str
    fiyat: Optional[float]
    degisim_pct: Optional[float]
    hacim: Optional[float]
    hacim_kat: Optional[float]     # son hacim / 10g ort
    rsi: Optional[float]
    macd_sinyal: str               # "Alış" / "Satış" / "Nötr"
    ema_durumu: str                # "Trend Yukarı" / "Trend Aşağı" / "Karışık"
    sinyal_skoru: int              # -100..+100 arası ham skor
    aksiyon: str                   # "Güçlü AL" / "AL" / "Nötr" / "Kaçın"
    gerekceler: list = field(default_factory=list)
    uyarilar: list = field(default_factory=list)
    perf_hafta: Optional[float] = None
    perf_ay: Optional[float] = None


def _aksiyon_belirle(skor: int) -> str:
    if skor >= 35:
        return "Güçlü AL adayı"
    if skor >= 20:
        return "AL adayı"
    if skor >= 5:
        return "Nötr / İzle"
    return "Zayıf / Kaçın"


def _macd_etiketi(s: TVSatir) -> str:
    if s.macd is None or s.macd_sinyal is None:
        return "Veri yok"
    return "Alış" if s.macd > s.macd_sinyal else "Satış"


def _ema_etiketi(s: TVSatir) -> str:
    if s.ema20 and s.ema50 and s.ema200:
        if s.ema20 > s.ema50 > s.ema200:
            return "Trend Yukarı"
        if s.ema20 < s.ema50 < s.ema200:
            return "Trend Aşağı"
        return "Karışık"
    if s.ema20 and s.ema50:
        return "Yukarı" if s.ema20 > s.ema50 else "Aşağı"
    return "Veri yok"


def _gerekceler_cikart(s: TVSatir, skor: int) -> list[str]:
    g: list[str] = []
    if s.rsi is not None:
        if s.rsi < 30:
            g.append(f"RSI aşırı satım ({s.rsi:.0f})")
        elif s.rsi > 70:
            g.append(f"RSI aşırı alım ({s.rsi:.0f})")
    if s.macd is not None and s.macd_sinyal is not None:
        if s.macd > s.macd_sinyal:
            g.append("MACD alış üstünde")
        else:
            g.append("MACD satış altında")
    if s.ema20 and s.ema50 and s.ema200:
        if s.ema20 > s.ema50 > s.ema200:
            g.append("EMA düzeni boğa (20>50>200)")
    if s.degisim_pct and abs(s.degisim_pct) >= 3:
        yon = "yükseldi" if s.degisim_pct > 0 else "düştü"
        g.append(f"Bugün {yon} %{s.degisim_pct:+.1f}")
    if s.hacim and s.ort_hacim_10g and s.ort_hacim_10g > 0:
        kat = s.hacim / s.ort_hacim_10g
        if kat >= 2:
            g.append(f"Anormal hacim ({kat:.1f}× ortalama)")
    if s.fiyat and s.bb_alt and s.bb_ust:
        band = s.bb_ust - s.bb_alt
        if band > 0:
            poz = (s.fiyat - s.bb_alt) / band
            if poz < 0.15:
                g.append("Bollinger alt bandına yakın")
            elif poz > 0.9:
                g.append("Bollinger üst bandına dayalı")
    return g


def _uyarilar_cikart(s: TVSatir) -> list[str]:
    u: list[str] = []
    if s.hacim and s.ort_hacim_10g and s.ort_hacim_10g < 500_000:
        u.append("Düşük hacim (likit olmayabilir)")
    if s.fiyat and s.fiyat < 1.0:
        u.append("Düşük fiyatlı hisse (dikkatli olun)")
    return u


def bist_tara(
    screen_cfg: dict | None = None,
    limit: int = 1000,
) -> tuple[bool, str, list[BistSatir]]:
    """
    Tüm BIST'i TradingView scanner ile tarar.

    Dönüş: (basarili, hata_mesaji, siralanmis_satirlar)
    Skor yüksek → öne çıkan; skor düşük → kaçın.
    """
    ok, hata, tv_satirlar = tv_tara(limit=limit)
    if not ok:
        return False, hata, []

    sonuclar: list[BistSatir] = []
    for s in tv_satirlar:
        skor = sinyal_puan(s)
        hacim_kat = None
        if s.hacim and s.ort_hacim_10g and s.ort_hacim_10g > 0:
            hacim_kat = round(s.hacim / s.ort_hacim_10g, 1)

        sonuclar.append(BistSatir(
            sembol=s.sembol,
            ad=s.ad,
            fiyat=round(s.fiyat, 2) if s.fiyat else None,
            degisim_pct=round(s.degisim_pct, 2) if s.degisim_pct is not None else None,
            hacim=s.hacim,
            hacim_kat=hacim_kat,
            rsi=round(s.rsi, 1) if s.rsi else None,
            macd_sinyal=_macd_etiketi(s),
            ema_durumu=_ema_etiketi(s),
            sinyal_skoru=skor,
            aksiyon=_aksiyon_belirle(skor),
            gerekceler=_gerekceler_cikart(s, skor),
            uyarilar=_uyarilar_cikart(s),
            perf_hafta=round(s.perf_hafta, 1) if s.perf_hafta is not None else None,
            perf_ay=round(s.perf_ay, 1) if s.perf_ay is not None else None,
        ))

    # Skor yüksekten düşüğe sırala
    sonuclar.sort(key=lambda r: r.sinyal_skoru, reverse=True)
    return True, "", sonuclar


def ozet_istatistik(satirlar: list[BistSatir]) -> dict:
    """Tarama sonuçlarından özet istatistik üretir."""
    toplam = len(satirlar)
    if toplam == 0:
        return {"toplam": 0}

    degisimler = [r.degisim_pct for r in satirlar if r.degisim_pct is not None]
    n_yukselis = sum(1 for d in degisimler if d > 0)
    n_dusus = sum(1 for d in degisimler if d < 0)
    ort_degisim = sum(degisimler) / len(degisimler) if degisimler else None

    n_guclu_al = sum(1 for r in satirlar if r.aksiyon == "Güçlü AL adayı")
    n_al = sum(1 for r in satirlar if r.aksiyon == "AL adayı")
    n_izle = sum(1 for r in satirlar if r.aksiyon == "Nötr / İzle")
    n_kacin = sum(1 for r in satirlar if r.aksiyon == "Zayıf / Kaçın")

    rsi_degerler = [r.rsi for r in satirlar if r.rsi]
    ort_rsi = sum(rsi_degerler) / len(rsi_degerler) if rsi_degerler else None
    asiri_satim = sum(1 for r in rsi_degerler if r < 30)
    asiri_alim = sum(1 for r in rsi_degerler if r > 70)

    return {
        "toplam": toplam,
        "yukselis": n_yukselis,
        "dusus": n_dusus,
        "degismedi": toplam - n_yukselis - n_dusus,
        "ort_degisim_pct": round(ort_degisim, 2) if ort_degisim is not None else None,
        "guclu_al": n_guclu_al,
        "al_adayi": n_al,
        "izle": n_izle,
        "kacin": n_kacin,
        "ort_rsi": round(ort_rsi, 1) if ort_rsi else None,
        "asiri_satim_sayisi": asiri_satim,
        "asiri_alim_sayisi": asiri_alim,
    }
