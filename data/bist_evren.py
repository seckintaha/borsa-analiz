"""
BIST tam evren yöneticisi.

TradingView scanner'dan 500 hisse çeker ve .IS suffix'i ekler.
Sonuç haftalık önbellekte saklanır (kap_evren.json).
"""

from __future__ import annotations
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta

_ONBELLEK = os.path.join(os.path.dirname(os.path.dirname(__file__)), "raporlar", "bist_evren.json")
_ONBELLEK_GUN = 7          # kaç günde bir güncellenir
_TV_URL = "https://scanner.tradingview.com/turkey/scan"

# Likit olmayan / ETF / sertifika / warrant tipi araçlar — hisse analizi için uygun değil
_FILTRE_SUFFIX = ("F", "E", "G", "W")  # Fon, ETF, Garanti belgesi, Warrant

# Minimum piyasa değeri filtresi yoktur — kullanıcı tüm şirketleri istiyor


def _tv_cek() -> list[str]:
    """TradingView scanner'dan tüm BIST hisselerini çeker."""
    payload = json.dumps({
        "filter": [{"left": "exchange", "operation": "equal", "right": "BIST"}],
        "options": {"lang": "tr"},
        "markets": ["turkey"],
        "symbols": {"query": {"types": ["stock"]}, "tickers": []},
        "columns": ["name", "description", "market_cap_basic", "type"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 1000],
    }).encode()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
    }
    req = urllib.request.Request(_TV_URL, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return [
            item["s"].replace("BIST:", "") + ".IS"
            for item in data.get("data", [])
            if not item["s"].replace("BIST:", "").endswith(_FILTRE_SUFFIX)
        ]
    except Exception:
        return []


def _onbellekten_oku() -> list[str] | None:
    try:
        if not os.path.exists(_ONBELLEK):
            return None
        with open(_ONBELLEK, encoding="utf-8") as f:
            obj = json.load(f)
        tarih = datetime.fromisoformat(obj["tarih"])
        if datetime.now() - tarih > timedelta(days=_ONBELLEK_GUN):
            return None
        return obj["hisseler"]
    except Exception:
        return None


def _onbellege_yaz(hisseler: list[str]) -> None:
    os.makedirs(os.path.dirname(_ONBELLEK), exist_ok=True)
    with open(_ONBELLEK, "w", encoding="utf-8") as f:
        json.dump({"tarih": datetime.now().isoformat(), "hisseler": hisseler}, f,
                  ensure_ascii=False)


def bist_evren_al(zorla_guncelle: bool = False) -> list[str]:
    """
    BIST'teki tüm hisselerin listesini döndürür (.IS suffix'li).
    Önbellekten okur; eski veya zorla_guncelle=True ise TradingView'dan çeker.
    """
    if not zorla_guncelle:
        onbellek = _onbellekten_oku()
        if onbellek:
            return onbellek

    hisseler = _tv_cek()
    if hisseler:
        _onbellege_yaz(hisseler)
        return hisseler

    # TradingView başarısız → statik BIST100 listesi (yedek)
    return _statik_bist100()


def _statik_bist100() -> list[str]:
    """TradingView erişilemezse kullanılan statik yedek BIST100 listesi."""
    tickers = [
        "AKBNK","AKSEN","ALARK","ALBRK","ARCLK","ASELS","ASTOR","AYDEM","AYGAZ",
        "BERA","BIMAS","BIOEN","BTCIM","CCOLA","CIMSA","CWENE","DOAS","DOHOL",
        "EGEEN","ENJSA","ENKAI","EREGL","EUPWR","FROTO","GARAN","GESAN","GUBRF",
        "HALKB","HEKTS","ISCTR","ISGYO","ISDMR","IZMDC","KCHOL","KERVT","KNFRT",
        "KOZAA","KOZAL","KRDMD","LOGO","MAVI","MGROS","MPARK","NETAS","ODAS",
        "OTKAR","OYAKC","PETKM","PGSUS","SAHOL","SASA","SELGD","SISE","SKBNK",
        "SMGE","SNGYO","SOKM","SONME","TATGD","TAVHL","TCELL","THYAO","TKFEN",
        "TOASO","TSKB","TTKOM","TTRAK","TUPRS","ULKER","VAKBN","VESTL","YKBNK",
        "AKGRT","ANHYT","ASUZU","BAGFS","BANVT","BRISA","BUCIM","CEMTS","DEVA",
        "ECILC","EDIP","EGPRO","EKGYO","ERBOS","ETILR","GEDZA","GLYHO","GOODY",
        "GRSEL","HURGZ","ICBCT","IHLAS","INDES","IPEKE","KARTN","KATMR","KLNMA",
        "KONYA","LKMNH","LUKSK","MAALT","MNDRS","NTHOL","NUGYO","ORGE","PRKME",
        "QUAGR","RYSAS","SAMAT","SERVE","SGCIM","SMRTG","SNPAM","SURGE","TRCAS",
        "TRGYO","TRILC","UFUK","ULUUN","VERUS","YATAS","YKSGR","YUNSA","ZOREN",
    ]
    return [t + ".IS" for t in tickers]
