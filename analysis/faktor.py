"""
Çok-Faktörlü KESİTSEL Sıralama Motoru — "quant fon" seviyesi hisse seçimi.

Basit eşik-tabanlı filtreleme yerine, tüm BIST evrenini (~600 hisse) tek bir
kesit (cross-section) olarak ele alır ve her hisseyi EVREN İÇİNDEKİ göreli
konumuna göre persentil (0-100) puanlar. Kanıtlanmış akademik/kurumsal
yöntemler uygulanır:

  • Fama-French / AQR tarzı ÇOK-FAKTÖR: Değer, Kalite, Momentum, Büyüme, Trend.
  • Piotroski F-Score (0-9): bilanço sağlamlığının ayrık puanı.
  • Greenblatt "Magic Formula": kazanç verimi + ROIC ortak sırası.

Kritik felsefe (kullanıcı isteği): "tavan yapmış/uçmuş" hisseyi KOVALAMA.
Momentum faktörü aşırı-alım (RSI) ve köpük (aşırı aylık getiri) durumunda
CEZALANDIRILIR; böylece motor kaliteli ama makul giriş sunan hisseleri öne
çıkarır, parabolik hareketleri değil.

Tüm veri gerçektir (TradingView + yfinance). Eksik veri UYDURULMAZ: bir
faktörün alt-metrikleri yoksa o faktör o hisse için None kalır ve persentil
sıralamasına dahil edilmez (nötr sayılır), ya da hisse tümden elenir.

Bu modül SAF matematiktir (ağ gerektirmez); veri, çağıran katmandan gelir.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Sequence


# ── Persentil (kesitsel sıralama çekirdeği) ───────────────────────────────────

def persentil_sirala(degerler: Sequence[Optional[float]],
                     yuksek_iyi: bool = True) -> list[Optional[float]]:
    """
    Bir metrik listesini evren içinde 0-100 persentile çevirir.

    - yuksek_iyi=True: en yüksek değer ~100, en düşük ~0 persentil alır.
    - yuksek_iyi=False: ters (düşük değer iyi → yüksek persentil).
    - None değerler sıralamaya girmez ve None kalır (veri yok = nötr).

    "Ortalama sıra" (average rank) yöntemi kullanılır: eşit değerler aynı
    persentili alır. Tek elemanlı geçerli evrende persentil 50 (nötr) verilir
    çünkü göreli bir sıralama anlamsızdır.
    """
    n = len(degerler)
    idx_gecerli = [i for i, v in enumerate(degerler) if v is not None]
    m = len(idx_gecerli)
    sonuc: list[Optional[float]] = [None] * n
    if m == 0:
        return sonuc
    if m == 1:
        sonuc[idx_gecerli[0]] = 50.0
        return sonuc

    # (deger, orijinal_index) sıralı
    sirali = sorted(idx_gecerli, key=lambda i: degerler[i])
    # Ortalama sıra: eşitlikler için ortalama pozisyon
    sira = [0.0] * n
    j = 0
    while j < m:
        k = j
        while k + 1 < m and degerler[sirali[k + 1]] == degerler[sirali[j]]:
            k += 1
        ort_poz = (j + k) / 2.0   # 0-tabanlı ortalama sıra
        for t in range(j, k + 1):
            sira[sirali[t]] = ort_poz
        j = k + 1

    for i in idx_gecerli:
        p = sira[i] / (m - 1) * 100.0   # 0..100
        sonuc[i] = p if yuksek_iyi else (100.0 - p)
    return sonuc


def _ort(persentiller: Sequence[Optional[float]]) -> Optional[float]:
    """None'ları atlayarak ortalama; hepsi None ise None."""
    gec = [p for p in persentiller if p is not None]
    if not gec:
        return None
    return sum(gec) / len(gec)


# ── Köpük / tavan cezası (momentum kırpma) ────────────────────────────────────

def kopuk_cezasi(rsi: Optional[float], perf_ay: Optional[float]) -> float:
    """
    0.0 (tam ceza) – 1.0 (ceza yok) arası momentum çarpanı döndürür.

    Kullanıcı isteği: "tavan yapmış/uçmuş" hisseyi kovalamayalım. Yüksek RSI ve
    aşırı aylık getiri, momentum puanını KIRPAR (parabolik = köpük riski):

      • RSI 65-80 arası doğrusal ceza; 80+ neredeyse sıfır momentum katkısı.
      • Aylık getiri %20-40 arası doğrusal ceza; %40+ ağır kırpma.

    Böylece "yavaş ama sağlam yükselen" hisse, "uçmuş" hisseden daha yüksek
    momentum puanı alabilir. Veri yoksa nötr (1.0) — ceza uydurulmaz.
    """
    carpan = 1.0
    if rsi is not None:
        if rsi >= 80:
            carpan *= 0.1
        elif rsi > 65:
            carpan *= 1.0 - (rsi - 65) / 15.0 * 0.9   # 65→1.0, 80→0.1
    if perf_ay is not None:
        if perf_ay >= 40:
            carpan *= 0.15
        elif perf_ay > 20:
            carpan *= 1.0 - (perf_ay - 20) / 20.0 * 0.85  # 20→1.0, 40→0.15
    return max(0.0, min(1.0, carpan))


# ── Piotroski F-Score (mevcut alanlara uyarlanmış, 0-9) ───────────────────────

def piotroski_fscore(k) -> tuple[int, int, list[str]]:
    """
    Piotroski (2000) F-Score'un mevcut kesit verisiyle uyarlanmış biçimi.

    Klasik F-Score dokuz ayrık (0/1) testten oluşur; bazıları yıl-üstü
    (t vs t-1) değişim gerektirir. Elimizde tek kesit olduğu için değişim
    gerektiren testler, mantıken eşdeğer seviye-testleriyle karşılanır:

      Kârlılık (4):
        1. Net kâr pozitif           → net_marj > 0
        2. Operasyonel nakit pozitif → fcf_marj > 0 (nakit üretiyor)
        3. ROE pozitif (kârlılık)    → roe > 0
        4. Nakit kalitesi (tahakkuk) → fcf_marj >= net_marj (kâr nakde dönüyor)
      Kaldıraç/Likidite (3):
        5. Düşük kaldıraç            → borc_ozkaynak < 1
        6. Cari oran sağlam          → cari_oran > 1
        7. Sulandırma yok (vekil)    → net_kar_buyume > -10 (özkaynak erimiyor)
      Verimlilik (2):
        8. Marj sağlığı              → net_marj >= 5
        9. Büyüme (döngü hızı vekil) → gelir_buyume > 0

    Dönüş: (skor 0-9, degerlendirilen_test_sayisi, gerekce_listesi).
    Veri yoksa o test atlanır (uydurulmaz); degerlendirilen < 9 olabilir.
    Karşılaştırma için puan, 9 üzerinden ölçeklenmiş rapor edilir.
    """
    skor = 0
    n = 0
    g: list[str] = []

    def test(kosul: Optional[bool], iyi_msg: str, kotu_msg: str):
        nonlocal skor, n
        if kosul is None:
            return
        n += 1
        if kosul:
            skor += 1
            g.append("✓ " + iyi_msg)
        else:
            g.append("✗ " + kotu_msg)

    finans = _finans_mu(getattr(k, "sektor", None))

    test(None if k.net_marj is None else k.net_marj > 0,
         "net kâr pozitif", "zarar ediyor")
    test(None if k.fcf_marj is None else k.fcf_marj > 0,
         "nakit üretiyor (FCF+)", "nakit yakıyor (FCF-)")
    test(None if k.roe is None else k.roe > 0,
         "ROE pozitif", "ROE negatif")
    test(None if (k.fcf_marj is None or k.net_marj is None)
         else k.fcf_marj >= k.net_marj,
         "kâr nakde dönüyor (tahakkuk düşük)", "kâr nakde dönmüyor")
    # Kaldıraç: finans sektörü doğal yüksek kaldıraçlı — test atlanır (uydurma yok)
    if not finans:
        test(None if k.borc_ozkaynak is None else k.borc_ozkaynak < 1,
             "düşük kaldıraç", "yüksek kaldıraç")
        test(None if k.cari_oran is None else k.cari_oran > 1,
             "cari oran > 1", "cari oran < 1")
    test(None if k.net_kar_buyume is None else k.net_kar_buyume > -10,
         "net kâr erimiyor", "net kâr çöküyor")
    test(None if k.net_marj is None else k.net_marj >= 5,
         "marj sağlıklı (≥%5)", "marj zayıf")
    test(None if k.gelir_buyume is None else k.gelir_buyume > 0,
         "gelir büyüyor", "gelir küçülüyor")

    return skor, n, g


# ── Sektör muafiyeti (kalite.py mantığıyla hizalı) ────────────────────────────

_FINANS = (
    "finance", "financial", "bank", "insurance", "banka", "sigorta",
    "finans", "holding", "leasing", "factoring", "gayrimenkul yatırım",
    "real estate investment", "reit",
)


def _finans_mu(sektor: Optional[str]) -> bool:
    if not sektor:
        return False
    s = sektor.lower()
    return any(a in s for a in _FINANS)


# ── Ham faktör çıkarımları (persentil öncesi) ─────────────────────────────────

def kazanc_verimi(fk: Optional[float]) -> Optional[float]:
    """Earnings yield = 1 / F/K (yalnızca F/K > 0). Negatif kârda anlamsız."""
    if fk is None or fk <= 0:
        return None
    return 1.0 / fk


def ham_deger(k) -> dict:
    """Değer alt-metrikleri (yüksek=iyi olacak biçimde işaretlenir)."""
    return {
        "kazanc_verimi": kazanc_verimi(k.fk),       # yüksek iyi
        "pddd": k.pddd,                              # düşük iyi (ters çevrilecek)
        "temettu": k.temettu,                        # yüksek iyi
    }


def ham_momentum(perf_ay: Optional[float], getiri_3a: Optional[float],
                 getiri_6a: Optional[float]) -> Optional[float]:
    """
    Orta-vade momentum ham değeri: mevcut getiri sinyallerinin ortalaması.
    yfinance 3-6 aylık getiri varsa kullanılır; yoksa perf_ay tek başına.
    (Köpük cezası burada DEĞİL, persentil sonrası çarpan olarak uygulanır.)
    """
    parcalar = [x for x in (perf_ay, getiri_3a, getiri_6a) if x is not None]
    if not parcalar:
        return None
    return sum(parcalar) / len(parcalar)


def trend_sagligi(fiyat: Optional[float], ema50: Optional[float],
                  ema200: Optional[float]) -> Optional[float]:
    """
    Trend sağlığı ham puanı (0-100): uzun vade yukarı mı, düşen bıçak mı?
      +50 fiyat > EMA200 (uzun vade yukarı)
      +50 EMA50 > EMA200 (altın kesişim düzeni)
    Hiç EMA verisi yoksa None.
    """
    if ema200 is None and ema50 is None:
        return None
    p = 0.0
    if fiyat is not None and ema200 is not None:
        p += 50.0 if fiyat > ema200 else 0.0
    if ema50 is not None and ema200 is not None:
        p += 50.0 if ema50 > ema200 else 0.0
    return p


# ── Faktör kaydı ──────────────────────────────────────────────────────────────

@dataclass
class FaktorKayit:
    sembol: str
    sektor: str
    # Persentiller (0-100), evren içi
    deger_p: Optional[float] = None
    kalite_p: Optional[float] = None
    momentum_p: Optional[float] = None      # köpük cezası UYGULANMIŞ
    momentum_ham_p: Optional[float] = None  # ceza öncesi (şeffaflık)
    buyume_p: Optional[float] = None
    trend_p: Optional[float] = None
    # Kanıtlanmış skorlar
    piotroski: int = 0
    piotroski_n: int = 0
    magic_sira: Optional[int] = None        # 1 = en iyi
    # Birleşik
    birlesik: float = 0.0
    kopuk_carpan: float = 1.0
    # Ham metrikler (rapor için)
    fk: Optional[float] = None
    roe: Optional[float] = None
    rsi: Optional[float] = None
    perf_ay: Optional[float] = None
    piyasa_degeri: Optional[float] = None
    piotroski_gerekce: list = field(default_factory=list)


# ── Birleşik skor ağırlıkları ─────────────────────────────────────────────────
# Gerekçe: KALİTE en ağır (kalıcı üstün getiri kaynağı, AQR "quality-minus-junk").
# DEĞER ikinci (klasik value primi). MOMENTUM üçüncü ama köpük-cezalı (tavan
# kovalamayı önlemek için). BÜYÜME destekleyici. TREND/giriş en düşük — sadece
# "düşen bıçak" ve kötü zamanlamayı elemek için, aşırı ağırlık verilmez.
AGIRLIKLAR = {
    "kalite": 0.30,
    "deger": 0.25,
    "momentum": 0.20,
    "buyume": 0.15,
    "trend": 0.10,
}


def birlesik_skor(f: FaktorKayit, agirliklar: dict = AGIRLIKLAR) -> float:
    """
    Faktör persentillerinin ağırlıklı harmanı (0-100).

    None persentiller ölçekten düşürülür (o faktör bu hisse için nötr sayılır ve
    ağırlığı kalan faktörlere yeniden dağıtılır) — böylece eksik veri olan hisse
    haksız yere 0 almaz, ama var olan sağlam faktörleri ödüllendirilir.
    """
    parcalar = [
        (f.kalite_p, agirliklar["kalite"]),
        (f.deger_p, agirliklar["deger"]),
        (f.momentum_p, agirliklar["momentum"]),
        (f.buyume_p, agirliklar["buyume"]),
        (f.trend_p, agirliklar["trend"]),
    ]
    gecerli = [(p, w) for p, w in parcalar if p is not None]
    if not gecerli:
        return 0.0
    toplam_a = sum(w for _, w in gecerli)
    return sum(p * w for p, w in gecerli) / toplam_a


# ── Motorun ana giriş noktası ─────────────────────────────────────────────────

@dataclass
class EvrenGirdi:
    """Tek hisse için ham girdi (çağıran katman TV + yfinance'tan doldurur)."""
    sembol: str
    kalite: object                      # TVKalite
    teknik: object                      # TVSatir (fiyat, rsi, ema...) — None olabilir
    getiri_3a: Optional[float] = None   # yfinance 3 aylık getiri %
    getiri_6a: Optional[float] = None   # yfinance 6 aylık getiri %


def faktor_evreni(girdiler: list[EvrenGirdi],
                  agirliklar: dict = AGIRLIKLAR) -> list[FaktorKayit]:
    """
    Tüm evren için kesitsel faktör puanlarını hesaplar.

    Adımlar:
      1. Her hisse için ham faktör bileşenlerini çıkar (gerçek veriyle).
      2. Her bileşeni EVREN içinde persentile çevir.
      3. Kalite/Değer/Büyüme'yi alt-persentillerin ortalaması olarak birleştir.
      4. Momentum persentiline KÖPÜK CEZASI çarpanı uygula (tavan kovalamayı önle).
      5. Piotroski F-Score ve Magic Formula sırasını ekle.
      6. Ağırlıklı birleşik skoru hesapla ve sırala.
    """
    from analysis.kalite import kalite_skoru

    n = len(girdiler)
    kayitlar = [FaktorKayit(sembol=g.sembol.replace(".IS", ""),
                            sektor=getattr(g.kalite, "sektor", "—"))
                for g in girdiler]

    # ── 1) Ham metrik dizileri ──
    kazanc_v, pddd_ters, temettu = [], [], []
    kalite_skorlari = []                       # kalite.py 0-100 skoru
    momentum_ham = []
    gelir_b, netkar_b = [], []
    roic_list = []                             # Magic Formula için
    trend_ham = []

    for i, g in enumerate(girdiler):
        k = g.kalite
        t = g.teknik
        r = kayitlar[i]

        r.fk = k.fk
        r.roe = k.roe
        r.piyasa_degeri = k.piyasa_degeri
        if t is not None:
            r.rsi = t.rsi
            r.perf_ay = t.perf_ay

        d = ham_deger(k)
        kazanc_v.append(d["kazanc_verimi"])
        pddd_ters.append(d["pddd"])            # düşük iyi → persentil ters çevrilir
        temettu.append(d["temettu"])

        ks = kalite_skoru(k)
        kalite_skorlari.append(float(ks.skor) if ks.etiket != "veri yok" else None)

        perf_ay = t.perf_ay if t is not None else k.perf_1m
        momentum_ham.append(ham_momentum(perf_ay, g.getiri_3a, g.getiri_6a))

        gelir_b.append(k.gelir_buyume)
        netkar_b.append(k.net_kar_buyume)
        roic_list.append(k.roic)

        if t is not None:
            trend_ham.append(trend_sagligi(t.fiyat, t.ema50, t.ema200))
        else:
            trend_ham.append(None)

        # Piotroski
        p_skor, p_n, p_g = piotroski_fscore(k)
        r.piotroski = p_skor
        r.piotroski_n = p_n
        r.piotroski_gerekce = p_g

    # ── 2) Persentiller ──
    p_kazanc = persentil_sirala(kazanc_v, yuksek_iyi=True)
    p_pddd = persentil_sirala(pddd_ters, yuksek_iyi=False)     # düşük PD/DD iyi
    p_temettu = persentil_sirala(temettu, yuksek_iyi=True)
    p_kalite = persentil_sirala(kalite_skorlari, yuksek_iyi=True)
    p_momentum = persentil_sirala(momentum_ham, yuksek_iyi=True)
    p_gelir = persentil_sirala(gelir_b, yuksek_iyi=True)
    p_netkar = persentil_sirala(netkar_b, yuksek_iyi=True)
    p_trend = persentil_sirala(trend_ham, yuksek_iyi=True)

    # ── 3-4) Faktörleri birleştir + köpük cezası ──
    for i, r in enumerate(kayitlar):
        g = girdiler[i]
        r.deger_p = _ort([p_kazanc[i], p_pddd[i], p_temettu[i]])
        r.kalite_p = p_kalite[i]
        r.buyume_p = _ort([p_gelir[i], p_netkar[i]])
        r.trend_p = p_trend[i]

        r.momentum_ham_p = p_momentum[i]
        r.kopuk_carpan = kopuk_cezasi(r.rsi, r.perf_ay)
        if p_momentum[i] is not None:
            # Köpük cezası momentum persentilini AŞAĞI çeker (çarpan). Böylece
            # "uçmuş/tavan" hissesinin yüksek ham momentum'u SİLİNİR ve sağlıklı
            # yükselen bir hisseden daha düşük momentum katkısı alır — tavan
            # kovalamayı bu adım engeller. Ceza yoksa (carpan=1) persentil aynen.
            r.momentum_p = p_momentum[i] * r.kopuk_carpan
        else:
            r.momentum_p = None

    # ── 5) Magic Formula ortak sırası (kazanç verimi + ROIC) ──
    _magic_formula_sirala(kayitlar, kazanc_v, roic_list)

    # ── 6) Birleşik skor ──
    for r in kayitlar:
        r.birlesik = birlesik_skor(r, agirliklar)

    kayitlar.sort(key=lambda x: -x.birlesik)
    return kayitlar


def _magic_formula_sirala(kayitlar, kazanc_v, roic_list):
    """
    Greenblatt Magic Formula: kazanç verimi ve ROIC'e göre AYRI sıralar yapılır,
    iki sıra toplanır, en düşük toplam en iyi (birinci) olur.

    Sadece her iki metriği de olan hisseler sıralanır (uydurma yok); ikisinden
    biri eksikse magic_sira None kalır.
    """
    idx = [i for i in range(len(kayitlar))
           if kazanc_v[i] is not None and roic_list[i] is not None]
    if not idx:
        return
    # Kazanç verimi sırası (yüksek iyi → sıra 1 = en yüksek)
    ev_sira = {i: r for r, i in enumerate(
        sorted(idx, key=lambda i: -kazanc_v[i]))}
    roic_sira = {i: r for r, i in enumerate(
        sorted(idx, key=lambda i: -roic_list[i]))}
    toplam = sorted(idx, key=lambda i: ev_sira[i] + roic_sira[i])
    for sira, i in enumerate(toplam, 1):
        kayitlar[i].magic_sira = sira
