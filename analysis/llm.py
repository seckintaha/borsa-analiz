"""
LLM Sentez (Aşama 6) — deterministik çıktıların dengeli özeti.

İlke (yol haritası): LLM burada bir "kâhin" değil, bir **sentezleyici**dir.
Diğer modüllerin (sinyal, tarihsel oranlar, piyasa rejimi, kalibrasyon, haber)
zaten hesapladığı sayıları alır ve bunları sade, dengeli, ayı senaryolu bir
Türkçe metne çevirir.

Katı kurallar (sistem komutunda da dayatılır):
- YENİ rakam/veri UYDURMAZ; yalnızca verilen bağlamı yorumlar.
- AL/SAT/TUT tavsiyesi VERMEZ.
- Her olumlu noktaya "ama ters giderse" (ayı senaryosu) ekler.
- Belirsizliği ve örnek azlığını saklamaz.

Çalışması için Claude API anahtarı gerekir (ortam değişkeni ANTHROPIC_API_KEY).
Anahtar/kütüphane yoksa sessizce uydurmak yerine ok=False ve açıklama döner.

NOT: Üretilen metin yatırım tavsiyesi değildir.
"""

from __future__ import annotations
from dataclasses import dataclass
import os


SISTEM = """Sen bir borsa analiz aracının "sentez" katmanısın. Görevin, sana \
verilen sayısal/teknik çıktıları sade ve dengeli bir Türkçe özete çevirmek.

KESİN KURALLAR:
1. SADECE sana verilen bağlamdaki bilgileri kullan. Yeni rakam, fiyat, oran ya \
da haber UYDURMA. Bağlamda yoksa "veri yok" de.
2. ASLA "al", "sat", "tut", "yatırım yapın" gibi tavsiye verme. Sen karar \
vermezsin; durumu tarif edersin.
3. Her olumlu gözleme, işlerin neden ters gidebileceğini söyleyen bir "ayı \
senaryosu" ekle.
4. Belirsizliği, örnek azlığını (düşük n), veri eksikliğini açıkça belirt. \
Abartma, kesinlik taslama.
5. Kısa, anlaşılır, maddeler hâlinde yaz. Teknik jargonu sade dille açıkla.
6. Sonunda tek satır hatırlatma: "Bu bir analiz özetidir, yatırım tavsiyesi \
değildir."
"""


@dataclass
class LLMSentez:
    ok: bool
    metin: str = ""
    model: str = ""
    not_: str = ""       # neden çalışmadığının açıklaması


def baglam_metni(baglam: dict) -> str:
    """
    Deterministik modüllerin çıktısından LLM'e verilecek düz metni kurar.
    Saf fonksiyon — ağ/anahtar gerektirmez, test edilebilir.

    baglam beklenen anahtarlar (hepsi opsiyonel):
      symbol, fiyat, sinyal_ozet, sinyal_notlar (list), ayi_senaryosu (list),
      bayraklar (list), rejim (str), tarihsel (list[str]), kalibrasyon (str),
      haber_basliklari (list[str])
    """
    p = []
    if baglam.get("symbol"):
        p.append(f"Hisse: {baglam['symbol']}")
    if baglam.get("fiyat") is not None:
        p.append(f"Son fiyat: {baglam['fiyat']}")
    if baglam.get("sinyal_ozet"):
        p.append(f"Teknik özet: {baglam['sinyal_ozet']}")
    if baglam.get("sinyal_notlar"):
        p.append("Göstergeler:\n- " + "\n- ".join(baglam["sinyal_notlar"]))
    if baglam.get("ayi_senaryosu"):
        p.append("Ayı senaryosu girdileri:\n- " + "\n- ".join(baglam["ayi_senaryosu"]))
    if baglam.get("bayraklar"):
        p.append("Dikkat bayrakları:\n- " + "\n- ".join(baglam["bayraklar"]))
    if baglam.get("rejim"):
        p.append(f"Piyasa rejimi: {baglam['rejim']}")
    if baglam.get("tarihsel"):
        p.append("Tarihsel temel oranlar:\n- " + "\n- ".join(baglam["tarihsel"]))
    if baglam.get("kalibrasyon"):
        p.append(f"Sistemin geçmiş isabeti (kalibrasyon):\n{baglam['kalibrasyon']}")
    if baglam.get("haber_basliklari"):
        p.append("Son haber başlıkları:\n- " + "\n- ".join(baglam["haber_basliklari"]))

    if not p:
        return ""
    return ("Aşağıdaki çıktıları dengeli bir Türkçe özete çevir. "
            "Yeni veri uydurma, tavsiye verme.\n\n" + "\n\n".join(p))


def _anahtar_var_mi(api_key: str | None) -> bool:
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def sentezle(baglam: dict, model: str = "claude-opus-4-8",
             max_tokens: int = 2000, api_key: str | None = None) -> LLMSentez:
    """Bağlamı Claude ile dengeli bir özete çevirir. Anahtar yoksa ok=False."""
    metin = baglam_metni(baglam)
    if not metin:
        return LLMSentez(False, not_="sentez için yeterli bağlam yok")

    try:
        import anthropic
    except ImportError:
        return LLMSentez(False, not_="anthropic kurulu değil (pip install anthropic)")

    if not _anahtar_var_mi(api_key):
        return LLMSentez(
            False,
            not_="Claude API anahtarı yok. Ortam değişkenini ayarlayın: "
                 "export ANTHROPIC_API_KEY=sk-ant-...",
        )

    try:
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        yanit = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SISTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": metin}],
        )
    except anthropic.AuthenticationError:
        return LLMSentez(False, not_="API anahtarı geçersiz (AuthenticationError)")
    except anthropic.RateLimitError:
        return LLMSentez(False, not_="hız sınırı aşıldı, biraz sonra tekrar deneyin")
    except anthropic.APIError as exc:
        return LLMSentez(False, not_=f"Claude API hatası: {exc}")
    except Exception as exc:
        return LLMSentez(False, not_=f"beklenmeyen hata: {exc}")

    parca = next((b.text for b in yanit.content if b.type == "text"), "")
    if not parca:
        return LLMSentez(False, model=model, not_="model boş yanıt döndürdü")
    return LLMSentez(True, metin=parca, model=model)
