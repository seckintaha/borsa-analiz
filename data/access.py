"""
Veri erişim katmanı — canlı çekme + DB önbellek yedeği (Aşama 0 dayanıklılık).

İlke: önce canlı veri denenir, başarılıysa DB'ye yazılır. Canlı veri alınamazsa
(ağ yok, hız limiti, delisting) sessizce hata vermek yerine **DB önbelleğindeki
son bilinen veriyle** devam edilir ve bu durum açıkça (kaynak "cache (DB)",
bayat=True, uyarı) işaretlenir. Önbellekte de yoksa dürüstçe ok=False döner.

Bu katman tek-sembol akışlar (panel hisse detayı, rejim endeksi) içindir.
"""

from __future__ import annotations

from data.fetcher import fetch_history, FetchResult
from data.storage import save_prices, get_prices_fetchresult


def veri_getir(db_path: str, symbol: str, period: str = "1y",
               interval: str = "1d", db_yedek: bool = True,
               max_deneme: int = 3, bekleme_sn: float = 1.5,
               bayat_gun: int = 7, bosluk_gun: int = 10) -> FetchResult:
    """
    Canlı veriyi çeker; başarılıysa DB'ye yazıp döndürür.
    Başarısızsa (db_yedek=True ise) DB önbelleğinden son kaydı döndürür.
    """
    fr = fetch_history(symbol, period=period, interval=interval,
                       max_deneme=max_deneme, bekleme_sn=bekleme_sn,
                       bayat_gun=bayat_gun, bosluk_gun=bosluk_gun)
    if fr.ok:
        try:
            save_prices(db_path, fr)
        except Exception:
            pass  # yazma hatası veriyi göstermeyi engellemesin
        return fr

    if db_yedek:
        yedek = get_prices_fetchresult(db_path, symbol, bayat_gun=bayat_gun)
        if yedek.ok:
            # Orijinal canlı hatayı da uyarılara ekle (şeffaflık)
            yedek.uyarilar.insert(0, f"canlı çekme başarısız: {fr.note}")
            return yedek

    return fr  # ne canlı ne önbellek — orijinal hata mesajıyla
