"""
Portföy Alarmları (Öneri #2 + #3).

Elindeki her pozisyonu kontrol eder ve şu durumlarda uyarı üretir:
  - 🛑 Fiyat teknik STOP seviyesini kırdı
  - ⚠️ Fiyat teknik stop'a YAKIN (%2 içinde)
  - 🎯 Fiyat teknik HEDEFE ulaştı (kâr realize sinyali)
  - 📉 Pozisyon stop-loss yüzde eşiğini aştı (config.RISK)

Seviyeler teknik_derin'den (gerçek hesap), zarar yüzdesi gerçek maliyetten gelir.
Veri yoksa o hisse atlanır, uydurulmaz. Çıktı yatırım tavsiyesi değildir.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Alarm:
    sembol: str
    tip: str        # "stop", "stop_yakin", "hedef", "zarar"
    mesaj: str
    oncelik: int    # 0 = en kritik


def portfoy_alarmlari(db_path: str, risk_cfg: dict) -> list[Alarm]:
    """Açık pozisyonları tarar, tetiklenen alarmları döndürür (önceliğe göre sıralı)."""
    from portfolio.ozet import acik_pozisyonlar
    from data.access import veri_getir
    from analysis.teknik_derin import analiz_et

    pos = acik_pozisyonlar(db_path)
    alarmlar: list[Alarm] = []
    stop_esik = risk_cfg.get("stop_loss_pct", -0.08) * 100   # örn -8.0

    for sembol, p in pos.items():
        kod = sembol.replace(".IS", "")
        fr = veri_getir(db_path, sembol, period="1y", interval="1d")
        if not fr.ok or fr.data is None or len(fr.data) < 30:
            continue
        guncel = float(fr.data["Close"].iloc[-1])
        maliyet = p.get("maliyet") or 0

        # Gerçek maliyete göre zarar yüzdesi
        if maliyet > 0:
            kz_pct = (guncel - maliyet) / maliyet * 100
            if kz_pct <= stop_esik:
                alarmlar.append(Alarm(
                    kod, "zarar",
                    f"📉 {kod}: %{kz_pct:+.1f} zararda — stop-loss eşiği (%{stop_esik:.0f}) "
                    f"aşıldı (maliyet {maliyet:.2f} → {guncel:.2f}). Pozisyonu gözden geçir.",
                    oncelik=0))

        # Teknik seviyeler
        k = analiz_et(fr.data, sembol)
        if not k.ok:
            continue
        # SAT kararında zarar_kes = fiyatın ÜSTÜNDEKİ direnç, kar_al = ALTINDAKİ
        # destek anlamına gelir (long-stop/hedef DEĞİL). Bu seviyeleri stop/hedef
        # gibi kıyaslamak neredeyse her zaman yanlış tetiklenir → SAT'te atla.
        if k.karar == "SAT":
            continue
        if k.zarar_kes and guncel <= k.zarar_kes:
            alarmlar.append(Alarm(
                kod, "stop",
                f"🛑 {kod}: {guncel:.2f} — teknik STOP {k.zarar_kes} kırıldı.",
                oncelik=0))
        elif k.zarar_kes and guncel <= k.zarar_kes * 1.02:
            alarmlar.append(Alarm(
                kod, "stop_yakin",
                f"⚠️ {kod}: {guncel:.2f} — teknik stop'a YAKIN ({k.zarar_kes}). İzle.",
                oncelik=1))
        if k.kar_al and guncel >= k.kar_al:
            alarmlar.append(Alarm(
                kod, "hedef",
                f"🎯 {kod}: {guncel:.2f} — teknik HEDEFE ulaştı ({k.kar_al}). "
                f"Kâr realize / stop yukarı çekmeyi düşün.",
                oncelik=1))

    alarmlar.sort(key=lambda a: a.oncelik)
    return alarmlar


def alarm_metni(alarmlar: list[Alarm], baslik: str = "🚨 PORTFÖY ALARMLARI") -> str:
    """Alarm listesini Telegram/panel metnine çevirir."""
    if not alarmlar:
        return (f"{baslik}\n\n✅ Aktif alarm yok — hiçbir pozisyon stop/hedef "
                "seviyesinde değil.")
    sat = [baslik, ""]
    for a in alarmlar:
        sat.append(a.mesaj)
    sat += ["", "⚠️ Teknik seviyelere dayanır, yatırım tavsiyesi değildir."]
    return "\n".join(sat)
