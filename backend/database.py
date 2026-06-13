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
    created_at    TEXT NOT NULL,
    custom_ua     TEXT DEFAULT '',
    force_proxy   INTEGER DEFAULT 0,
    last_tested   TEXT DEFAULT ''
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
    is_working      INTEGER DEFAULT 0,
    latency_ms      REAL DEFAULT 0,
    last_tested     TEXT DEFAULT '',
    source_type     TEXT DEFAULT 'hls',
    youtube_video_id TEXT DEFAULT '',
    referer         TEXT DEFAULT '',
    probe_status    TEXT DEFAULT 'untested',
    live_status     TEXT DEFAULT 'unknown',
    probe_method    TEXT DEFAULT '',
    speed_mbps      REAL DEFAULT 0,
    resolution      TEXT DEFAULT '',
    fps             REAL DEFAULT 0,
    video_codec     TEXT DEFAULT '',
    audio_codec     TEXT DEFAULT '',
    requires_headers INTEGER DEFAULT 0,
    requires_proxy_declared INTEGER DEFAULT 0,
    proxy_required_hint INTEGER DEFAULT 0,
    last_success_at TEXT DEFAULT '',
    last_error      TEXT DEFAULT '',
    adapter_provider TEXT DEFAULT '',
    adapter_title   TEXT DEFAULT '',
    probe_meta_json TEXT DEFAULT '{}',
    market_package_id TEXT DEFAULT '',
    market_source_id TEXT DEFAULT '',
    market_channel_id TEXT DEFAULT '',
    market_source_item_id TEXT DEFAULT '',
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_channels_sub ON channels(subscription_id);
CREATE INDEX IF NOT EXISTS idx_channels_name ON channels(name);

CREATE TABLE IF NOT EXISTS epg_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    enabled         INTEGER DEFAULT 1,
    last_fetched_at TEXT DEFAULT '',
    last_status     TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS epg_channels (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        INTEGER NOT NULL REFERENCES epg_sources(id) ON DELETE CASCADE,
    channel_id       TEXT NOT NULL,
    display_names    TEXT NOT NULL,
    normalized_names TEXT NOT NULL,
    UNIQUE(source_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_epg_channels_src_ch ON epg_channels(source_id, channel_id);

CREATE TABLE IF NOT EXISTS epg_programs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES epg_sources(id) ON DELETE CASCADE,
    channel_id  TEXT NOT NULL,
    start       TEXT NOT NULL,
    stop        TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_epg_programs_ch_time ON epg_programs(source_id, channel_id, start, stop);

CREATE TABLE IF NOT EXISTS channel_epg_map (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key   TEXT NOT NULL UNIQUE,
    epg_source_id   INTEGER,
    epg_channel_id  TEXT,
    match_type      TEXT DEFAULT '',
    confidence      INTEGER DEFAULT 0,
    match_status    TEXT DEFAULT 'unmatched',
    match_detail    TEXT DEFAULT '',
    locked          INTEGER DEFAULT 0,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_packages_installed (
    package_id                TEXT PRIMARY KEY,
    market_url                TEXT DEFAULT '',
    installed_subscription_id INTEGER,
    installed_version         TEXT DEFAULT '',
    installed_at              TEXT NOT NULL,
    auto_update               INTEGER DEFAULT 0,
    metadata_json             TEXT DEFAULT '',
    FOREIGN KEY (installed_subscription_id) REFERENCES subscriptions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS market_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key      TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    enabled         INTEGER DEFAULT 1,
    allow_private   INTEGER DEFAULT 0,
    is_builtin      INTEGER DEFAULT 0,
    last_fetched_at TEXT DEFAULT '',
    last_status     TEXT DEFAULT '',
    last_error      TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
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
        # 兼容已有数据库：补充新字段
        for col, typ, default in [
            ('custom_ua', 'TEXT', "''"),
            ('force_proxy', 'INTEGER', '0'),
            ('last_tested', 'TEXT', "''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col} {typ} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # 字段已存在
        for col, typ, default in [
            ('source_type', 'TEXT', "'hls'"),
            ('youtube_video_id', 'TEXT', "''"),
            ('referer', 'TEXT', "''"),
            ('probe_status', 'TEXT', "'untested'"),
            ('live_status', 'TEXT', "'unknown'"),
            ('probe_method', 'TEXT', "''"),
            ('speed_mbps', 'REAL', '0'),
            ('resolution', 'TEXT', "''"),
            ('fps', 'REAL', '0'),
            ('video_codec', 'TEXT', "''"),
            ('audio_codec', 'TEXT', "''"),
            ('requires_headers', 'INTEGER', '0'),
            ('requires_proxy_declared', 'INTEGER', '0'),
            ('proxy_required_hint', 'INTEGER', '0'),
            ('last_success_at', 'TEXT', "''"),
            ('last_error', 'TEXT', "''"),
            ('adapter_provider', 'TEXT', "''"),
            ('adapter_title', 'TEXT', "''"),
            ('probe_meta_json', 'TEXT', "'{}'"),
            ('market_package_id', 'TEXT', "''"),
            ('market_source_id', 'TEXT', "''"),
            ('market_channel_id', 'TEXT', "''"),
            ('market_source_item_id', 'TEXT', "''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE channels ADD COLUMN {col} {typ} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # 字段已存在
        conn.execute("CREATE INDEX IF NOT EXISTS idx_channels_market_pkg ON channels(market_package_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_channels_market_item ON channels(market_package_id, market_source_item_id)")
        for col, typ, default in [
            ('source_key', 'TEXT', "''"),
            ('allow_private', 'INTEGER', '0'),
            ('is_builtin', 'INTEGER', '0'),
            ('last_fetched_at', 'TEXT', "''"),
            ('last_status', 'TEXT', "''"),
            ('last_error', 'TEXT', "''"),
            ('updated_at', 'TEXT', "''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE market_sources ADD COLUMN {col} {typ} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass
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

class DuplicateSubscriptionError(Exception):
    pass


async def add_subscription(title: str, url: str, channel_count: int = 0, custom_ua: str = '', force_proxy: int = 0) -> int:
    def _add():
        conn = _connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            cur = conn.execute(
                "INSERT INTO subscriptions(title, url, channel_count, created_at, custom_ua, force_proxy) VALUES(?, ?, ?, ?, ?, ?)",
                (title, url, channel_count, now, custom_ua, force_proxy),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            if 'subscriptions.url' in str(exc):
                raise DuplicateSubscriptionError(url) from exc
            raise
        finally:
            conn.close()
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


async def get_subscription_by_url(url: str) -> dict | None:
    def _get():
        conn = _connect()
        row = conn.execute("SELECT * FROM subscriptions WHERE url=?", (url,)).fetchone()
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
            "INSERT INTO channels("
            "subscription_id, name, url, logo_url, group_name, tvg_id, tvg_name, "
            "is_working, probe_status, live_status, source_type, youtube_video_id, referer, "
            "market_package_id, market_source_id, market_channel_id, market_source_item_id"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    sub_id,
                    ch['name'],
                    ch['url'],
                    ch.get('logo_url', ''),
                    ch.get('group_name', ''),
                    ch.get('tvg_id', ''),
                    ch.get('tvg_name', ''),
                    0,
                    'untested',
                    'unknown',
                    ch.get('source_type', 'hls'),
                    ch.get('youtube_video_id', ''),
                    ch.get('referer', ''),
                    ch.get('market_package_id', ''),
                    ch.get('market_source_id', ''),
                    ch.get('market_channel_id', ''),
                    ch.get('market_source_item_id', ''),
                )
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
            SELECT c.*, s.title as sub_title, s.custom_ua, s.force_proxy
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


# ── Market install state ──

async def get_market_install(package_id: str) -> dict | None:
    def _get():
        conn = _connect()
        row = conn.execute(
            "SELECT * FROM market_packages_installed WHERE package_id=?",
            (package_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    return await asyncio.to_thread(_get)


async def list_market_installs() -> list[dict]:
    def _list():
        conn = _connect()
        rows = conn.execute("SELECT * FROM market_packages_installed ORDER BY installed_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_list)


async def upsert_market_install(
    package_id: str,
    market_url: str,
    installed_subscription_id: int,
    installed_version: str = '',
    metadata_json: str = '',
    auto_update: int = 0,
):
    def _upsert():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO market_packages_installed(
                package_id, market_url, installed_subscription_id, installed_version,
                installed_at, auto_update, metadata_json
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(package_id) DO UPDATE SET
                market_url=excluded.market_url,
                installed_subscription_id=excluded.installed_subscription_id,
                installed_version=excluded.installed_version,
                installed_at=excluded.installed_at,
                auto_update=excluded.auto_update,
                metadata_json=excluded.metadata_json
            """,
            (package_id, market_url, installed_subscription_id, installed_version, now, auto_update, metadata_json),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_upsert)


async def update_market_install(package_id: str, **kwargs):
    allowed = {"auto_update"}
    values = {key: value for key, value in kwargs.items() if key in allowed}
    if not values:
        return

    def _update():
        conn = _connect()
        sets = ', '.join(f"{k}=?" for k in values)
        conn.execute(f"UPDATE market_packages_installed SET {sets} WHERE package_id=?", (*values.values(), package_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)


async def delete_market_install(package_id: str):
    def _delete():
        conn = _connect()
        conn.execute("DELETE FROM market_packages_installed WHERE package_id=?", (package_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_delete)


# ── Market sources ──

async def list_market_sources() -> list[dict]:
    def _list():
        conn = _connect()
        rows = conn.execute("SELECT * FROM market_sources ORDER BY is_builtin DESC, id ASC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_list)


async def get_market_source(source_id: int) -> dict | None:
    def _get():
        conn = _connect()
        row = conn.execute("SELECT * FROM market_sources WHERE id=?", (source_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    return await asyncio.to_thread(_get)


async def get_market_source_by_key(source_key: str) -> dict | None:
    def _get():
        conn = _connect()
        row = conn.execute("SELECT * FROM market_sources WHERE source_key=?", (source_key,)).fetchone()
        conn.close()
        return dict(row) if row else None
    return await asyncio.to_thread(_get)


async def upsert_market_source(
    *,
    source_key: str,
    name: str,
    url: str,
    enabled: int = 1,
    allow_private: int = 0,
    is_builtin: int = 0,
) -> int:
    def _upsert():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO market_sources(
                source_key, name, url, enabled, allow_private, is_builtin,
                created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                name=excluded.name,
                url=excluded.url,
                enabled=excluded.enabled,
                allow_private=excluded.allow_private,
                is_builtin=excluded.is_builtin,
                updated_at=excluded.updated_at
            """,
            (source_key, name, url, enabled, allow_private, is_builtin, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM market_sources WHERE source_key=?", (source_key,)).fetchone()
        conn.close()
        return int(row["id"] if row else cur.lastrowid)
    return await asyncio.to_thread(_upsert)


async def create_market_source(name: str, url: str, source_key: str, enabled: int = 1, allow_private: int = 0) -> int:
    def _create():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """
            INSERT INTO market_sources(
                source_key, name, url, enabled, allow_private, is_builtin,
                created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (source_key, name, url, enabled, allow_private, now, now),
        )
        conn.commit()
        source_id = cur.lastrowid
        conn.close()
        return source_id
    return await asyncio.to_thread(_create)


async def update_market_source(source_id: int, **kwargs):
    allowed = {"name", "url", "enabled", "allow_private", "last_fetched_at", "last_status", "last_error"}
    values = {key: value for key, value in kwargs.items() if key in allowed}
    if not values:
        return

    def _update():
        conn = _connect()
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        sets = ', '.join(f"{k}=?" for k in values)
        conn.execute(f"UPDATE market_sources SET {sets} WHERE id=?", (*values.values(), source_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)


async def delete_market_source(source_id: int):
    def _delete():
        conn = _connect()
        row = conn.execute("SELECT is_builtin FROM market_sources WHERE id=?", (source_id,)).fetchone()
        if row and row["is_builtin"]:
            conn.close()
            raise ValueError("内置 Market 源不能删除")
        conn.execute("DELETE FROM market_sources WHERE id=?", (source_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_delete)


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


async def update_channel_probe_result(ch_id: int, result: dict):
    def _update():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        probe_status = str(result.get('probe_status') or 'error')
        is_working = 1 if probe_status == 'online' else 0
        last_success_at = now if probe_status == 'online' else str(result.get('last_success_at') or '')
        conn.execute(
            """
            UPDATE channels SET
                is_working=?,
                latency_ms=?,
                last_tested=?,
                probe_status=?,
                live_status=?,
                probe_method=?,
                speed_mbps=?,
                resolution=?,
                fps=?,
                video_codec=?,
                audio_codec=?,
                requires_headers=?,
                requires_proxy_declared=?,
                proxy_required_hint=?,
                last_success_at=COALESCE(NULLIF(?, ''), last_success_at),
                last_error=?,
                adapter_provider=?,
                adapter_title=?,
                probe_meta_json=?
            WHERE id=?
            """,
            (
                is_working,
                float(result.get('latency_ms') or 0),
                now,
                probe_status,
                str(result.get('live_status') or 'unknown'),
                str(result.get('probe_method') or ''),
                float(result.get('speed_mbps') or 0),
                str(result.get('resolution') or ''),
                float(result.get('fps') or 0),
                str(result.get('video_codec') or ''),
                str(result.get('audio_codec') or ''),
                1 if result.get('requires_headers') else 0,
                1 if result.get('requires_proxy_declared') else 0,
                1 if result.get('proxy_required_hint') else 0,
                last_success_at,
                str(result.get('last_error') or ''),
                str(result.get('adapter_provider') or ''),
                str(result.get('adapter_title') or ''),
                str(result.get('probe_meta_json') or '{}'),
                ch_id,
            ),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)


async def reset_channel_statuses(sub_id: int):
    def _reset():
        conn = _connect()
        conn.execute(
            """
            UPDATE channels SET
                is_working=0,
                latency_ms=0,
                last_tested='',
                probe_status='untested',
                live_status='unknown',
                probe_method='',
                speed_mbps=0,
                resolution='',
                fps=0,
                video_codec='',
                audio_codec='',
                requires_headers=0,
                requires_proxy_declared=0,
                proxy_required_hint=0,
                adapter_provider='',
                adapter_title='',
                probe_meta_json='{}',
                last_error=''
            WHERE subscription_id=?
            """,
            (sub_id,),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_reset)


async def reset_channel_statuses_all():
    def _reset():
        conn = _connect()
        conn.execute(
            """
            UPDATE channels SET
                is_working=0,
                latency_ms=0,
                last_tested='',
                probe_status='untested',
                live_status='unknown',
                probe_method='',
                speed_mbps=0,
                resolution='',
                fps=0,
                video_codec='',
                audio_codec='',
                requires_headers=0,
                requires_proxy_declared=0,
                proxy_required_hint=0,
                adapter_provider='',
                adapter_title='',
                probe_meta_json='{}',
                last_error=''
            """
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_reset)


# ── EPG ──

async def add_epg_source(name: str, url: str) -> int:
    def _add():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO epg_sources(name, url, created_at, updated_at) VALUES(?, ?, ?, ?)",
            (name, url, now, now),
        )
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        return sid
    return await asyncio.to_thread(_add)


async def get_epg_sources() -> list[dict]:
    def _get():
        conn = _connect()
        rows = conn.execute("SELECT * FROM epg_sources ORDER BY id").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def delete_epg_source(source_id: int):
    def _delete():
        conn = _connect()
        conn.execute("DELETE FROM epg_sources WHERE id=?", (source_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_delete)


async def update_epg_source(source_id: int, **kwargs):
    def _update():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        kwargs['updated_at'] = now
        sets = ', '.join(f"{k}=?" for k in kwargs)
        conn.execute(f"UPDATE epg_sources SET {sets} WHERE id=?", (*kwargs.values(), source_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)


async def replace_epg_channels(source_id: int, channels: list[dict]):
    def _replace():
        conn = _connect()
        conn.execute("DELETE FROM epg_channels WHERE source_id=?", (source_id,))
        conn.executemany(
            "INSERT INTO epg_channels(source_id, channel_id, display_names, normalized_names) VALUES(?, ?, ?, ?)",
            [(source_id, ch['channel_id'], ch['display_names'], ch['normalized_names']) for ch in channels],
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_replace)


async def replace_epg_programs(source_id: int, programs: list[dict]):
    def _replace():
        conn = _connect()
        conn.execute("DELETE FROM epg_programs WHERE source_id=?", (source_id,))
        conn.executemany(
            "INSERT INTO epg_programs(source_id, channel_id, start, stop, title, description) VALUES(?, ?, ?, ?, ?, ?)",
            [(source_id, p['channel_id'], p['start'], p['stop'], p['title'], p.get('description', '')) for p in programs],
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_replace)


async def get_epg_channels(source_id: int) -> list[dict]:
    def _get():
        conn = _connect()
        rows = conn.execute("SELECT * FROM epg_channels WHERE source_id=?", (source_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def get_epg_programs(source_id: int, channel_id: str, start_after: str = '', start_before: str = '') -> list[dict]:
    def _get():
        conn = _connect()
        query = "SELECT * FROM epg_programs WHERE source_id=? AND channel_id=?"
        params: list = [source_id, channel_id]
        if start_after:
            query += " AND stop >= ?"
            params.append(start_after)
        if start_before:
            query += " AND start <= ?"
            params.append(start_before)
        query += " ORDER BY start"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def batch_get_current_programs(canonical_keys: list[str]) -> dict:
    """批量查当前节目：返回 {canonical_key: {current, next}} 或 {}"""
    def _get():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        result = {}
        for key in canonical_keys:
            row = conn.execute(
                "SELECT epg_source_id, epg_channel_id FROM channel_epg_map WHERE canonical_key=? AND match_status IN ('matched','locked')",
                (key,),
            ).fetchone()
            if not row:
                result[key] = None
                continue
            sid = row['epg_source_id']
            cid = row['epg_channel_id']
            current = conn.execute(
                "SELECT title, start, stop, description FROM epg_programs WHERE source_id=? AND channel_id=? AND start <= ? AND stop > ? ORDER BY start LIMIT 1",
                (sid, cid, now, now),
            ).fetchone()
            if current:
                c = dict(current)
                c['start_ts'] = c['start']
                c['stop_ts'] = c['stop']
                now_ts = datetime.now(timezone.utc)
                try:
                    start_dt = datetime.fromisoformat(c['start'])
                    stop_dt = datetime.fromisoformat(c['stop'])
                    total = (stop_dt - start_dt).total_seconds()
                    elapsed = (now_ts - start_dt).total_seconds()
                    c['progress'] = max(0, min(1, elapsed / total)) if total > 0 else 0
                    c['remaining_minutes'] = max(0, int((stop_dt - now_ts).total_seconds() / 60))
                except Exception:
                    c['progress'] = 0
                    c['remaining_minutes'] = 0
            next_prog = conn.execute(
                "SELECT title, start, stop FROM epg_programs WHERE source_id=? AND channel_id=? AND start >= ? ORDER BY start LIMIT 1",
                (sid, cid, now),
            ).fetchone()
            result[key] = {
                'current': dict(current) if current else None,
                'next': dict(next_prog) if next_prog else None,
            }
        conn.close()
        return result
    return await asyncio.to_thread(_get)


async def get_channel_epg_map(key: str = '') -> dict | None:
    def _get():
        conn = _connect()
        row = conn.execute("SELECT * FROM channel_epg_map WHERE canonical_key=?", (key,)).fetchone()
        conn.close()
        return dict(row) if row else None
    return await asyncio.to_thread(_get)


async def get_all_channel_epg_maps() -> list[dict]:
    def _get():
        conn = _connect()
        rows = conn.execute("SELECT * FROM channel_epg_map ORDER BY canonical_key").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def upsert_channel_epg_map(key: str, **kwargs):
    def _upsert():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        kwargs['updated_at'] = now
        cols = ', '.join(kwargs.keys())
        placeholders = ', '.join('?' for _ in kwargs)
        sets = ', '.join(f"{k}=excluded.{k}" for k in kwargs)
        conn.execute(
            f"INSERT INTO channel_epg_map(canonical_key, {cols}) VALUES(?, {placeholders}) ON CONFLICT(canonical_key) DO UPDATE SET {sets}",
            (key, *kwargs.values()),
        )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_upsert)
