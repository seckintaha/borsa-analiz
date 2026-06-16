"""
Telegram-öncelikli portföy özeti (panelden bağımsız).

portfolio_islemler tablosundan açık pozisyonları hesaplar. PaperPortfolio'nun
nakit kısıtı YOKTUR — kullanıcı Telegram'dan gerçek portföyünü "beyan ederken"
100.000 ₺ sanal kasaya takılmaz. Ağırlıklı ortalama maliyet kullanılır.

Bu modül saf hesap + DB okumadır; canlı fiyatı çağıran taraf verir.
"""

from __future__ import annotations
import sqlite3


def _islemler(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT symbol,yon,tarih,fiyat,adet,tutar,gerekce "
            "FROM portfolio_islemler ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def acik_pozisyonlar(db_path: str) -> dict[str, dict]:
    """
    {sembol: {"adet": x, "maliyet": ortalama_alis, "ilk_tarih": ...}} döndürür.
    Nakit kontrolü YOK — beyan edilen tüm alımlar kabul edilir.
    """
    pos: dict[str, dict] = {}
    for it in _islemler(db_path):
        sym = (it["symbol"] or "").upper()
        adet = float(it["adet"] or 0)
        fiyat = float(it["fiyat"] or 0)
        if adet <= 0:
            continue
        if it["yon"] == "AL":
            if sym in pos:
                p = pos[sym]
                yeni_adet = p["adet"] + adet
                p["maliyet"] = (p["maliyet"] * p["adet"] + fiyat * adet) / yeni_adet
                p["adet"] = yeni_adet
            else:
                pos[sym] = {"adet": adet, "maliyet": fiyat,
                            "ilk_tarih": it["tarih"]}
        elif it["yon"] == "SAT" and sym in pos:
            pos[sym]["adet"] -= adet
            if pos[sym]["adet"] <= 1e-6:
                del pos[sym]
    # Yuvarla
    for sym, p in pos.items():
        p["adet"] = round(p["adet"], 4)
        p["maliyet"] = round(p["maliyet"], 4)
    return pos


def net_adet(db_path: str, sembol: str) -> float:
    """Bir sembolün net açık adedini döndürür (satışta kontrol için)."""
    sembol = sembol.upper()
    return acik_pozisyonlar(db_path).get(sembol, {}).get("adet", 0.0)
