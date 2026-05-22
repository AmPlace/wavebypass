import asyncio
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get('WAVEBYPASS_DB_PATH', os.path.join(os.path.dirname(__file__), 'data', 'wavebypass.db'))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    channel_count INTEGER DEFAULT 0,
    valid         INTEGER DEFAULT 1,
    last_updated  TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    logo_url        TEXT DEFAULT '',
    group_name      TEXT DEFAULT '',
    tvg_id          TEXT DEFAULT '',
    tvg_name        TEXT DEFAULT '',
    is_working      INTEGER DEFAULT -1,
    latency_ms      REAL DEFAULT 0,
    last_tested     TEXT DEFAULT '',
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_channels_sub ON channels(subscription_id);
CREATE INDEX IF NOT EXISTS idx_channels_name ON channels(name);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


async def initialize():
    def _init():
        conn = _connect()
        conn.executescript(_SCHEMA)
        conn.close()
    await asyncio.to_thread(_init)


# ── Settings ──

async def get_setting(key: str, default: str = '') -> str:
    def _get():
        conn = _connect()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    return await asyncio.to_thread(_get)


async def set_setting(key: str, value: str):
    def _set():
        conn = _connect()
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)


# ── Subscriptions ──

async def add_subscription(title: str, url: str, channel_count: int = 0) -> int:
    def _add():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO subscriptions(title, url, channel_count, created_at) VALUES(?, ?, ?, ?)",
            (title, url, channel_count, now),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid
    return await asyncio.to_thread(_add)


async def get_subscriptions() -> list[dict]:
    def _get():
        conn = _connect()
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def get_subscription(sub_id: int) -> dict | None:
    def _get():
        conn = _connect()
        row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    return await asyncio.to_thread(_get)


async def update_subscription(sub_id: int, **kwargs):
    def _update():
        conn = _connect()
        sets = ', '.join(f"{k}=?" for k in kwargs)
        conn.execute(f"UPDATE subscriptions SET {sets} WHERE id=?", (*kwargs.values(), sub_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)


async def delete_subscription(sub_id: int):
    def _delete():
        conn = _connect()
        conn.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_delete)


# ── Channels ──

async def add_channels_bulk(sub_id: int, channels: list[dict]):
    def _add():
        conn = _connect()
        conn.execute("DELETE FROM channels WHERE subscription_id=?", (sub_id,))
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT INTO channels(subscription_id, name, url, logo_url, group_name, tvg_id, tvg_name) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            [
                (sub_id, ch['name'], ch['url'], ch.get('logo_url', ''), ch.get('group_name', ''), ch.get('tvg_id', ''), ch.get('tvg_name', ''))
                for ch in channels
            ],
        )
        conn.execute(
            "UPDATE subscriptions SET channel_count=?, last_updated=? WHERE id=?",
            (len(channels), now, sub_id),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_add)


async def get_channels(sub_id: int, group: str = '', search: str = '') -> list[dict]:
    def _get():
        conn = _connect()
        query = "SELECT * FROM channels WHERE subscription_id=?"
        params: list = [sub_id]
        if group:
            query += " AND group_name=?"
            params.append(group)
        if search:
            query += " AND name LIKE ?"
            params.append(f"%{search}%")
        query += " ORDER BY id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def get_channel_groups(sub_id: int) -> list[str]:
    def _get():
        conn = _connect()
        rows = conn.execute(
            "SELECT DISTINCT group_name FROM channels WHERE subscription_id=? AND group_name != '' ORDER BY group_name",
            (sub_id,),
        ).fetchall()
        conn.close()
        return [r['group_name'] for r in rows]
    return await asyncio.to_thread(_get)


async def get_aggregated_channels(group: str = '', search: str = '') -> list[dict]:
    """跨所有订阅源聚合频道：按清洗名去重，每个频道保留所有可用链接"""
    def _get():
        conn = _connect()
        query = """
            SELECT c.*, s.title as sub_title
            FROM channels c
            JOIN subscriptions s ON c.subscription_id = s.id
        """
        params: list = []
        where = []
        if group:
            where.append("c.group_name = ?")
            params.append(group)
        if search:
            where.append("c.name LIKE ?")
            params.append(f"%{search}%")
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY c.name, c.is_working DESC, c.latency_ms ASC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def get_all_channel_groups() -> list[str]:
    def _get():
        conn = _connect()
        rows = conn.execute(
            "SELECT DISTINCT group_name FROM channels WHERE group_name != '' ORDER BY group_name"
        ).fetchall()
        conn.close()
        return [r['group_name'] for r in rows]
    return await asyncio.to_thread(_get)


async def update_channel_status(ch_id: int, is_working: int, latency_ms: float = 0):
    def _update():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE channels SET is_working=?, latency_ms=?, last_tested=? WHERE id=?",
            (is_working, latency_ms, now, ch_id),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)


async def reset_channel_statuses(sub_id: int):
    def _reset():
        conn = _connect()
        conn.execute(
            "UPDATE channels SET is_working=-1, latency_ms=0, last_tested='' WHERE subscription_id=?",
            (sub_id,),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_reset)


async def reset_channel_statuses_all():
    def _reset():
        conn = _connect()
        conn.execute("UPDATE channels SET is_working=-1, latency_ms=0, last_tested=''")
        conn.commit()
        conn.close()
    await asyncio.to_thread(_reset)
