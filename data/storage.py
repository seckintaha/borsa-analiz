"""
SQLite saklama katmanı.

Tablolar:
  prices               — OHLCV geçmişi
  events               — olay günlüğü
  portfolio_islemler   — paper portföy işlemleri (kalıcı)
  kalibrasyon_tahminler— tahmin kayıtları (kalıcı)
  watchlist            — kullanıcının izleme listesi (kalıcı)
"""

from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from typing import Optional

import pandas as pd

from data.fetcher import FetchResult


@contextmanager
def _connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol TEXT NOT NULL, date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                source TEXT NOT NULL, fetched_at TEXT NOT NULL,
                PRIMARY KEY (symbol, date)
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                ts TEXT NOT NULL, symbol TEXT, kind TEXT, detail TEXT, source TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_islemler (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT    NOT NULL,
                yon       TEXT    NOT NULL,
                tarih     TEXT    NOT NULL,
                fiyat     REAL    NOT NULL,
                adet      REAL    NOT NULL,
                tutar     REAL    NOT NULL,
                gerekce   TEXT    DEFAULT '',
                created_at TEXT   DEFAULT (datetime('now'))
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kalibrasyon_tahminler (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT    NOT NULL,
                tarih           TEXT    NOT NULL,
                yon             TEXT    NOT NULL,
                sinyal_tipi     TEXT    NOT NULL,
                ufuk_gun        INTEGER NOT NULL,
                gerceklesen_pct REAL,
                created_at      TEXT    DEFAULT (datetime('now'))
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                sira   INTEGER DEFAULT 0
            )""")


# ── Fiyatlar ────────────────────────────────────────────────────────────────

def save_prices(db_path: str, result: FetchResult) -> int:
    if not result.ok or result.data is None:
        return 0
    df = result.data.copy()
    df.index = pd.to_datetime(df.index)
    rows = [(result.symbol, ts.strftime("%Y-%m-%d"),
             _f(r.get("Open")), _f(r.get("High")), _f(r.get("Low")),
             _f(r.get("Close")), _f(r.get("Volume")),
             result.source, result.fetched_at)
            for ts, r in df.iterrows()]
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices "
            "(symbol,date,open,high,low,close,volume,source,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def get_prices(db_path: str, symbol: str) -> Optional[pd.DataFrame]:
    with _connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date,open,high,low,close,volume,source,fetched_at "
            "FROM prices WHERE symbol=? ORDER BY date",
            conn, params=(symbol.strip().upper(),))
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def log_event(db_path: str, ts: str, symbol: str, kind: str,
              detail: str, source: str = "") -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (ts,symbol,kind,detail,source) VALUES (?,?,?,?,?)",
            (ts, symbol, kind, detail, source))


# ── Portföy ─────────────────────────────────────────────────────────────────

def save_islem(db_path: str, symbol: str, yon: str, tarih: str,
               fiyat: float, adet: float, tutar: float, gerekce: str = "") -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO portfolio_islemler "
            "(symbol,yon,tarih,fiyat,adet,tutar,gerekce) VALUES (?,?,?,?,?,?,?)",
            (symbol.upper(), yon, tarih, fiyat, adet, tutar, gerekce))


def load_portfolio(db_path: str):
    """Tüm işlemleri sırayla oynatarak PaperPortfolio reconstruct eder."""
    from portfolio.paper import PaperPortfolio
    import config
    p = PaperPortfolio(config.INITIAL_CAPITAL, costs=config.COSTS)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol,yon,tarih,fiyat,adet,tutar,gerekce "
            "FROM portfolio_islemler ORDER BY id").fetchall()
    for r in rows:
        try:
            if r["yon"] == "AL":
                p.al(r["symbol"], r["fiyat"], r["tarih"],
                     adet=r["adet"], gerekce=r["gerekce"])
            else:
                p.sat(r["symbol"], r["fiyat"], r["tarih"],
                      adet=r["adet"], gerekce=r["gerekce"])
        except ValueError:
            pass  # Tutarsız kayıt — atla
    return p


def temizle_portfolio(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM portfolio_islemler")


# ── Kalibrasyon ──────────────────────────────────────────────────────────────

def save_tahmin(db_path: str, t) -> int:
    """Tahmin kaydeder, atanan DB id'yi döndürür."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO kalibrasyon_tahminler "
            "(symbol,tarih,yon,sinyal_tipi,ufuk_gun) VALUES (?,?,?,?,?)",
            (t.symbol, t.tarih, t.yon, t.sinyal_tipi, t.ufuk_gun))
        return cur.lastrowid


def update_tahmin_gercek(db_path: str, db_id: int, gercek_pct: float) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE kalibrasyon_tahminler SET gerceklesen_pct=? WHERE id=?",
            (gercek_pct, db_id))


def load_tahminler(db_path: str) -> list:
    """Tüm tahminleri Tahmin nesnesi olarak döndürür (db_id dolu)."""
    from analysis.calibration import Tahmin
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id,symbol,tarih,yon,sinyal_tipi,ufuk_gun,gerceklesen_pct "
            "FROM kalibrasyon_tahminler ORDER BY id").fetchall()
    return [Tahmin(r["symbol"], r["tarih"], r["yon"], r["sinyal_tipi"],
                   r["ufuk_gun"], r["gerceklesen_pct"], db_id=r["id"])
            for r in rows]


def temizle_tahminler(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM kalibrasyon_tahminler")


# ── Watchlist ────────────────────────────────────────────────────────────────

def load_watchlist(db_path: str) -> list[str] | None:
    """DB'deki watchlist'i döndürür. Boşsa None."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol FROM watchlist ORDER BY sira, symbol").fetchall()
    return [r["symbol"] for r in rows] if rows else None


def save_watchlist(db_path: str, symbols: list[str]) -> None:
    """Watchlist'i tamamen yeniden yazar."""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM watchlist")
        conn.executemany(
            "INSERT INTO watchlist (symbol, sira) VALUES (?,?)",
            [(s.strip().upper(), i) for i, s in enumerate(symbols)])


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
