"""
Portföy optimizasyonu (Aşama ekstra) — GERÇEK açık pozisyonlar için risk-optimal
ağırlık önerisi.

İlke: veri ASLA uydurulmaz. Yalnızca kullanıcının beyan ettiği açık pozisyonlar ve
bu hisselerin geçmiş kapanış fiyatları (data.access.veri_getir) kullanılır. Yeterli
veri yoksa dürüstçe belirtilir.

Bu AYRI bir araçtır; çekirdek öneri motorunu (recommender / ayin_onerileri) DEĞİŞTİRMEZ.
Amaç: mevcut ağırlıkları üç kıyas şemasıyla (eşit, ters-volatilite, minimum varyans)
karşılaştırıp tahmini yıllık portföy riskini düşürecek ağırlık önerisi vermek.

Saf hesap + veri okuma; harici pip paketi yok (yalnız numpy/pandas).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_ISLEM_GUN = 252  # yıllık işlem günü (volatilite ölçeklemesi için)


# ── Saf yardımcılar (ağ gerektirmez, doğrudan test edilebilir) ────────────────

def _gunluk_getiri(kapanis: pd.Series) -> pd.Series:
    """Kapanış serisinden günlük getiri; NaN/inf temizlenir."""
    getiri = kapanis.astype(float).pct_change()
    getiri = getiri.replace([np.inf, -np.inf], np.nan).dropna()
    return getiri


def _yillik_vol(getiri_df: pd.DataFrame) -> np.ndarray:
    """Her kolon (hisse) için yıllık volatilite: std * sqrt(252)."""
    std = getiri_df.std(axis=0, ddof=1).to_numpy(dtype=float)
    std = np.nan_to_num(std, nan=0.0, posinf=0.0, neginf=0.0)
    return std * np.sqrt(_ISLEM_GUN)


def _kovaryans(getiri_df: pd.DataFrame) -> np.ndarray:
    """Günlük getiri kovaryans matrisi (yıllıklaştırılmış)."""
    cov = getiri_df.cov().to_numpy(dtype=float)
    cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)
    return cov * _ISLEM_GUN


def _normalize(w: np.ndarray) -> np.ndarray:
    """Uzun-only, toplam=1 normalize. Toplam ~0 ise eşit ağırlığa düşer."""
    w = np.clip(np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0), 0.0, None)
    toplam = w.sum()
    if toplam <= 1e-12:
        n = len(w)
        return np.full(n, 1.0 / n) if n else w
    return w / toplam


def _esit_agirlik(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n) if n > 0 else np.array([])


def _ters_vol_agirlik(vol: np.ndarray) -> np.ndarray:
    """w_i ∝ 1/vol_i — yüksek volatiliteli hisse daha düşük ağırlık alır."""
    vol = np.asarray(vol, dtype=float)
    # Sıfır/negatif volatiliteyi çok küçük pozitif sayıyla koru (sıfıra bölme).
    pozitif = vol[vol > 0]
    taban = pozitif.min() * 1e-3 if pozitif.size else 1e-9
    guvenli = np.where(vol > 0, vol, taban)
    return _normalize(1.0 / guvenli)


def _min_varyans_agirlik(cov: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """
    Minimum varyans: w ∝ Σ⁻¹·1, negatifler 0'a kırpılır + yeniden normalize.
    Matris tekilse (ters alınamıyorsa) ters-volatiliteye düşülür.
    """
    n = cov.shape[0]
    if n == 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])
    bir = np.ones(n)
    try:
        ham = np.linalg.solve(cov, bir)
    except np.linalg.LinAlgError:
        return _ters_vol_agirlik(vol)
    if not np.all(np.isfinite(ham)):
        return _ters_vol_agirlik(vol)
    kirpik = np.clip(ham, 0.0, None)
    if kirpik.sum() <= 1e-12:      # tümü ≤0 → uzun-only anlamsız, ters-vol'e düş
        return _ters_vol_agirlik(vol)
    return _normalize(kirpik)


def _portfoy_vol(w: np.ndarray, cov: np.ndarray) -> float:
    """Yıllık portföy volatilitesi: sqrt(wᵀ Σ w)."""
    if len(w) == 0:
        return 0.0
    var = float(w @ cov @ w)
    return float(np.sqrt(var)) if var > 0 else 0.0


def _korelasyon_ciftleri(getiri_df: pd.DataFrame, esik: float = 0.7) -> list[dict]:
    """Korelasyonu eşik üstü olan hisse çiftleri (çeşitlendirme zayıflığı uyarısı)."""
    ciftler: list[dict] = []
    kolonlar = list(getiri_df.columns)
    if len(kolonlar) < 2:
        return ciftler
    korr = getiri_df.corr().to_numpy(dtype=float)
    for i in range(len(kolonlar)):
        for j in range(i + 1, len(kolonlar)):
            r = korr[i, j]
            if np.isfinite(r) and r > esik:
                ciftler.append({"a": kolonlar[i], "b": kolonlar[j],
                                "korelasyon": round(float(r), 2)})
    ciftler.sort(key=lambda c: c["korelasyon"], reverse=True)
    return ciftler


# ── Ana giriş ─────────────────────────────────────────────────────────────────

def portfoy_optimizasyon(db_path: str, pencere_gun: int = 180) -> dict:
    """
    Kullanıcının GERÇEK açık pozisyonları için risk-optimal ağırlık önerisi.

    Dönüş (ok=True):
      semboller, mevcut_agirlik, esit_agirlik, ters_vol_agirlik, min_var_agirlik,
      yillik_vol (hisse başı), risk (her şema için tahmini yıllık portföy riski),
      en_yuksek_vol, en_dusuk_vol, korelasyon_ciftleri.
    Boş portföy / yetersiz veri → ok=False + dürüst mesaj.
    """
    from portfolio.ozet import acik_pozisyonlar
    from data.access import veri_getir

    pozlar = acik_pozisyonlar(db_path)
    if not pozlar:
        return {"ok": False, "mesaj": "portföy boş"}

    # Mevcut (gerçek) ağırlık = pozisyon piyasa değeri; canlı fiyat yoksa son kapanış,
    # o da yoksa maliyet. Kapanış serilerini de burada topluyoruz.
    seriler: dict[str, pd.Series] = {}
    son_fiyat: dict[str, float] = {}
    veri_yok: list[str] = []

    for sym, p in pozlar.items():
        try:
            fr = veri_getir(db_path, sym, "1y", "1d")
        except Exception:
            fr = None
        kapanis = None
        if fr is not None and getattr(fr, "ok", False) and getattr(fr, "data", None) is not None:
            df = fr.data
            if "Close" in df.columns and len(df) > 0:
                kapanis = df["Close"].astype(float).tail(int(pencere_gun))
        if kapanis is None or kapanis.dropna().shape[0] < 2:
            veri_yok.append(sym)
            son_fiyat[sym] = float(p.get("maliyet") or 0.0)
            continue
        seriler[sym] = kapanis
        son = kapanis.dropna().iloc[-1]
        son_fiyat[sym] = float(son) if np.isfinite(son) else float(p.get("maliyet") or 0.0)

    # Getirisi hesaplanabilen hisseler (en az 2 kapanış) optimizasyona girer.
    kullanilabilir = list(seriler.keys())
    if len(kullanilabilir) < 1:
        return {"ok": False,
                "mesaj": "hiçbir pozisyon için yeterli fiyat geçmişi yok",
                "veri_yok": veri_yok}

    # Ortak tarih ekseninde hizala → günlük getiri matrisi.
    fiyat_df = pd.concat([seriler[s].rename(s) for s in kullanilabilir], axis=1)
    fiyat_df = fiyat_df.sort_index()
    getiri_df = fiyat_df.apply(_gunluk_getiri).dropna(how="any")

    # Hizalama sonrası yeterli ortak gözlem kalmadıysa dürüstçe bırak.
    if getiri_df.shape[0] < 2 or getiri_df.shape[1] < 1:
        return {"ok": False,
                "mesaj": "hisseler için yeterli ortak fiyat geçmişi yok",
                "veri_yok": veri_yok}

    semboller = list(getiri_df.columns)
    n = len(semboller)

    vol = _yillik_vol(getiri_df)
    cov = _kovaryans(getiri_df)

    # Mevcut gerçek ağırlık: piyasa değeri (adet * son fiyat), sadece kullanılabilir
    # hisseler üzerinden normalize (kıyas aynı evrende olsun).
    ham_deger = np.array([float(pozlar[s]["adet"]) * son_fiyat.get(s, 0.0)
                          for s in semboller], dtype=float)
    mevcut_w = _normalize(ham_deger)

    esit_w = _esit_agirlik(n)
    ters_w = _ters_vol_agirlik(vol)
    minvar_w = _min_varyans_agirlik(cov, vol)

    risk = {
        "mevcut": round(_portfoy_vol(mevcut_w, cov), 4),
        "esit": round(_portfoy_vol(esit_w, cov), 4),
        "ters_vol": round(_portfoy_vol(ters_w, cov), 4),
        "min_var": round(_portfoy_vol(minvar_w, cov), 4),
    }

    def _harita(w: np.ndarray) -> dict[str, float]:
        return {s: round(float(x), 4) for s, x in zip(semboller, w)}

    vol_harita = {s: round(float(v), 4) for s, v in zip(semboller, vol)}
    en_yuksek = max(vol_harita, key=vol_harita.get) if vol_harita else None
    en_dusuk = min(vol_harita, key=vol_harita.get) if vol_harita else None

    return {
        "ok": True,
        "semboller": semboller,
        "pencere_gun": int(pencere_gun),
        "gozlem": int(getiri_df.shape[0]),
        "mevcut_agirlik": _harita(mevcut_w),
        "esit_agirlik": _harita(esit_w),
        "ters_vol_agirlik": _harita(ters_w),
        "min_var_agirlik": _harita(minvar_w),
        "yillik_vol": vol_harita,
        "risk": risk,
        "en_yuksek_vol": en_yuksek,
        "en_dusuk_vol": en_dusuk,
        "korelasyon_ciftleri": _korelasyon_ciftleri(getiri_df),
        "veri_yok": veri_yok,
    }


# ── Telegram metni ────────────────────────────────────────────────────────────

def _yuzde(x: float) -> str:
    return f"%{x * 100:.1f}"


def _risk_azalt_notu(mevcut: float, onerilen: float) -> str:
    """Önerinin mevcuda göre riski yüzde kaç azalttığını (ya da artırdığını) döndürür."""
    if mevcut <= 1e-9:
        return ""
    fark = (mevcut - onerilen) / mevcut
    if fark > 0.005:
        return f"riski %{fark * 100:.0f} azaltır"
    if fark < -0.005:
        return f"riski %{-fark * 100:.0f} artırır"
    return "risk benzer"


def optimize_metni(db_path: str) -> str:
    """Telegram için portföy optimizasyon metni. Boş/yetersiz veride dürüst mesaj."""
    r = portfoy_optimizasyon(db_path)
    baslik = "📊 PORTFÖY OPTİMİZASYONU (risk-optimal ağırlık)\n"

    if not r.get("ok"):
        return baslik + "\n" + (r.get("mesaj") or "veri yok") + "."

    semboller = r["semboller"]
    mevcut = r["mevcut_agirlik"]
    minvar = r["min_var_agirlik"]
    ters = r["ters_vol_agirlik"]
    risk = r["risk"]
    vol = r["yillik_vol"]

    satirlar = [baslik.rstrip()]
    satirlar.append(f"\n{len(semboller)} hisse · son {r['pencere_gun']} gün · "
                    f"{r['gozlem']} gözlem\n")

    # Mevcut ve tahmini portföy riski (yıllık volatilite).
    satirlar.append("Tahmini yıllık risk (oynaklık):")
    satirlar.append(f"  Mevcut     : {_yuzde(risk['mevcut'])}")
    satirlar.append(f"  Min-varyans: {_yuzde(risk['min_var'])} "
                    f"({_risk_azalt_notu(risk['mevcut'], risk['min_var'])})")
    satirlar.append(f"  Ters-vol   : {_yuzde(risk['ters_vol'])} "
                    f"({_risk_azalt_notu(risk['mevcut'], risk['ters_vol'])})")

    # Önerilen (min-varyans birincil) ağırlıklar, hisse bazında.
    satirlar.append("\nÖnerilen ağırlık (mevcut → min-varyans / ters-vol):")
    for s in semboller:
        satirlar.append(
            f"  {s}: {_yuzde(mevcut.get(s, 0))} → "
            f"{_yuzde(minvar.get(s, 0))} / {_yuzde(ters.get(s, 0))} "
            f"(yıllık oynaklık {_yuzde(vol.get(s, 0))})")

    if r.get("en_yuksek_vol"):
        satirlar.append(f"\nEn oynak: {r['en_yuksek_vol']} "
                        f"({_yuzde(vol.get(r['en_yuksek_vol'], 0))}) · "
                        f"En sakin: {r['en_dusuk_vol']} "
                        f"({_yuzde(vol.get(r['en_dusuk_vol'], 0))})")

    ciftler = r.get("korelasyon_ciftleri") or []
    if ciftler:
        satirlar.append("\n⚠️ Yüksek korelasyon (çeşitlendirme zayıf):")
        for c in ciftler[:5]:
            satirlar.append(f"  {c['a']} ↔ {c['b']}: {c['korelasyon']}")

    veri_yok = r.get("veri_yok") or []
    if veri_yok:
        satirlar.append("\nℹ️ Fiyat geçmişi yetersiz (analiz dışı): "
                        + ", ".join(veri_yok))

    satirlar.append("\n⚠️ Geçmiş oynaklığa dayalı; gelecek garantisi değil, "
                    "yatırım tavsiyesi değildir.")
    return "\n".join(satirlar)
