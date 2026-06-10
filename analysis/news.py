"""
KAP & Haber katmanı (Aşama 4).

İlke (yol haritası Bölüm 1 ve 6): hiçbir haber uydurulmaz. Her kayıt bir
**kaynağa** ve **yayın zamanına** bağlıdır. Veri yoksa/eksikse açıkça belirtilir
(HaberSonuc.ok = False), boşluk doldurulmaz.

Kaynaklar:
- Hisseye özel haber: yfinance (ek anahtar gerekmez).
- Genel piyasa / KAP bildirimleri: config.HABER["rss_feeds"]'e eklenen RSS
  adresleri (saf stdlib ile okunur, ek bağımlılık yok). Boşsa atlanır.

NOT: Haberler ham bilgidir; hiçbiri yatırım tavsiyesi değildir ve doğruluğu
garanti edilmez.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse
import urllib.request

# XML'i güvenli ayrıştır: defusedxml varsa entity-bomb / harici varlık (XXE)
# saldırılarına karşı korur; yoksa stdlib'e düşer (indirme boyutu yine sınırlı).
try:
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:
    from xml.etree.ElementTree import fromstring as _xml_fromstring

# Güvenlik sınırları
_IZINLI_SEMALAR = ("http", "https")   # file://, ftp:// vb. engellenir (SSRF/yerel dosya)
_MAX_RSS_BAYT = 3_000_000              # 3 MB üstü indirilmez (bellek DoS koruması)


def _http_url_mu(url: str) -> bool:
    """Yalnızca http/https adreslerine izin verir (yerel dosya/SSRF koruması)."""
    try:
        return urlparse(url).scheme.lower() in _IZINLI_SEMALAR
    except Exception:
        return False


@dataclass
class HaberKaydi:
    baslik: str
    kaynak: str          # yayıncı/feed adı (Reuters, KAP, ...)
    zaman: str           # yayın zamanı (ISO veya kaynaktaki ham metin)
    link: str
    symbol: str = ""
    ozet: str = ""
    saglayici: str = ""  # "yfinance" / "rss" — nereden çekildi


@dataclass
class HaberSonuc:
    ok: bool
    kayitlar: list = field(default_factory=list)
    fetched_at: str = ""
    not_: str = ""       # veri yok / hata açıklaması


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _unix_iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return ""


# ── Hisseye özel haber (yfinance) ─────────────────────────────────────────────

def hisse_haberleri(symbol: str, limit: int = 8) -> HaberSonuc:
    """Tek sembol için son haberleri yfinance üzerinden çeker."""
    symbol = symbol.strip().upper()
    fetched_at = _now_iso()
    try:
        import yfinance as yf
    except ImportError:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_="yfinance kurulu değil (pip install yfinance)")

    try:
        ham = yf.Ticker(symbol).news or []
    except Exception as exc:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_=f"haber çekme hatası: {exc}")

    kayitlar = []
    for h in ham[:limit]:
        # yfinance iki farklı şekil döndürebilir: düz dict ya da {"content": {...}}
        icerik = h.get("content", h) if isinstance(h, dict) else {}
        baslik = icerik.get("title") or h.get("title") or ""
        if not baslik:
            continue
        yayinci = (icerik.get("provider", {}) or {}).get("displayName") \
            or h.get("publisher") or "bilinmiyor"
        link = ""
        if isinstance(icerik.get("clickThroughUrl"), dict):
            link = icerik["clickThroughUrl"].get("url", "")
        link = link or h.get("link", "")
        zaman = icerik.get("pubDate") or _unix_iso(h.get("providerPublishTime"))
        kayitlar.append(HaberKaydi(
            baslik=baslik, kaynak=yayinci, zaman=zaman or "", link=link,
            symbol=symbol, saglayici="yfinance",
        ))

    if not kayitlar:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_=f"'{symbol}' için haber bulunamadı")
    return HaberSonuc(True, kayitlar=kayitlar, fetched_at=fetched_at)


# ── BIST hissesine özel haber (Türkçe RSS akışlarından, sembol-filtreli) ──────

# BIST sembol kodu → haber metninde aranacak anahtar kelimeler (şirket adları).
# Amaç: yfinance'ın BIST için verdiği ABD-odaklı/boş haberi bırakıp, Türkçe
# akışlardan o şirketle ilgili GERÇEK haberleri eşleştirmek. Eşleşme yoksa
# dürüstçe "haber yok" denir — asla uydurulmaz.
BIST_ISIM: dict = {
    "THYAO": ["Türk Hava Yolları", "THY", "Turkish Airlines"],
    "GARAN": ["Garanti BBVA", "Garanti Bankası", "Garanti"],
    "AKBNK": ["Akbank"],
    "YKBNK": ["Yapı Kredi"],
    "ISCTR": ["İş Bankası", "Türkiye İş Bankası"],
    "HALKB": ["Halkbank", "Halk Bankası"],
    "VAKBN": ["VakıfBank", "Vakıflar Bankası"],
    "ASELS": ["Aselsan"],
    "EREGL": ["Ereğli Demir Çelik", "Erdemir"],
    "PETKM": ["Petkim"],
    "TUPRS": ["Tüpraş"],
    "AKSEN": ["Aksa Enerji"],
    "ARCLK": ["Arçelik"],
    "VESTL": ["Vestel"],
    "PGSUS": ["Pegasus"],
    "TAVHL": ["TAV Havalimanları", "TAV"],
    "TOASO": ["Tofaş"],
    "FROTO": ["Ford Otosan", "Ford Otomotiv"],
    "TTKOM": ["Türk Telekom"],
    "TCELL": ["Turkcell"],
    "BIMAS": ["BİM"],
    "MGROS": ["Migros"],
    "ULKER": ["Ülker"],
    "SOKM": ["Şok Marketler", "ŞOK"],
    "KCHOL": ["Koç Holding"],
    "SAHOL": ["Sabancı Holding"],
    "SISE": ["Şişecam"],
    "SASA": ["Sasa Polyester", "Sasa"],
    "KOZAL": ["Koza Altın"],
    "KOZAA": ["Koza Anadolu"],
    "EKGYO": ["Emlak Konut"],
    "ENKAI": ["Enka İnşaat", "Enka"],
    "OYAKC": ["Oyak Çimento"],
    "HEKTS": ["Hektaş"],
    "GUBRF": ["Gübre Fabrikaları", "Gübretaş"],
}


def _tr_kucult(s: str) -> str:
    """Türkçe-duyarlı küçük harf (I→ı, İ→i) — eşleştirmeyi güvenli yapar."""
    return s.replace("I", "ı").replace("İ", "i").lower()


# Türkçe dahil harfler — anahtar kelime "tam kelime" olarak eşleşmeli ki
# "THY" → "Timothy" gibi yanlış pozitifler olmasın.
import re as _re
_HARF = "a-zàâçéèêîôû0-9ığüşöçâîû"


def _tam_kelime_var(metin: str, anahtar: str) -> bool:
    """anahtar, metinde tam kelime olarak (harf sınırlarıyla) geçiyor mu?"""
    desen = rf"(?<![{_HARF}]){_re.escape(anahtar)}(?![{_HARF}])"
    return _re.search(desen, metin) is not None


def hisse_haberleri_tr(symbol: str, rss_feeds: dict, limit: int = 8,
                       tarama_limit: int = 15) -> HaberSonuc:
    """
    BIST hissesi için Türkçe RSS akışlarından, şirket adıyla EŞLEŞEN haberleri
    süzer. yfinance yerine yerel/Türkçe kaynak kullanır. Eşleşme yoksa
    ok=False ("güncel haber bulunamadı") — boşluk uydurulmaz.
    """
    fetched_at = _now_iso()
    kod = symbol.strip().upper().replace(".IS", "")
    anahtarlar = [kod] + BIST_ISIM.get(kod, [])
    al = [_tr_kucult(a) for a in anahtarlar]

    r = piyasa_akisi(rss_feeds, limit=tarama_limit)
    if not r.ok:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_=f"Türkçe akış okunamadı: {r.not_}")

    secilen = []
    for k in r.kayitlar:
        metin = _tr_kucult(f"{k.baslik} {k.ozet}")
        if any(_tam_kelime_var(metin, a) for a in al):
            kk = HaberKaydi(baslik=k.baslik, kaynak=k.kaynak, zaman=k.zaman,
                            link=k.link, symbol=kod, ozet=k.ozet,
                            saglayici="rss-tr")
            secilen.append(kk)
        if len(secilen) >= limit:
            break

    if not secilen:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_=f"'{kod}' için Türkçe kaynaklarda güncel haber "
                               "bulunamadı (her gün her hisseye haber çıkmaz).")
    return HaberSonuc(True, kayitlar=secilen, fetched_at=fetched_at)


# ── Genel / KAP akışı (RSS, saf stdlib) ───────────────────────────────────────

def _rss_ayristir(xml_metni: str, feed_adi: str, limit: int) -> list[HaberKaydi]:
    """RSS 2.0 ve Atom akışlarını ayrıştırır (namespace'e dayanmaz, güvenli parser)."""
    kok = _xml_fromstring(xml_metni)

    def yerel(etiket: str) -> str:
        return etiket.rsplit("}", 1)[-1]  # namespace'i at

    def alan(ogol, *adlar):
        for c in ogol:
            if yerel(c.tag) in adlar and c.text:
                return c.text.strip()
        return ""

    def link_al(ogol):
        for c in ogol:
            if yerel(c.tag) == "link":
                if c.text and c.text.strip():
                    return c.text.strip()
                href = c.attrib.get("href")
                if href:
                    return href
        return ""

    ogeler = [e for e in kok.iter() if yerel(e.tag) in ("item", "entry")]
    out = []
    for o in ogeler[:limit]:
        baslik = alan(o, "title")
        if not baslik:
            continue
        out.append(HaberKaydi(
            baslik=baslik,
            kaynak=feed_adi,
            zaman=alan(o, "pubDate", "published", "updated"),
            link=link_al(o),
            ozet=alan(o, "description", "summary")[:280],
            saglayici="rss",
        ))
    return out


def rss_oku(feed_url: str, feed_adi: str = "RSS", limit: int = 10,
            timeout: float = 8.0) -> HaberSonuc:
    """Bir RSS/Atom akışını okur. Ağ/parse hatasında ok=False döner."""
    fetched_at = _now_iso()

    # Güvenlik: yalnızca http/https (file://, ftp:// engellenir)
    if not _http_url_mu(feed_url):
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_="güvenlik: yalnızca http/https adreslerine izin verilir")

    try:
        istek = urllib.request.Request(feed_url, headers={"User-Agent": "borsa-analiz/1.0"})
        with urllib.request.urlopen(istek, timeout=timeout) as yanit:
            # Boyut sınırı: aşırı büyük/kötücül akışa karşı bellek koruması
            ham_bayt = yanit.read(_MAX_RSS_BAYT + 1)
        if len(ham_bayt) > _MAX_RSS_BAYT:
            return HaberSonuc(False, fetched_at=fetched_at,
                              not_=f"akış çok büyük (> {_MAX_RSS_BAYT // 1_000_000} MB) — atlandı")
        kayitlar = _rss_ayristir(ham_bayt.decode("utf-8", errors="replace"), feed_adi, limit)
    except Exception as exc:
        # defusedxml entity-bomb dahil tüm parse/ağ hatalarını dürüstçe bildir
        return HaberSonuc(False, fetched_at=fetched_at, not_=f"RSS işleme hatası: {exc}")

    if not kayitlar:
        return HaberSonuc(False, fetched_at=fetched_at, not_="akışta haber yok")
    return HaberSonuc(True, kayitlar=kayitlar, fetched_at=fetched_at)


def piyasa_akisi(rss_feeds: dict, limit: int = 10) -> HaberSonuc:
    """config.HABER['rss_feeds']'deki tüm akışları toplar."""
    fetched_at = _now_iso()
    if not rss_feeds:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_="RSS akışı yapılandırılmamış (config.HABER['rss_feeds'] boş)")
    tum, hatalar = [], []
    for ad, url in rss_feeds.items():
        r = rss_oku(url, feed_adi=ad, limit=limit)
        if r.ok:
            tum.extend(r.kayitlar)
        else:
            hatalar.append(f"{ad}: {r.not_}")
    if not tum:
        return HaberSonuc(False, fetched_at=fetched_at,
                          not_="hiçbir akıştan haber alınamadı (" + "; ".join(hatalar) + ")")
    return HaberSonuc(True, kayitlar=tum, fetched_at=fetched_at,
                      not_=("bazı akışlar başarısız: " + "; ".join(hatalar)) if hatalar else "")
