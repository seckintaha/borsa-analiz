"""
Otomasyon komut satırı girişi (Aşama 10).

Kullanım (proje kökünde):
    python -m automation.run

İzleme listesini tarar, piyasa rejimini okur ve `raporlar/` altına tarihli bir
Markdown rapor yazar.

Zamanlama (her gün otomatik çalışsın istiyorsanız) — bu işletim sistemine özgüdür:

  macOS / Linux (cron), her gün 18:30:
    30 18 * * 1-5  cd /yol/borsa-analiz && /yol/.venv/bin/python -m automation.run

  macOS (launchd) veya Windows (Görev Zamanlayıcı) ile de aynı komut kurulabilir.

NOT: Çıktı yatırım tavsiyesi değildir.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data.storage import load_watchlist
from automation.scheduler import calistir


def main() -> None:
    watchlist = load_watchlist(config.DB_PATH) or list(config.WATCHLIST)
    print(f"Tarama başlıyor: {len(watchlist)} hisse...")
    ozet = calistir(
        db_path=config.DB_PATH,
        watchlist=watchlist,
        screen_cfg=config.SCREEN,
        macro_cfg=config.MACRO,
        rapor_klasoru=config.OTOMASYON["rapor_klasoru"],
    )
    print(f"\nBitti. {ozet['taranan']} hisse tarandı, "
          f"{ozet['one_cikan']} öne çıkan.")
    print(f"Rejim : {ozet['rejim']}")
    print(f"Rapor : {ozet['rapor_yolu']}")


if __name__ == "__main__":
    main()
