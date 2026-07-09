"""SQLite persistence. One file, append-only price_points, cheap to host anywhere."""
import sqlite3

from .models import Offer, Sku
from .ranking import rank

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, set_name TEXT NOT NULL, category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id TEXT NOT NULL REFERENCES products(id),
    store TEXT NOT NULL,
    url TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'AUD',
    in_stock INTEGER NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pp_sku_time ON price_points (sku_id, observed_at DESC);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def upsert_products(conn: sqlite3.Connection, catalog: list[Sku]) -> None:
    conn.executemany(
        "INSERT INTO products (id, name, set_name, category) VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, set_name=excluded.set_name, category=excluded.category",
        [(s.id, s.name, s.set, s.category) for s in catalog],
    )
    conn.commit()


def insert_offers(conn: sqlite3.Connection, offers: list[Offer]) -> None:
    conn.executemany(
        "INSERT INTO price_points (sku_id, store, url, price_cents, currency, in_stock, observed_at) "
        "VALUES (?,?,?,?,?,?,?)",
        [(o.sku_id, o.store, o.url, o.price_cents, o.currency, int(o.in_stock), o.observed_at) for o in offers],
    )
    conn.commit()


def latest_offers(conn: sqlite3.Connection) -> list[dict]:
    """Most recent observation per (sku, store)."""
    rows = conn.execute(
        """
        SELECT p.sku_id, p.store, p.url, p.price_cents, p.currency, p.in_stock, p.observed_at
        FROM price_points p
        JOIN (
            SELECT sku_id, store, MAX(observed_at) AS mx
            FROM price_points GROUP BY sku_id, store
        ) last ON last.sku_id = p.sku_id AND last.store = p.store AND last.mx = p.observed_at
        """
    ).fetchall()
    keys = ["sku_id", "store", "url", "price_cents", "currency", "in_stock", "observed_at"]
    offers = [dict(zip(keys, r)) for r in rows]
    for o in offers:
        o["in_stock"] = bool(o["in_stock"])  # match the gitstore path's JSON booleans
    # Several listings at one store can match one SKU and tie on observed_at;
    # keep the ranked best per (sku, store), same as gitstore.dedupe_run.
    grouped: dict[tuple[str, str], list[dict]] = {}
    for o in offers:
        grouped.setdefault((o["sku_id"], o["store"]), []).append(o)
    return [rank(group) for _, group in sorted(grouped.items())]
