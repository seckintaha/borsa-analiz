"""
Güvenlik testleri.

Kapsam:
- RSS/haber: yalnızca http/https adreslerine izin (SSRF / yerel dosya koruması),
  güvenli XML ayrıştırma (entity-bomb), kötücül link enjeksiyonu engeli.
- SQLite: parametreli sorgular sayesinde SQL enjeksiyonuna kapalı.

Hiçbiri internet gerektirmez.
"""

import pytest

from analysis import news
from data.storage import init_db, save_watchlist, load_watchlist, get_prices


# ── RSS / haber güvenliği ─────────────────────────────────────────────────────

def test_url_semasi_izin():
    assert news._http_url_mu("https://ornek.test/feed.xml") is True
    assert news._http_url_mu("http://ornek.test/feed.xml") is True


def test_url_semasi_engel():
    assert news._http_url_mu("file:///etc/passwd") is False
    assert news._http_url_mu("ftp://ornek.test/x") is False
    assert news._http_url_mu("javascript:alert(1)") is False
    assert news._http_url_mu("") is False
    assert news._http_url_mu("/yerel/dosya") is False


def test_rss_oku_file_semasini_reddeder():
    # Ağ çağrısı yapılmadan, şema kontrolünde durur
    r = news.rss_oku("file:///etc/passwd")
    assert r.ok is False
    assert "güvenlik" in r.not_


def test_rss_entity_bomb_engellenir_defusedxml_varsa():
    # defusedxml kuruluysa "billion laughs" tarzı saldırı reddedilmeli
    pytest.importorskip("defusedxml")
    bomba = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">
    ]>
    <rss><channel><item><title>&lol2;</title></item></channel></rss>"""
    with pytest.raises(Exception):
        news._rss_ayristir(bomba, "kotucul", limit=5)


def test_kotucul_link_panelde_render_edilmez():
    # Panel yalnızca http/https linkleri tıklanabilir yapar
    assert news._http_url_mu("javascript:alert(document.cookie)") is False


# ── SQLite enjeksiyon güvenliği ───────────────────────────────────────────────

def test_watchlist_sql_enjeksiyonuna_kapali(tmp_path):
    db = str(tmp_path / "g.db")
    init_db(db)
    kotucul = "'; DROP TABLE prices; --"
    save_watchlist(db, ["AAA.IS", kotucul])

    # Tablolar hâlâ ayakta (enjeksiyon çalışmadı) — parametreli sorgu
    wl = load_watchlist(db)
    assert wl is not None and len(wl) == 2
    # prices tablosu silinmedi: sorgu hatasız çalışmalı (boş → None)
    assert get_prices(db, "AAA.IS") is None
