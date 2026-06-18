"""
Eğitim + uygulamalı içerikler:
  #3 Risk yönetimi (stop-loss, pozisyon büyüklüğü, çeşitlendirme) — SENİN sermayenle örnekli
  #5 Ekonomik göstergeler (GSYİH, enflasyon, faiz, işsizlik) → borsa etkisi
  #10 Küresel olaylar (jeopolitik, pandemi) → korunma stratejileri

#3 gerçek hesap içerir (config.RISK + sermaye). #5 ve #10 genel finans bilgisidir
(canlı makro veri çekmez — sistem TR makro beslemesi içermez, bu yüzden sayı
uydurmaz, ilişkileri açıklar).
"""

from __future__ import annotations


# ── #3 Risk Yönetimi (uygulamalı) ─────────────────────────────────────────────

def risk_yonetimi(db_path: str, sermaye: float | None = None) -> str:
    import config
    from analysis import risk as risk_mod

    sermaye = sermaye or float(config.INITIAL_CAPITAL)
    poz_pct = config.RISK["pozisyon_pct"]
    stop_pct = abs(config.RISK["stop_loss_pct"])
    yogun = config.RISK["yogunlasma_uyari_pct"]

    # Örnek pozisyon büyüklüğü (örnek fiyat 100 ₺)
    pb = risk_mod.pozisyon_buyuklugu(sermaye, 100.0, poz_pct)
    tek_poz = sermaye * poz_pct
    risk_tutar = tek_poz * stop_pct   # bir işlemde riske atılan TL

    sat = [
        "🛡️ RİSK YÖNETİMİ — 3 Temel Teknik",
        f"(Senin ayarların: sermaye {sermaye:,.0f} ₺)",
        "",
        "1️⃣ POZİSYON BÜYÜKLÜĞÜ",
        f"   Kural: tek hisseye sermayenin en fazla %{poz_pct*100:.0f}'i "
        f"= {tek_poz:,.0f} ₺",
        f"   Örnek: 100 ₺'lik hisseden ~{pb['adet']} adet alınır.",
        "   Neden: tek bir hisse battığında portföyün küçük kısmı etkilenir.",
        "",
        "2️⃣ STOP-LOSS (zarar kes)",
        f"   Kural: her işlemde %{stop_pct*100:.0f} zararda çık.",
        f"   Örnek: {tek_poz:,.0f} ₺'lik pozisyonda en fazla "
        f"~{risk_tutar:,.0f} ₺ risk edersin.",
        "   Neden: küçük zararlar büyük zarara dönüşmeden kesilir. "
        "Stop'suz işlem AÇMA.",
        "",
        "3️⃣ ÇEŞİTLENDİRME",
        f"   Kural: tek hisse portföyün %{yogun*100:.0f}'ini geçmesin; "
        "farklı sektörlere yay.",
        "   Neden: bir sektör çökerken diğerleri dengeler. "
        "(detay: /cesitlendir)",
        "",
        "📐 1R MANTIĞI: 'risk birimi' = stop'a olan mesafe. Hedefin en az "
        "1.5–2R olsun (kazanç, riskin 1.5–2 katı). Bot /analiz ve /fikirler'de "
        "risk/ödülü bunun için verir.",
        "",
        "⚠️ Eğitim amaçlıdır; yatırım tavsiyesi değildir. /alarmlar ile "
        "pozisyonlarını stop açısından izleyebilirsin.",
    ]
    return "\n".join(sat)


# ── #5 Ekonomik Göstergeler ───────────────────────────────────────────────────

def ekonomik_gostergeler() -> str:
    return "\n".join([
        "📈 EKONOMİK GÖSTERGELER → BORSA ETKİSİ",
        "",
        "🏦 FAİZ (en önemlisi - TCMB politika faizi)",
        "   Faiz ↑ → borsa genelde ↓ (mevduat/bono cazipleşir, kredi pahalı).",
        "   En hassas: bankacılık (marj), GYO/inşaat, yüksek borçlu şirketler.",
        "   Faiz ↓ → borsa genelde ↑, özellikle büyüme hisseleri.",
        "",
        "💸 ENFLASYON",
        "   Yüksek enflasyon → belirsizlik, reel getiri baskısı.",
        "   Korunaklı: fiyatlama gücü olanlar (perakende lider, enerji, ihracatçı).",
        "   Zarar gören: sabit gelirli/maliyeti hızlı artan sektörler.",
        "",
        "📊 GSYİH (büyüme)",
        "   Büyüme ↑ → şirket kârları ↑ → borsa olumlu (döngüsel sektörler: "
        "otomotiv, dayanıklı tüketim, sanayi).",
        "",
        "👷 İŞSİZLİK",
        "   İşsizlik ↑ → tüketim ↓ → perakende/hizmet baskı altında.",
        "",
        "💱 KUR (USD/TRY) — TR'de kritik",
        "   Kur ↑ → ihracatçı/dolar geliri olanlar kazanır (THYAO, EREGL, "
        "madencilik); ithalatçı/dolar borçlusu kaybeder.",
        "",
        "🧭 NASIL KULLANILIR:",
        "   • Faiz artış döngüsünde bankacılığa, kur yükselişinde ihracatçıya bak.",
        "   • Bir veri açıklanınca hangi sektörü etkiler diye düşün, /sektor ile incele.",
        "",
        "ℹ️ Bu genel finans bilgisidir. Sistem canlı TR makro verisi (TÜİK/TCMB) "
        "ÇEKMEZ — istersen o besleme ayrıca eklenebilir. Yatırım tavsiyesi değildir.",
    ])


# ── #10 Küresel Olaylar ───────────────────────────────────────────────────────

def kuresel_olaylar() -> str:
    return "\n".join([
        "🌍 KÜRESEL OLAYLAR → PİYASA & KORUNMA",
        "",
        "⚔️ JEOPOLİTİK GERİLİM (savaş, yaptırım)",
        "   Etki: oynaklık ↑, petrol/altın ↑, riskli varlıklar ↓.",
        "   Kazanan: enerji, savunma, altın. Kaybeden: turizm, havayolu, ithalatçı.",
        "",
        "🦠 PANDEMİ / KRİZ",
        "   Etki: ani sert düşüş, sonra ayrışma.",
        "   Dayanıklı: gıda perakende, sağlık, teknoloji. Vurulan: ulaşım, AVM, turizm.",
        "",
        "🛡️ KORUNMA STRATEJİLERİ (portföyü savunmak):",
        "   1) Nakit oranını artır — en basit, maliyetsiz hedge.",
        "   2) Defansif sektörlere kay (gıda, kamu hizmetleri, sağlık).",
        "   3) Altın/döviz ile sistemik şoka kısmi tampon.",
        "   4) Pozisyonları küçült, stop'ları sıkılaştır (/alarmlar izler).",
        "   5) Kaldıraçtan kaçın; panikle satma, planına sadık kal.",
        "",
        "📉 TARİHSEL DERS: Büyük düşüşler geçicidir ama zamanlaması bilinmez. "
        "Çeşitlendirme + nakit tamponu, krizden çıkışta hayatta kalmanı sağlar.",
        "",
        "🧭 Uygula: /cesitlendir (sektör dengesi) · /portfoy (risk) · /duyarlilik "
        "(piyasa korku/açgözlülük).",
        "",
        "ℹ️ Genel finans bilgisidir; canlı haber/olay verisine bağlı değildir. "
        "Yatırım tavsiyesi değildir.",
    ])
