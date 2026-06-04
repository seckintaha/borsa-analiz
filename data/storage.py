"""
SQLite saklama katmanı (Aşama 0).

Her fiyat kaydı, hangi kaynaktan ne zaman alındığıyla birlikte saklanır
(yol haritası Bölüm 6). Boş/eksik veri kaydedilmez.
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
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                symbol     TEXT NOT NULL,
                date       TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     REAL,
                source     TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (symbol, date)
            )
            """
        )
        # Olay gunlugu: ilerideki asamalar (sinyal/karar) icin
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                ts       TEXT NOT NULL,
                symbol   TEXT,
                kind     TEXT,
                detail   TEXT,
                source   TEXT
            )
            """
        )


def save_prices(db_path: str, result: FetchResult) -> int:
    """Bir FetchResult'taki fiyatlari kaydeder. ok=False ise hicbir sey yazmaz."""
    if not result.ok or result.data is None:
        return 0

    df = result.data.copy()
    df.index = pd.to_datetime(df.index)
    rows = []
    for ts, r in df.iterrows():
        rows.append((
            result.symbol,
            ts.strftime("%Y-%m-%d"),
            _f(r.get("Open")), _f(r.get("High")), _f(r.get("Low")),
            _f(r.get("Close")), _f(r.get("Volume")),
            result.source, result.fetched_at,
        ))

    with _connect(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO prices
            (symbol, date, open, high, low, close, volume, source, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
    return len(rows)


def log_event(db_path: str, ts: str, symbol: str, kind: str, detail: str, source: str = "") -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO events (ts, symbol, kind, detail, source) VALUES (?,?,?,?,?)",
            (ts, symbol, kind, detail, source),
        )


def get_prices(db_path: str, symbol: str) -> Optional[pd.DataFrame]:
    with _connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume, source, fetched_at "
            "FROM prices WHERE symbol = ? ORDER BY date",
            conn, params=(symbol.strip().upper(),),
        )
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
