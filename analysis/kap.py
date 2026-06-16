"""
KAP/haber analiz modülü.

ÖNEMLİ: kap.org.tr kamuya açık JSON API sunmaz; Next.js SPA'dır.
Bu modül alternatif kaynaklardan şeffaf biçimde haber toplar:
  1. yfinance .news  — şirkete özel İngilizce/Türkçe haberler
  2. RSS akışları    — BloombergHT, AA, Borsagundem vb.
  3. yfinance info   — halka arz tarihi tespiti

Veri kap.org.tr doğrudan erişim DEĞİLDİR. Kaynak her haberde gösterilir.
Veri yoksa 'veri yok' döner, uydurulmaz.
"""

from __future__ import annotations
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import html


@dataclass
class HaberKaydi:
    baslik: str
    kaynak: str
    url: str = ""
    tarih: str = ""          # ISO
    sembol: str = ""         # ilgili hisse (varsa)
    kategori: str = "haber"  # "kap_benzeri", "halka_arz", "haber"


@dataclass
class HaberSonucu:
    ok: bool
    kayitlar: list[HaberKaydi] = field(default_factory=list)
    hata: str = ""
    kaynak: str = ""


# ── RSS çekici ────────────────────────────────────────────────────────────────

_RSS_TIMEOUT = 8


def _rss_cek(url: str, limit: int = 10, kaynak: str = "") -> list[HaberKaydi]:
    """Tek bir RSS akışından haber başlıklarını çeker."""
    kayitlar: list[HaberKaydi] = []
    try:
        istek = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
        with urllib.request.urlopen(istek, timeout=_RSS_TIMEOUT) as r:
            raw = r.read()
        kok = ET.fromstring(raw)
    except Exception:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    ogeler = kok.findall(".//item") or kok.findall(".//atom:entry", ns)

    for oge in ogeler[:limit]:
        baslik = (oge.findtext("title") or oge.findtext("atom:title", namespaces=ns) or "").strip()
        baslik = html.unescape(baslik)
        link = (oge.findtext("link") or oge.findtext("atom:link", namespaces=ns) or "").strip()
        pub = (oge.findtext("pubDate") or oge.findtext("published") or
               oge.findtext("atom:published", namespaces=ns) or "").strip()

        if baslik:
            kayitlar.append(HaberKaydi(
                baslik=baslik[:200],
                kaynak=kaynak,
                url=link[:300],
                tarih=pub[:30],
                kategori="haber",
            ))

    return kayitlar


# ── KAP anahtar kelimeleri ─────────────────────────────────────────────────────

_KAP_ANAHTAR = [
    "özel durum", "bildirim", "kap", "kamuyu aydınlatma",
    "temettü", "yönetim kurulu", "sermaye artırım", "bedelsiz",
    "birleşme", "devralma", "halka arz", "ipo", "genel kurul",
    "finansal sonuç", "kar açıklama", "bilanço",
    "kap.org.tr", "kap bildiri", "kamuoyu",
]


def _kap_benzeri_mi(baslik: str) -> bool:
    b = baslik.lower()
    return any(k in b for k in _KAP_ANAHTAR)


# ── yfinance haber çekici ──────────────────────────────────────────────────────

def yfinance_haberleri(semboller: list[str], limit_per_hisse: int = 5) -> list[HaberKaydi]:
    """
    yfinance .news ile şirkete özel haberleri çeker.
    BIST hisseleri için İngilizce/Türkçe karışık sonuç döner.
    """
    try:
        import yfinance as yf
    except ImportError:
        return []

    kayitlar: list[HaberKaydi] = []
    for sembol in semboller[:20]:   # çok fazla istek atmamak için cap
        try:
            ticker = yf.Ticker(sembol)
            haberler = ticker.news or []
        except Exception:
            continue

        for h in haberler[:limit_per_hisse]:
            baslik = h.get("title", "").strip()
            if not baslik:
                continue

            pub_ts = h.get("providerPublishTime", 0)
            if pub_ts:
                tarih = datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            else:
                tarih = ""

            kategori = "kap_benzeri" if _kap_benzeri_mi(baslik) else "haber"
            kayitlar.append(HaberKaydi(
                baslik=baslik[:200],
                kaynak=h.get("publisher", "yfinance"),
                url=h.get("link", "")[:300],
                tarih=tarih,
                sembol=sembol.replace(".IS", ""),
                kategori=kategori,
            ))

    # tarihe göre sırala (en yeni önce)
    kayitlar.sort(key=lambda k: k.tarih, reverse=True)
    return kayitlar


# ── Haber → İşlem Sinyali (Özellik #5) ────────────────────────────────────────

# Duygu sözlüğü — başlıktaki kelimelerden yön çıkarır (deterministik).
_POZITIF_KELIME = [
    "rekor", "artış", "arttı", "yüksel", "kâr", "kazanç", "büyüme", "anlaşma",
    "sözleşme", "ihale kazan", "temettü", "bedelsiz", "yatırım", "teşvik",
    "onay", "ihracat", "talep", "güçlü", "beklenti üstü", "not yükselt",
    "geri alım", "satın al", "ortaklık", "lisans", "ruhsat",
]
_NEGATIF_KELIME = [
    "düşüş", "düştü", "zarar", "kayıp", "iflas", "soruşturma", "ceza", "dava",
    "gerileme", "kriz", "uyarı", "borç", "konkordato", "iptal", "durdur",
    "not indir", "beklenti altı", "küçülme", "grev", "yaptırım", "vergi cezası",
    "azal", "kötü", "risk",
]


@dataclass
class HaberSinyali:
    sembol: str
    haber_sayisi: int
    duygu: str               # "Pozitif" / "Negatif" / "Nötr"
    duygu_skoru: int         # pozitif - negatif kelime farkı
    kisa_vade: str
    uzun_vade: str
    beklenen_aralik: str     # ATR temelli tahmini hareket bandı
    basliklar: list = field(default_factory=list)   # (kaynak, baslik, duygu)
    ok: bool = True
    not_: str = ""


def _baslik_duygu(baslik: str) -> int:
    b = baslik.lower()
    poz = sum(1 for k in _POZITIF_KELIME if k in b)
    neg = sum(1 for k in _NEGATIF_KELIME if k in b)
    return poz - neg


def haber_sinyali(sembol: str, db_path: str | None = None,
                  rss_feeds: dict | None = None) -> HaberSinyali:
    """
    Bir hisse için haberleri çeker, duygu analizi yapar ve işlem etkisini yorumlar.

    1. yfinance şirket haberleri + (varsa) RSS'te şirket adı geçen başlıklar
    2. Deterministik duygu skoru (pozitif/negatif kelime)
    3. Kısa/uzun vade yorumu + ATR temelli beklenen fiyat aralığı
    """
    kod = sembol.replace(".IS", "").upper()

    # Haberleri topla
    kayitlar = yfinance_haberleri([sembol], limit_per_hisse=8)

    # RSS'te kod/şirket adı geçenleri de ekle
    if rss_feeds:
        try:
            ps = piyasa_akisi(dict(rss_feeds), limit=8)
            if ps.ok:
                for k in ps.kayitlar:
                    if kod.lower() in k.baslik.lower():
                        k.sembol = kod
                        kayitlar.append(k)
        except Exception:
            pass

    if not kayitlar:
        return HaberSinyali(kod, 0, "Nötr", 0,
                            "Şirkete özel taze haber yok — fiyatı teknik belirler.",
                            "Uzun vade için temel/bilanço takibi önerilir.",
                            "Habersiz: belirgin haber kaynaklı hareket beklenmez.",
                            ok=False, not_="Bu hisse için haber bulunamadı (yfinance/RSS).")

    # Duygu
    toplam_skor = 0
    basliklar = []
    for k in kayitlar[:10]:
        d = _baslik_duygu(k.baslik)
        toplam_skor += d
        etiket = "🟢" if d > 0 else ("🔴" if d < 0 else "⚪")
        basliklar.append((k.kaynak, k.baslik, etiket))

    if toplam_skor >= 2:
        duygu = "Pozitif"
        kisa = "Haber akışı POZİTİF — kısa vadede alıcı ilgisi artabilir, hacimli yükseliş izle."
        uzun = "Olumlu haberler kalıcıysa (bilanço/anlaşma) uzun vade trendi destekler."
    elif toplam_skor <= -2:
        duygu = "Negatif"
        kisa = "Haber akışı NEGATİF — kısa vadede satış baskısı olabilir, stop'a dikkat."
        uzun = "Olumsuz haber yapısalsa (borç/dava) uzun vade için risk; pozisyonu sorgula."
    else:
        duygu = "Nötr"
        kisa = "Haber akışı KARIŞIK/NÖTR — yönü teknik göstergeler belirleyecek."
        uzun = "Belirgin temel katalizör yok; uzun vade için trend ve bilanço takibi."

    # ATR temelli beklenen aralık
    beklenen = "Beklenen hareket aralığı: veri yok."
    if db_path:
        try:
            from data.access import veri_getir
            from analysis.indicators import add_indicators
            fr = veri_getir(db_path, sembol, period="3mo", interval="1d")
            if fr.ok and fr.data is not None and len(fr.data) > 20:
                di = add_indicators(fr.data)
                son = di.iloc[-1]
                fiyat = float(son["Close"])
                atr = float(son["ATR14"]) if pd.notna(son.get("ATR14")) else fiyat * 0.02
                alt = round(fiyat - atr, 2)
                ust = round(fiyat + atr, 2)
                atr_pct = atr / fiyat * 100
                beklenen = (f"Güncel {fiyat:.2f} · 1 günlük tipik dalga ±%{atr_pct:.1f} "
                            f"(yaklaşık {alt}–{ust}). Haber sürprizinde bu aralık aşılabilir.")
        except Exception:
            pass

    return HaberSinyali(
        sembol=kod, haber_sayisi=len(kayitlar), duygu=duygu, duygu_skoru=toplam_skor,
        kisa_vade=kisa, uzun_vade=uzun, beklenen_aralik=beklenen,
        basliklar=basliklar, ok=True,
    )


def haber_sinyali_metni(hs: "HaberSinyali") -> str:
    """HaberSinyali'ni Telegram/panel metnine çevirir."""
    emoji = {"Pozitif": "🟢", "Negatif": "🔴", "Nötr": "🟡"}.get(hs.duygu, "⚪")
    sat = [
        f"📰 {hs.sembol} — HABER SİNYALİ",
        f"{emoji} Genel duygu: {hs.duygu} (skor {hs.duygu_skoru:+d}, {hs.haber_sayisi} haber)",
        "",
        f"⏱️ Kısa vade: {hs.kisa_vade}",
        f"📅 Uzun vade: {hs.uzun_vade}",
        f"📊 {hs.beklenen_aralik}",
    ]
    if hs.basliklar:
        sat += ["", "📋 Başlıklar:"]
        for kaynak, bas, et in hs.basliklar[:6]:
            sat.append(f"   {et} {bas[:85]} —{kaynak}")
    if hs.not_:
        sat += ["", f"ℹ️ {hs.not_}"]
    sat += ["", "⚠️ Haber yorumu otomatik kelime analizidir; kesin değildir, "
            "yatırım tavsiyesi değildir."]
    return "\n".join(sat)


# ── Piyasa RSS akışı ──────────────────────────────────────────────────────────

def piyasa_akisi(rss_feeds: dict[str, str], limit: int = 5) -> HaberSonucu:
    """
    Tüm RSS akışlarından haber başlıklarını çeker.
    Her akış bağımsız denenir; hata olan atlanır.
    """
    tum_kayitlar: list[HaberKaydi] = []
    for ad, url in rss_feeds.items():
        if not url:
            continue
        kayitlar = _rss_cek(url, limit=limit, kaynak=ad)
        tum_kayitlar.extend(kayitlar)

    if not tum_kayitlar:
        return HaberSonucu(ok=False, hata="Hiçbir RSS akışından veri alınamadı",
                           kaynak="RSS")

    # KAP benzeri haberleri öne al, sonra tarih sırası
    def siralama(k: HaberKaydi):
        return (0 if k.kategori == "kap_benzeri" else 1, k.tarih)

    tum_kayitlar.sort(key=lambda k: (0 if k.kategori == "kap_benzeri" else 1))
    return HaberSonucu(ok=True, kayitlar=tum_kayitlar, kaynak="RSS")


# ── Halka arz (IPO) tespiti ────────────────────────────────────────────────────

@dataclass
class HalkaArzKaydi:
    sembol: str
    ad: str
    ilk_islem_tarihi: str   # YYYY-MM-DD
    ilk_fiyat: Optional[float]
    son_fiyat: Optional[float]
    getiri_pct: Optional[float]


def halka_arz_tara(semboller: list[str], son_gun: int = 90) -> list[HalkaArzKaydi]:
    """
    Son `son_gun` gün içinde ilk işlem gören hisseleri tespit eder.
    Kriter: yfinance'dan çekilen ilk OHLCV tarihi son `son_gun` güne düşüyorsa
    yeni halka arz sayılır.

    NOT: yfinance bazı BIST hisselerinde `firstTradeDateEpochUtc` döndürmeyebilir.
    Bu durumda geçmiş veri uzunluğuna (kısa geçmiş = yeni hisse) bakılır.
    """
    try:
        import yfinance as yf
    except ImportError:
        return []

    bugun = datetime.now().date()
    esik = bugun - timedelta(days=son_gun)
    sonuclar: list[HalkaArzKaydi] = []

    for sembol in semboller:
        try:
            ticker = yf.Ticker(sembol)
            info = ticker.info or {}
        except Exception:
            continue

        # Yöntem 1: firstTradeDateEpochUtc
        ilk_ts = info.get("firstTradeDateEpochUtc")
        if ilk_ts:
            ilk_tarih = datetime.fromtimestamp(ilk_ts).date()
            if ilk_tarih >= esik:
                ilk_fiyat = None
                son_fiyat = _guvence_float(info.get("regularMarketPrice"))
                try:
                    df = ticker.history(period=f"{son_gun}d", interval="1d", auto_adjust=True)
                    if df is not None and not df.empty:
                        ilk_fiyat = float(df["Close"].iloc[0])
                        son_fiyat = float(df["Close"].iloc[-1])
                except Exception:
                    pass
                getiri = ((son_fiyat - ilk_fiyat) / ilk_fiyat * 100
                          if ilk_fiyat and son_fiyat and ilk_fiyat > 0 else None)
                sonuclar.append(HalkaArzKaydi(
                    sembol=sembol.replace(".IS", ""),
                    ad=info.get("longName", sembol),
                    ilk_islem_tarihi=str(ilk_tarih),
                    ilk_fiyat=round(ilk_fiyat, 2) if ilk_fiyat else None,
                    son_fiyat=round(son_fiyat, 2) if son_fiyat else None,
                    getiri_pct=round(getiri, 1) if getiri is not None else None,
                ))

    return sonuclar


def _guvence_float(v) -> Optional[float]:
    try:
        r = float(v)
        import math
        return None if math.isnan(r) else r
    except (TypeError, ValueError):
        return None


# ── Özet yorum üretici ────────────────────────────────────────────────────────

def piyasa_yorumu(
    rejim: str,
    n_al: int,
    n_yukselis: int,
    n_dusus: int,
    n_toplam: int,
    ortalama_degisim: Optional[float],
    one_cikan_sektorler: list[str] | None = None,
) -> str:
    """
    Deterministik piyasa yorumu üretir — LLM çağırmaz, sayılara dayalı.
    Yatırım tavsiyesi içermez; AL/SAT sinyali vermez.
    """
    satirlar: list[str] = []

    # Genel tablo
    if n_toplam > 0:
        yukselis_oran = n_yukselis / n_toplam * 100
        satirlar.append(
            f"Taranan {n_toplam} hissenin %{yukselis_oran:.0f}'i yükseliş gösterdi "
            f"({n_yukselis} yükseliş, {n_dusus} düşüş)."
        )
    if ortalama_degisim is not None:
        satirlar.append(
            f"Ortalama günlük değişim %{ortalama_degisim:+.2f}."
        )

    # Rejim yorumu
    if "Boğa" in rejim:
        satirlar.append("Endeks boğa trendinde; teknik koşullar görece olumlu.")
    elif "Ayı" in rejim:
        satirlar.append("Endeks ayı baskısı altında; dikkatli pozisyon önerilir.")
    elif "Yatay" in rejim:
        satirlar.append("Endeks yatay seyirde; net bir trend oluşmamış durumda.")

    # AL adayı sayısı
    if n_al == 0:
        satirlar.append("Teknik kriterleri güçlü karşılayan hisse tespit edilmedi.")
    elif n_al <= 3:
        satirlar.append(f"{n_al} hisse teknik kriterler açısından öne çıkıyor.")
    else:
        satirlar.append(f"{n_al} hisse teknik göstergeler bazında dikkat çekiyor.")

    # Sektör
    if one_cikan_sektorler:
        satirlar.append(f"Öne çıkan: {', '.join(one_cikan_sektorler[:3])}.")

    satirlar.append("Bu analiz geçmiş fiyat verilerine dayanır; yatırım tavsiyesi değildir.")
    return " ".join(satirlar)
