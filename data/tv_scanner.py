"""
TradingView bulk tarayıcı — tüm BIST'i tek HTTP isteğiyle tarar.

500 hisseyi ayrı ayrı yfinance ile çekmek yerine TradingView scanner
kullanılır: fiyat, değişim %, hacim, RSI, MACD, EMA ve piyasa değeri
tek istekte gelir.

Kaynak: TradingView public scanner API (borsa.tradingview.com/turkey/scan).
Veri gerçek zamanlı/gecikmeli TradingView verisidir; kap.org.tr değildir.
Veri yoksa ya da API yanıt vermezse açıkça belirtilir, uydurulmaz.
"""

from __future__ import annotations
import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

_TV_SCAN_URL = "https://scanner.tradingview.com/turkey/scan"

_KOLONLAR = [
    "name",           # sembol (BIST:THYAO gibi)
    "description",    # şirket adı
    "close",          # son kapanış
    "change",         # günlük % değişim
    "volume",         # günlük hacim
    "average_volume_10d_calc",  # 10 günlük ort hacim
    "RSI",            # RSI(14)
    "MACD.macd",      # MACD çizgisi
    "MACD.signal",    # MACD sinyal çizgisi
    "EMA20",          # 20 günlük EMA
    "EMA50",          # 50 günlük EMA
    "EMA200",         # 200 günlük EMA
    "BB.upper",       # Bollinger Üst
    "BB.lower",       # Bollinger Alt
    "market_cap_basic",  # piyasa değeri (TL)
    "High.1M",        # 1 aylık en yüksek
    "Low.1M",         # 1 aylık en düşük
    "Perf.W",         # haftalık performans %
    "Perf.1M",        # aylık performans %
    "ATH",            # tüm zamanların en yükseği (bazı hisseler için)
]


@dataclass
class TVSatir:
    sembol: str           # THYAO.IS formatında
    ad: str               # şirket adı
    fiyat: Optional[float]
    degisim_pct: Optional[float]
    hacim: Optional[float]
    ort_hacim_10g: Optional[float]
    rsi: Optional[float]
    macd: Optional[float]
    macd_sinyal: Optional[float]
    ema20: Optional[float]
    ema50: Optional[float]
    ema200: Optional[float]
    bb_ust: Optional[float]
    bb_alt: Optional[float]
    piyasa_degeri: Optional[float]
    yuksek_1m: Optional[float]
    dusuk_1m: Optional[float]
    perf_hafta: Optional[float]
    perf_ay: Optional[float]


def _guvence(v, tip=float):
    """None veya NaN değerini None'a çevirir."""
    if v is None:
        return None
    try:
        r = tip(v)
        import math
        return None if math.isnan(r) else r
    except (TypeError, ValueError):
        return None


def tv_tara(
    limit: int = 1000,
    min_piyasa_degeri: float = 0,
    timeout: int = 20,
) -> tuple[bool, str, list[TVSatir]]:
    """
    TradingView scanner'dan tüm BIST hisselerini çeker.

    Dönüş: (basarili, hata_mesaji, satir_listesi)
    Başarısızsa satir_listesi boştur.
    """
    payload = json.dumps({
        "filter": [],
        "options": {"lang": "tr"},
        "markets": ["turkey"],
        "symbols": {"query": {"types": ["stock"]}, "tickers": []},
        "columns": _KOLONLAR,
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, min(limit, 1000)],
    }).encode()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }

    try:
        istek = urllib.request.Request(_TV_SCAN_URL, data=payload, headers=headers)
        with urllib.request.urlopen(istek, timeout=timeout) as yanit:
            raw = yanit.read()
        data = json.loads(raw)
    except Exception as exc:
        return False, f"TradingView erişim hatası: {exc}", []

    satirlar: list[TVSatir] = []
    for item in data.get("data", []):
        d = item.get("d", [])
        if len(d) < len(_KOLONLAR):
            d = d + [None] * (len(_KOLONLAR) - len(d))

        ham_sembol = str(d[0] or "")
        sembol = ham_sembol.replace("BIST:", "") + ".IS"

        pd_val = _guvence(d[14])
        if min_piyasa_degeri and pd_val and pd_val < min_piyasa_degeri:
            continue

        satirlar.append(TVSatir(
            sembol=sembol,
            ad=str(d[1] or sembol),
            fiyat=_guvence(d[2]),
            degisim_pct=_guvence(d[3]),
            hacim=_guvence(d[4]),
            ort_hacim_10g=_guvence(d[5]),
            rsi=_guvence(d[6]),
            macd=_guvence(d[7]),
            macd_sinyal=_guvence(d[8]),
            ema20=_guvence(d[9]),
            ema50=_guvence(d[10]),
            ema200=_guvence(d[11]),
            bb_ust=_guvence(d[12]),
            bb_alt=_guvence(d[13]),
            piyasa_degeri=pd_val,
            yuksek_1m=_guvence(d[15]),
            dusuk_1m=_guvence(d[16]),
            perf_hafta=_guvence(d[17]),
            perf_ay=_guvence(d[18]),
        ))

    if not satirlar:
        return False, "TradingView'dan hiç hisse verisi gelmedi", []

    return True, "", satirlar


def sinyal_puan(s: TVSatir) -> int:
    """
    Teknik sinyal puanı hesaplar (deterministik, 0-100 arası değil ham skor).
    Pozitif = güçlü, negatif = zayıf.
    """
    puan = 0

    # RSI
    if s.rsi is not None:
        if s.rsi < 30:
            puan += 20   # aşırı satım
        elif s.rsi < 40:
            puan += 10
        elif s.rsi > 70:
            puan -= 15   # aşırı alım (rölatif olarak kötü alım noktası)
        elif s.rsi > 60:
            puan += 5    # güçlü momentum

    # MACD
    if s.macd is not None and s.macd_sinyal is not None:
        if s.macd > s.macd_sinyal:
            puan += 10
        else:
            puan -= 10

    # EMA düzeni (kısa > uzun = trend yukarı)
    if s.ema20 and s.ema50:
        if s.ema20 > s.ema50:
            puan += 8
        else:
            puan -= 5

    if s.ema50 and s.ema200:
        if s.ema50 > s.ema200:
            puan += 10
        else:
            puan -= 8

    # Fiyat EMA ilişkisi
    if s.fiyat and s.ema20:
        if s.fiyat > s.ema20 * 1.02:  # EMA20'nin %2 üstü
            puan += 5
        elif s.fiyat < s.ema20 * 0.98:
            puan -= 5

    # Bollinger
    if s.fiyat and s.bb_alt and s.bb_ust:
        band_gen = s.bb_ust - s.bb_alt
        if band_gen > 0:
            pozisyon = (s.fiyat - s.bb_alt) / band_gen
            if pozisyon < 0.2:   # bant altına yakın — potansiyel dönüş
                puan += 8
            elif pozisyon > 0.9:  # banda dayanmış — dikkat
                puan -= 5

    # Hacim anormalliği (olumlu yönde hareketle birlikte değer kazanır)
    if s.hacim and s.ort_hacim_10g and s.ort_hacim_10g > 0:
        oran = s.hacim / s.ort_hacim_10g
        if oran > 2 and s.degisim_pct and s.degisim_pct > 0:
            puan += 10  # hacimli yükseliş

    return puan
