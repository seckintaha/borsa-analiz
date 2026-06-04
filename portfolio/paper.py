"""
Paper portföy (Aşama 2) — sanal alım-satım, gerçek para olmadan.

İlkeler (yol haritası):
- Her alım fiyat + tarih + gerekçeyle kaydedilir.
- İşlem maliyetleri (komisyon + kayma) hesaba katılır; yoksa portföy gerçeğinden
  iyi görünür.
- İzleme/tutma süresi sabit değil, ayarlanabilir parametredir; bir pozisyon birden
  çok ufukta (kısa/orta/uzun) aynı anda ölçülebilir.

Bu modül saf hesap mantığıdır; canlı veri gerektirmez (fiyatları çağıran verir).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd


@dataclass
class Pozisyon:
    symbol: str
    adet: float
    alis_fiyat: float          # maliyet dahil efektif alis
    alis_tarih: str
    gerekce: str = ""


@dataclass
class Islem:
    symbol: str
    yon: str                   # "AL" / "SAT"
    tarih: str
    fiyat: float               # maliyet dahil efektif fiyat
    adet: float
    tutar: float
    gerekce: str = ""


class PaperPortfolio:
    def __init__(self, baslangic_sermaye: float, costs: dict | None = None):
        self.baslangic = float(baslangic_sermaye)
        self.nakit = float(baslangic_sermaye)
        self.pozisyonlar: dict[str, Pozisyon] = {}
        self.islemler: list[Islem] = []
        self.costs = costs or {"komisyon_pct": 0.0, "kayma_pct": 0.0}

    # --- maliyet dahil efektif fiyat ---
    def _efektif_alis(self, fiyat: float) -> float:
        return fiyat * (1 + self.costs["komisyon_pct"] + self.costs["kayma_pct"])

    def _efektif_satis(self, fiyat: float) -> float:
        return fiyat * (1 - self.costs["komisyon_pct"] - self.costs["kayma_pct"])

    # --- alim ---
    def al(self, symbol, fiyat, tarih, tutar=None, adet=None, gerekce=""):
        symbol = symbol.upper()
        ef = self._efektif_alis(fiyat)
        if adet is None:
            if tutar is None:
                raise ValueError("tutar veya adet verilmeli")
            adet = tutar / ef
        maliyet = adet * ef
        if maliyet > self.nakit + 1e-9:
            raise ValueError(f"yetersiz nakit: gereken {maliyet:.2f}, mevcut {self.nakit:.2f}")
        self.nakit -= maliyet
        if symbol in self.pozisyonlar:  # ortalama maliyet
            p = self.pozisyonlar[symbol]
            toplam_adet = p.adet + adet
            p.alis_fiyat = (p.alis_fiyat * p.adet + ef * adet) / toplam_adet
            p.adet = toplam_adet
        else:
            self.pozisyonlar[symbol] = Pozisyon(symbol, adet, ef, tarih, gerekce)
        self.islemler.append(Islem(symbol, "AL", tarih, ef, adet, maliyet, gerekce))
        return adet

    # --- satim ---
    def sat(self, symbol, fiyat, tarih, adet=None, gerekce=""):
        symbol = symbol.upper()
        if symbol not in self.pozisyonlar:
            raise ValueError(f"{symbol} pozisyonu yok")
        p = self.pozisyonlar[symbol]
        adet = p.adet if adet is None else min(adet, p.adet)
        ef = self._efektif_satis(fiyat)
        gelir = adet * ef
        self.nakit += gelir
        p.adet -= adet
        if p.adet <= 1e-9:
            del self.pozisyonlar[symbol]
        self.islemler.append(Islem(symbol, "SAT", tarih, ef, adet, gelir, gerekce))
        return gelir

    # --- degerleme ---
    def deger(self, fiyatlar: dict[str, float]) -> float:
        """Nakit + acik pozisyonlarin guncel degeri. fiyatlar: {symbol: fiyat}."""
        toplam = self.nakit
        for sym, p in self.pozisyonlar.items():
            f = fiyatlar.get(sym)
            if f is not None:
                toplam += p.adet * f
        return toplam

    def getiri_pct(self, fiyatlar: dict[str, float]) -> float:
        return (self.deger(fiyatlar) - self.baslangic) / self.baslangic * 100

    def ozet(self, fiyatlar: dict[str, float]) -> dict:
        return {
            "baslangic": round(self.baslangic, 2),
            "nakit": round(self.nakit, 2),
            "guncel_deger": round(self.deger(fiyatlar), 2),
            "getiri_pct": round(self.getiri_pct(fiyatlar), 2),
            "acik_pozisyon": len(self.pozisyonlar),
            "islem_sayisi": len(self.islemler),
        }


def cok_ufuklu_getiri(fiyat_serisi: pd.Series, giris_tarih, horizons: dict) -> dict:
    """
    Bir girisin farkli ufuklardaki getirisini olcer (yol haritasi: ufuk parametriktir).
    fiyat_serisi: tarih indeksli Close serisi. horizons: {"kisa":14, ...} (gun).
    Doner: {"kisa": {"getiri_pct":..., "tarih":...}, ...}
    """
    fiyat_serisi = fiyat_serisi.sort_index()
    giris_tarih = pd.to_datetime(giris_tarih)
    giris_idx = fiyat_serisi.index.get_indexer([giris_tarih], method="nearest")[0]
    giris_fiyat = float(fiyat_serisi.iloc[giris_idx])
    out = {}
    for ad, gun in horizons.items():
        hedef_idx = giris_idx + gun
        if hedef_idx < len(fiyat_serisi):
            hedef_fiyat = float(fiyat_serisi.iloc[hedef_idx])
            out[ad] = {
                "getiri_pct": round((hedef_fiyat - giris_fiyat) / giris_fiyat * 100, 2),
                "tarih": str(fiyat_serisi.index[hedef_idx].date()),
            }
        else:
            out[ad] = {"getiri_pct": None, "tarih": None, "not": "yeterli ileri veri yok"}
    return out
