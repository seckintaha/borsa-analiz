"""
Kalibrasyon (Aşama 8) — sistemin kendini denetlemesi.

İlke (yol haritası): hedef "hep haklı olmak" değil, isabetini dürüstçe ölçmek.
Her tahmin (yön + ufuk) kaydedilir, ufuk dolunca gerçekle karşılaştırılır,
sinyal tipine göre isabet oranı çıkar ve **yazı-tura (0.5) ile kıyaslanır.**

Saf hesap mantığı; canlı veri gerektirmez.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Tahmin:
    symbol: str
    tarih: str
    yon: str                 # "pozitif" / "negatif"
    sinyal_tipi: str         # orn. "RSI_dusuk", "MACD_kesisim"
    ufuk_gun: int
    gerceklesen_pct: float | None = None   # ufuk dolunca doldurulur
    db_id: int | None = None               # SQLite satir id (None = henuz kaydedilmedi)


def gercek_ekle(t: Tahmin, gerceklesen_pct: float) -> Tahmin:
    t.gerceklesen_pct = gerceklesen_pct
    return t


def _isabetli(t: Tahmin) -> bool | None:
    if t.gerceklesen_pct is None:
        return None
    if t.yon == "pozitif":
        return t.gerceklesen_pct > 0
    if t.yon == "negatif":
        return t.gerceklesen_pct < 0
    return None


@dataclass
class KalibrasyonSonuc:
    sinyal_tipi: str
    n: int
    isabet_orani: float | None
    yazitura_farki: float | None    # isabet - 0.5 (pozitifse yazi-turadan iyi)
    guvenilir: bool
    not_: str = ""


def kalibre_et(tahminler: list[Tahmin], min_ornek: int = 20) -> list[KalibrasyonSonuc]:
    """Sinyal tipine gore isabet oranlarini hesaplar."""
    gruplar: dict[str, list[bool]] = {}
    for t in tahminler:
        r = _isabetli(t)
        if r is None:
            continue
        gruplar.setdefault(t.sinyal_tipi, []).append(r)

    out = []
    for tip, sonuclar in sorted(gruplar.items()):
        n = len(sonuclar)
        if n == 0:
            continue
        isabet = sum(sonuclar) / n
        out.append(KalibrasyonSonuc(
            sinyal_tipi=tip, n=n,
            isabet_orani=round(isabet, 3),
            yazitura_farki=round(isabet - 0.5, 3),
            guvenilir=(n >= min_ornek),
            not_="" if n >= min_ornek else f"az örnek (n={n}); henüz güvenilmez",
        ))
    return out


def genel_ozet(sonuclar: list[KalibrasyonSonuc]) -> str:
    if not sonuclar:
        return "Henüz değerlendirilmiş tahmin yok."
    satirlar = []
    for s in sonuclar:
        iyi = "yazı-turadan iyi" if (s.yazitura_farki or 0) > 0 else "yazı-turadan kötü/eşit"
        ek = f" ({s.not_})" if s.not_ else ""
        satirlar.append(f"{s.sinyal_tipi}: %{s.isabet_orani*100:.0f} isabet, {iyi}, n={s.n}{ek}")
    return "\n".join(satirlar)
