"""
İşlem Alışkanlık Analizi (Özellik #2).

Son N işlemi (portfolio_islemler) inceler:
  - Kazanma oranı, ortalama kâr/zarar, ortalama tutuş süresi
  - Tekrarlayan hatalar ve DUYGUSAL işlem davranışları:
      * Revenge trade (zarardan hemen sonra hızlı yeni alım)
      * Erken kâr alma / geç zarar kesme
      * Aşırı işlem (overtrading) — kısa sürede çok işlem
      * Aynı hisseye tekrar tekrar girip kaybetme
  - Sana özel 3 NET kural üretir (sayılara dayalı)

Veri: SQLite portfolio_islemler. İşlem yoksa açıkça belirtir, uydurmaz.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import sqlite3


@dataclass
class IslemAnaliz:
    islem_sayisi: int
    kapali_islem: int          # eşleşen AL→SAT sayısı
    kazanma_orani: float       # %
    ort_kar_pct: float
    ort_zarar_pct: float
    ort_tutus_gun: float
    hatalar: list = field(default_factory=list)       # tespit edilen alışkanlıklar
    kurallar: list = field(default_factory=list)      # 3 kişisel kural
    ok: bool = True
    not_: str = ""


def _islemleri_oku(db_path: str, n: int = 40) -> list[dict]:
    """Son n işlemi kronolojik (eski→yeni) döndürür."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT symbol,yon,tarih,fiyat,adet,tutar,gerekce "
            "FROM portfolio_islemler ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]


def _gun_farki(t1: str, t2: str) -> float:
    try:
        d1 = datetime.strptime(t1[:10], "%Y-%m-%d")
        d2 = datetime.strptime(t2[:10], "%Y-%m-%d")
        return abs((d2 - d1).days)
    except Exception:
        return 0.0


def analiz_et(db_path: str, n: int = 20) -> IslemAnaliz:
    """Son n işlemi analiz eder, alışkanlıkları çıkarır, 3 kural üretir."""
    islemler = _islemleri_oku(db_path, n=n * 2)  # eşleştirme için fazla çek
    if not islemler:
        return IslemAnaliz(0, 0, 0, 0, 0, 0, ok=False,
                           not_="Henüz işlem geçmişi yok. Sanal Portföy'den alım-satım "
                                "yaptıkça burada alışkanlık analizi oluşur.")

    # AL→SAT eşleştir (FIFO, hisse bazında) → kapalı işlemler
    acik: dict[str, list[dict]] = {}
    kapali = []  # {symbol, getiri_pct, tutus_gun, al_tarih, sat_tarih}
    for it in islemler:
        sym = it["symbol"]
        if it["yon"] == "AL":
            acik.setdefault(sym, []).append(it)
        elif it["yon"] == "SAT" and acik.get(sym):
            al = acik[sym].pop(0)
            al_fiyat = al["fiyat"] or 0
            if al_fiyat > 0:
                getiri = (it["fiyat"] - al_fiyat) / al_fiyat * 100
                kapali.append({
                    "symbol": sym,
                    "getiri_pct": getiri,
                    "tutus_gun": _gun_farki(al["tarih"], it["tarih"]),
                    "al_tarih": al["tarih"],
                    "sat_tarih": it["tarih"],
                })

    # Son n işlemle sınırla (kapalı işlemler)
    kapali = kapali[-n:]

    hatalar = []
    kurallar = []

    if not kapali:
        return IslemAnaliz(
            islem_sayisi=len(islemler), kapali_islem=0,
            kazanma_orani=0, ort_kar_pct=0, ort_zarar_pct=0, ort_tutus_gun=0,
            hatalar=["Henüz kapanmış (AL→SAT) işlem yok — sadece açık pozisyonlar var."],
            kurallar=["Pozisyon kapatınca getiri/alışkanlık analizi anlamlanır."],
            ok=True, not_="Kapalı işlem yok.")

    kazananlar = [k for k in kapali if k["getiri_pct"] > 0]
    kaybedenler = [k for k in kapali if k["getiri_pct"] <= 0]
    kazanma_orani = len(kazananlar) / len(kapali) * 100
    ort_kar = sum(k["getiri_pct"] for k in kazananlar) / len(kazananlar) if kazananlar else 0
    ort_zarar = sum(k["getiri_pct"] for k in kaybedenler) / len(kaybedenler) if kaybedenler else 0
    ort_tutus = sum(k["tutus_gun"] for k in kapali) / len(kapali)

    # ── Alışkanlık tespiti ──

    # 1) Erken kâr / geç zarar: kazananları çok kısa tutup kaybedenleri uzun tutma
    if kazananlar and kaybedenler:
        kar_tutus = sum(k["tutus_gun"] for k in kazananlar) / len(kazananlar)
        zarar_tutus = sum(k["tutus_gun"] for k in kaybedenler) / len(kaybedenler)
        if zarar_tutus > kar_tutus * 1.3:
            hatalar.append(
                f"⚠️ Zarardaki pozisyonları ({zarar_tutus:.0f} gün) kârdakilerden "
                f"({kar_tutus:.0f} gün) DAHA UZUN tutuyorsun — 'umut ederek bekleme' kalıbı.")
            kurallar.append(
                f"KURAL: Bir pozisyon stop seviyesine gelince UMUT ETME, kes. "
                f"Zararı {kar_tutus:.0f} günden uzun taşıma.")

    # 2) Ortalama kâr < ortalama zarar büyüklüğü → risk/ödül ters
    if ort_kar > 0 and ort_zarar < 0 and ort_kar < abs(ort_zarar):
        hatalar.append(
            f"⚠️ Ortalama kârın (%{ort_kar:.1f}) ortalama zararından (%{ort_zarar:.1f}) "
            f"KÜÇÜK — küçük kârla çıkıp büyük zarara katlanıyorsun.")
        kurallar.append(
            "KURAL: Her işleme girmeden önce hedef ve stop belirle; "
            "risk/ödül en az 1:1.5 olmadan girme.")

    # 3) Revenge trade: zarar eden bir satıştan sonra <=1 gün içinde yeni alım
    revenge = 0
    for i in range(1, len(islemler)):
        onceki, simdi = islemler[i - 1], islemler[i]
        if onceki["yon"] == "SAT" and simdi["yon"] == "AL":
            if _gun_farki(onceki["tarih"], simdi["tarih"]) <= 1:
                revenge += 1
    if revenge >= 2:
        hatalar.append(
            f"⚠️ {revenge} kez satıştan hemen sonra (≤1 gün) yeni alım yaptın — "
            f"'kaybı geri alma' (revenge trade) davranışı olabilir.")
        kurallar.append(
            "KURAL: Zarar kapatan işlemden sonra 24 saat YENİ pozisyon açma; "
            "duygusal işlemi soğut.")

    # 4) Overtrading: çok kısa sürede çok işlem
    if len(islemler) >= 10:
        toplam_gun = _gun_farki(islemler[0]["tarih"], islemler[-1]["tarih"]) or 1
        gunluk_islem = len(islemler) / toplam_gun
        if gunluk_islem > 1.5:
            hatalar.append(
                f"⚠️ Günde ortalama {gunluk_islem:.1f} işlem — aşırı işlem (overtrading); "
                f"komisyon ve hata riskini artırır.")
            kurallar.append(
                "KURAL: Günde en fazla 2-3 nitelikli işlem yap; her işlem bir tez içersin.")

    # 5) Aynı hisseye tekrar girip kaybetme
    from collections import Counter
    kayip_sym = Counter(k["symbol"] for k in kaybedenler)
    tekrar_kayip = [s for s, c in kayip_sym.items() if c >= 2]
    if tekrar_kayip:
        hatalar.append(
            f"⚠️ Şu hisselerde tekrar tekrar zarar ettin: {', '.join(tekrar_kayip)} — "
            f"'inatlaşma' kalıbı; bu hisseler sana uymuyor olabilir.")
        kurallar.append(
            f"KURAL: 2 kez üst üste zarar ettiren hisseye ({', '.join(tekrar_kayip)}) "
            f"bir süre girme; tarafsız bakana kadar bekle.")

    # 6) Düşük kazanma oranı genel uyarı
    if kazanma_orani < 40 and len(kapali) >= 5:
        hatalar.append(
            f"⚠️ Kazanma oranın %{kazanma_orani:.0f} — işlemlerin çoğu zararla kapanıyor. "
            f"Giriş kriterlerini sıkılaştır.")

    # 3 kuraldan az çıktıysa genel kurallarla tamamla
    genel_kurallar = [
        "KURAL: Her işleme girmeden önce stop seviyeni yaz; stop'suz işlem açma.",
        "KURAL: Tek pozisyona sermayenin %10'undan fazlasını koyma.",
        "KURAL: İşlem sonrası 'neden girdim, ne öğrendim' diye günlüğe not al.",
    ]
    for gk in genel_kurallar:
        if len(kurallar) >= 3:
            break
        if gk not in kurallar:
            kurallar.append(gk)
    kurallar = kurallar[:3]

    if not hatalar:
        hatalar.append("✅ Belirgin tekrarlayan hata tespit edilmedi — disiplinli görünüyorsun.")

    return IslemAnaliz(
        islem_sayisi=len(islemler), kapali_islem=len(kapali),
        kazanma_orani=round(kazanma_orani, 1),
        ort_kar_pct=round(ort_kar, 2), ort_zarar_pct=round(ort_zarar, 2),
        ort_tutus_gun=round(ort_tutus, 1),
        hatalar=hatalar, kurallar=kurallar, ok=True,
    )


def metin_ozet(a: IslemAnaliz) -> str:
    """IslemAnaliz'i Telegram/panel metnine çevirir."""
    if not a.ok:
        return f"📭 İşlem Alışkanlık Analizi\n\n{a.not_}"

    sat = [
        "🧠 İŞLEM ALIŞKANLIK ANALİZİ",
        f"(son {a.kapali_islem} kapalı işlem, {a.islem_sayisi} toplam emir)",
        "",
        f"🎯 Kazanma oranı: %{a.kazanma_orani}",
        f"📈 Ort. kâr: %{a.ort_kar_pct:+.2f} · 📉 Ort. zarar: %{a.ort_zarar_pct:+.2f}",
        f"⏳ Ort. tutuş: {a.ort_tutus_gun} gün",
        "",
        "🔍 TESPİT EDİLEN ALIŞKANLIKLAR:",
    ]
    for h in a.hatalar:
        sat.append(f"   {h}")

    sat += ["", "📌 SANA ÖZEL 3 KURAL (yarından itibaren):"]
    for i, k in enumerate(a.kurallar, 1):
        sat.append(f"   {i}. {k}")

    sat += ["", "⚠️ Analiz geçmiş işlem kayıtlarına dayanır; finansal tavsiye değildir."]
    return "\n".join(sat)
