import asyncio
import sqlite3
import os
import json
import uuid
from datetime import datetime, timezone


AUTOMATION_ERROR_MAX_LENGTH = 2048
EPG_ERROR_MAX_LENGTH = 1024
AUTOMATION_STATUSES = {
    'never_run',
    'running',
    'success',
    'partial',
    'failed',
    'cancelled',
    'interrupted',
}
AUTOMATION_FINAL_STATUSES = AUTOMATION_STATUSES - {'never_run', 'running'}
MARKET_VERSION_STATUSES = {'same', 'upgrade', 'downgrade', 'different', 'unknown'}
MARKET_UPDATE_FINAL_STATUSES = {'success', 'failed', 'cancelled', 'interrupted'}
MARKET_AUTOMATION_TASK_ID = 'market_auto_update'
MARKET_AUTOMATION_CONFLICT_GROUP = 'market'
MARKET_AUTOMATION_INTERVAL_SECONDS = 86400

DB_PATH_RAW = (
    os.environ.get('WAVEFLOW_DB_PATH')
    or os.path.join(os.path.dirname(__file__), 'data', 'waveflow.db')
)
# 转为 file: URI（允许 :memory: 多连接共享，以及正常路径）
if DB_PATH_RAW == ":memory:":
    DB_PATH = "file:waveflow?mode=memory&cache=shared"
else:
    DB_PATH = DB_PATH_RAW

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER
);

CREATE TABLE IF NOT EXISTS automation_task_config (
    task_id          TEXT PRIMARY KEY,
    conflict_group   TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    interval_seconds INTEGER NOT NULL CHECK(interval_seconds > 0),
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_task_state (
    task_id          TEXT PRIMARY KEY,
    conflict_group   TEXT NOT NULL,
    task_type        TEXT DEFAULT '',
    run_token        TEXT DEFAULT '',
    last_started_at  TEXT DEFAULT '',
    last_finished_at TEXT DEFAULT '',
    last_status      TEXT NOT NULL DEFAULT 'never_run'
                     CHECK(last_status IN (
                         'never_run', 'running', 'success', 'partial',
                         'failed', 'cancelled', 'interrupted'
                     )),
    checked_count    INTEGER NOT NULL DEFAULT 0 CHECK(checked_count >= 0),
    updated_count    INTEGER NOT NULL DEFAULT 0 CHECK(updated_count >= 0),
    skipped_count    INTEGER NOT NULL DEFAULT 0 CHECK(skipped_count >= 0),
    failed_count     INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
    last_error       TEXT DEFAULT '',
    FOREIGN KEY (task_id) REFERENCES automation_task_config(task_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_running_conflict_group
ON automation_task_state(conflict_group)
WHERE last_status = 'running';

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
    custom_ua       TEXT DEFAULT '',
    force_proxy     INTEGER DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS iptv_logical_channels (
    id            TEXT PRIMARY KEY,
    canonical_key TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK(status IN ('active', 'orphaned', 'split_conflict', 'merge_conflict')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_iptv_logical_channels_key
ON iptv_logical_channels(canonical_key);
CREATE INDEX IF NOT EXISTS idx_iptv_logical_channels_status
ON iptv_logical_channels(status);

CREATE TABLE IF NOT EXISTS iptv_logical_channel_members (
    logical_channel_id    TEXT NOT NULL,
    channel_id            INTEGER NOT NULL UNIQUE,
    membership_reason     TEXT NOT NULL DEFAULT 'normalized_name',
    membership_confidence INTEGER NOT NULL DEFAULT 100
                          CHECK(membership_confidence BETWEEN 0 AND 100),
    variant_type          TEXT NOT NULL DEFAULT 'unknown'
                          CHECK(variant_type IN (
                              'unknown', 'standard', 'hd', '4k', 'delayed',
                              'region', 'international'
                          )),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    PRIMARY KEY(logical_channel_id, channel_id),
    FOREIGN KEY(logical_channel_id) REFERENCES iptv_logical_channels(id) ON DELETE CASCADE,
    FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_iptv_logical_members_logical
ON iptv_logical_channel_members(logical_channel_id);
CREATE INDEX IF NOT EXISTS idx_iptv_logical_members_channel
ON iptv_logical_channel_members(channel_id);

CREATE TABLE IF NOT EXISTS epg_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    enabled         INTEGER DEFAULT 1,
    revision        INTEGER NOT NULL DEFAULT 1,
    last_fetched_at TEXT DEFAULT '',
    last_attempt_at TEXT DEFAULT '',
    last_success_at TEXT DEFAULT '',
    last_status     TEXT DEFAULT '',
    last_error      TEXT DEFAULT '',
    channel_count   INTEGER NOT NULL DEFAULT 0,
    programme_count INTEGER NOT NULL DEFAULT 0,
    data_start_at   TEXT DEFAULT '',
    data_end_at     TEXT DEFAULT '',
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
    last_checked_at           TEXT DEFAULT '',
    remote_version            TEXT DEFAULT '',
    version_status            TEXT DEFAULT 'unknown',
    last_update_started_at    TEXT DEFAULT '',
    last_update_finished_at   TEXT DEFAULT '',
    last_update_status        TEXT DEFAULT 'never_run',
    last_update_error         TEXT DEFAULT '',
    last_update_run_token     TEXT DEFAULT '',
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

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revoked_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS media_credentials (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    scopes_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT DEFAULT '',
    last_used_at TEXT DEFAULT '',
    revoked_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_media_credentials_token ON media_credentials(token_hash);

-- 应用级密钥（用途隔离的对称根密钥）。
-- 仅持久化「无法从环境变量提供」时自动生成的回退值。
-- 不通过普通 app_settings 暴露，不允许通过设置面板修改。
CREATE TABLE IF NOT EXISTS app_secrets (
    name       TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_identifier(value, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{field} 必须是字符串')
    normalized = value.strip()
    if not normalized:
        raise ValueError(f'{field} 不能为空')
    return normalized


def _normalize_interval_seconds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError('interval_seconds 必须是正整数')
    if value <= 0:
        raise ValueError('interval_seconds 必须大于 0')
    return value


def _normalize_enabled(value) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in {0, 1}:
        return value
    raise ValueError('enabled 必须是布尔值或 0/1')


def _normalize_timestamp(value: str | None, field: str) -> str:
    if value is None:
        return _utc_now()
    if not isinstance(value, str):
        raise TypeError(f'{field} 必须是 UTC ISO 时间字符串')
    normalized = value.strip()
    if not normalized:
        raise ValueError(f'{field} 不能为空')
    try:
        parsed = datetime.fromisoformat(normalized.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field} 必须是有效的 ISO 时间字符串') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{field} 必须包含时区')
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_error(value: str | None) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise TypeError('error 必须是字符串')
    return value.replace('\x00', '').strip()[:AUTOMATION_ERROR_MAX_LENGTH]


def _normalize_count(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f'{field} 必须是非负整数')
    if value < 0:
        raise ValueError(f'{field} 不能小于 0')
    return value


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
            ('custom_ua', 'TEXT', "''"),
            ('force_proxy', 'INTEGER', '0'),
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
            ('revision', 'INTEGER', '1'),
            ('last_attempt_at', 'TEXT', "''"),
            ('last_success_at', 'TEXT', "''"),
            ('last_error', 'TEXT', "''"),
            ('channel_count', 'INTEGER', '0'),
            ('programme_count', 'INTEGER', '0'),
            ('data_start_at', 'TEXT', "''"),
            ('data_end_at', 'TEXT', "''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE epg_sources ADD COLUMN {col} {typ} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass
        conn.execute("UPDATE epg_sources SET revision=1 WHERE revision IS NULL OR revision < 1")
        conn.execute(
            """
            UPDATE epg_sources
            SET last_attempt_at=last_fetched_at
            WHERE last_attempt_at='' AND last_fetched_at<>''
            """
        )
        conn.execute(
            """
            UPDATE epg_sources
            SET last_success_at=last_fetched_at,
                last_status='success'
            WHERE last_success_at='' AND last_fetched_at<>'' AND last_status='ok'
            """
        )
        conn.execute(
            """
            UPDATE epg_sources
            SET channel_count=(
                    SELECT COUNT(*) FROM epg_channels WHERE epg_channels.source_id=epg_sources.id
                ),
                programme_count=(
                    SELECT COUNT(*) FROM epg_programs WHERE epg_programs.source_id=epg_sources.id
                ),
                data_start_at=COALESCE((
                    SELECT MIN(start) FROM epg_programs WHERE epg_programs.source_id=epg_sources.id
                ), ''),
                data_end_at=COALESCE((
                    SELECT MAX(stop) FROM epg_programs WHERE epg_programs.source_id=epg_sources.id
                ), '')
            WHERE channel_count=0 AND programme_count=0
            """
        )
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
        for col, typ, default in [
            ('last_checked_at', 'TEXT', "''"),
            ('remote_version', 'TEXT', "''"),
            ('version_status', 'TEXT', "'unknown'"),
            ('last_update_started_at', 'TEXT', "''"),
            ('last_update_finished_at', 'TEXT', "''"),
            ('last_update_status', 'TEXT', "'never_run'"),
            ('last_update_error', 'TEXT', "''"),
            ('last_update_run_token', 'TEXT', "''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE market_packages_installed ADD COLUMN {col} {typ} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass
        now = _utc_now()
        conn.execute(
            """
            INSERT OR IGNORE INTO automation_task_config(
                task_id, conflict_group, enabled, interval_seconds, updated_at
            ) VALUES(?, ?, 1, ?, ?)
            """,
            (
                MARKET_AUTOMATION_TASK_ID,
                MARKET_AUTOMATION_CONFLICT_GROUP,
                MARKET_AUTOMATION_INTERVAL_SECONDS,
                now,
            ),
        )
        market_config = conn.execute(
            "SELECT conflict_group FROM automation_task_config WHERE task_id=?",
            (MARKET_AUTOMATION_TASK_ID,),
        ).fetchone()
        conn.execute(
            """
            INSERT OR IGNORE INTO automation_task_state(task_id, conflict_group, last_status)
            VALUES(?, ?, 'never_run')
            """,
            (MARKET_AUTOMATION_TASK_ID, market_config['conflict_group']),
        )
        conn.commit()
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


async def get_app_settings() -> dict:
    def _get():
        conn = _connect()
        try:
            rows = conn.execute("SELECT key, value_json FROM app_settings").fetchall()
        except sqlite3.OperationalError:
            conn.close()
            return {}
        conn.close()
        result = {}
        for row in rows:
            try:
                result[row['key']] = json.loads(row['value_json'])
            except json.JSONDecodeError:
                continue
        return result
    return await asyncio.to_thread(_get)


async def set_app_settings(values: dict, updated_by: int | None = None) -> None:
    def _set():
        conn = _connect()
        now = datetime.now(timezone.utc).isoformat()
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO app_settings(key, value_json, updated_at, updated_by)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json=excluded.value_json,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by
                """,
                (key, json.dumps(value, ensure_ascii=False), now, updated_by),
            )
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)


# ── Automation task persistence ──

async def ensure_automation_task_config(
    task_id: str,
    conflict_group: str,
    enabled: bool | int,
    interval_seconds: int,
) -> dict:
    task_id = _normalize_identifier(task_id, 'task_id')
    conflict_group = _normalize_identifier(conflict_group, 'conflict_group')
    enabled_value = _normalize_enabled(enabled)
    interval_value = _normalize_interval_seconds(interval_seconds)

    def _ensure():
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO automation_task_config(
                        task_id, conflict_group, enabled, interval_seconds, updated_at
                    ) VALUES(?, ?, ?, ?, ?)
                    """,
                    (task_id, conflict_group, enabled_value, interval_value, _utc_now()),
                )
                config = conn.execute(
                    "SELECT * FROM automation_task_config WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO automation_task_state(task_id, conflict_group, last_status)
                    VALUES(?, ?, 'never_run')
                    """,
                    (task_id, config['conflict_group']),
                )
                return dict(config)
        finally:
            conn.close()

    return await asyncio.to_thread(_ensure)


async def get_automation_task_config(task_id: str) -> dict | None:
    task_id = _normalize_identifier(task_id, 'task_id')

    def _get():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM automation_task_config WHERE task_id=?",
                (task_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_get)


async def list_automation_task_configs() -> list[dict]:
    def _list():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM automation_task_config ORDER BY task_id"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_list)


async def update_automation_task_config(
    task_id: str,
    *,
    enabled: bool | int | None = None,
    interval_seconds: int | None = None,
) -> dict | None:
    task_id = _normalize_identifier(task_id, 'task_id')
    updates = {}
    if enabled is not None:
        updates['enabled'] = _normalize_enabled(enabled)
    if interval_seconds is not None:
        updates['interval_seconds'] = _normalize_interval_seconds(interval_seconds)
    if not updates:
        return await get_automation_task_config(task_id)
    updates['updated_at'] = _utc_now()

    def _update():
        conn = _connect()
        try:
            with conn:
                assignments = ', '.join(f'{key}=?' for key in updates)
                cursor = conn.execute(
                    f"UPDATE automation_task_config SET {assignments} WHERE task_id=?",
                    (*updates.values(), task_id),
                )
                if cursor.rowcount != 1:
                    return None
                row = conn.execute(
                    "SELECT * FROM automation_task_config WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                return dict(row)
        finally:
            conn.close()

    return await asyncio.to_thread(_update)


async def get_automation_task_state(task_id: str) -> dict | None:
    task_id = _normalize_identifier(task_id, 'task_id')

    def _get():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM automation_task_state WHERE task_id=?",
                (task_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_get)


async def get_automation_conflict_group_state(conflict_group: str) -> dict | None:
    conflict_group = _normalize_identifier(conflict_group, 'conflict_group')

    def _get():
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM automation_task_state
                WHERE conflict_group=? AND last_status='running'
                ORDER BY last_started_at DESC
                LIMIT 1
                """,
                (conflict_group,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_get)


async def claim_automation_task(
    *,
    task_id: str,
    conflict_group: str,
    task_type: str,
    run_token: str,
    started_at: str | None = None,
) -> dict:
    task_id = _normalize_identifier(task_id, 'task_id')
    conflict_group = _normalize_identifier(conflict_group, 'conflict_group')
    task_type = _normalize_identifier(task_type, 'task_type')
    run_token = _normalize_identifier(run_token, 'run_token')
    started_at_value = _normalize_timestamp(started_at, 'started_at')

    def _claim():
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            config = conn.execute(
                "SELECT * FROM automation_task_config WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if config is None:
                raise KeyError(f'未知自动任务: {task_id}')
            if config['conflict_group'] != conflict_group:
                raise ValueError('conflict_group 与任务配置不一致')

            current = conn.execute(
                """
                SELECT * FROM automation_task_state
                WHERE conflict_group=? AND last_status='running'
                LIMIT 1
                """,
                (conflict_group,),
            ).fetchone()
            if current is not None:
                conn.rollback()
                return {'claimed': False, 'current': dict(current)}

            try:
                conn.execute(
                    """
                    INSERT INTO automation_task_state(
                        task_id, conflict_group, task_type, run_token,
                        last_started_at, last_finished_at, last_status,
                        checked_count, updated_count, skipped_count, failed_count,
                        last_error
                    ) VALUES(?, ?, ?, ?, ?, '', 'running', 0, 0, 0, 0, '')
                    ON CONFLICT(task_id) DO UPDATE SET
                        conflict_group=excluded.conflict_group,
                        task_type=excluded.task_type,
                        run_token=excluded.run_token,
                        last_started_at=excluded.last_started_at,
                        last_finished_at='',
                        last_status='running',
                        checked_count=0,
                        updated_count=0,
                        skipped_count=0,
                        failed_count=0,
                        last_error=''
                    """,
                    (task_id, conflict_group, task_type, run_token, started_at_value),
                )
            except sqlite3.IntegrityError:
                current = conn.execute(
                    """
                    SELECT * FROM automation_task_state
                    WHERE conflict_group=? AND last_status='running'
                    LIMIT 1
                    """,
                    (conflict_group,),
                ).fetchone()
                conn.rollback()
                if current is not None:
                    return {'claimed': False, 'current': dict(current)}
                raise

            state = conn.execute(
                "SELECT * FROM automation_task_state WHERE task_id=?",
                (task_id,),
            ).fetchone()
            conn.commit()
            return {'claimed': True, 'state': dict(state)}
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_claim)


async def update_automation_task_progress(
    task_id: str,
    run_token: str,
    *,
    checked_count: int | None = None,
    updated_count: int | None = None,
    skipped_count: int | None = None,
    failed_count: int | None = None,
    error: str | None = None,
) -> bool:
    task_id = _normalize_identifier(task_id, 'task_id')
    run_token = _normalize_identifier(run_token, 'run_token')
    updates = {}
    for field, value in (
        ('checked_count', checked_count),
        ('updated_count', updated_count),
        ('skipped_count', skipped_count),
        ('failed_count', failed_count),
    ):
        if value is not None:
            updates[field] = _normalize_count(value, field)
    if error is not None:
        updates['last_error'] = _normalize_error(error)
    if not updates:
        return False

    def _update():
        conn = _connect()
        try:
            with conn:
                assignments = ', '.join(f'{key}=?' for key in updates)
                cursor = conn.execute(
                    f"""
                    UPDATE automation_task_state SET {assignments}
                    WHERE task_id=? AND run_token=? AND last_status='running'
                    """,
                    (*updates.values(), task_id, run_token),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_update)


async def complete_automation_task(
    task_id: str,
    run_token: str,
    *,
    status: str,
    finished_at: str | None = None,
    checked_count: int | None = None,
    updated_count: int | None = None,
    skipped_count: int | None = None,
    failed_count: int | None = None,
    error: str | None = '',
) -> bool:
    task_id = _normalize_identifier(task_id, 'task_id')
    run_token = _normalize_identifier(run_token, 'run_token')
    if status not in AUTOMATION_FINAL_STATUSES:
        raise ValueError(f'非法自动任务完成状态: {status}')
    updates = {
        'last_finished_at': _normalize_timestamp(finished_at, 'finished_at'),
        'last_status': status,
        'last_error': _normalize_error(error),
    }
    for field, value in (
        ('checked_count', checked_count),
        ('updated_count', updated_count),
        ('skipped_count', skipped_count),
        ('failed_count', failed_count),
    ):
        if value is not None:
            updates[field] = _normalize_count(value, field)

    def _complete():
        conn = _connect()
        try:
            with conn:
                assignments = ', '.join(f'{key}=?' for key in updates)
                cursor = conn.execute(
                    f"""
                    UPDATE automation_task_state SET {assignments}
                    WHERE task_id=? AND run_token=? AND last_status='running'
                    """,
                    (*updates.values(), task_id, run_token),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_complete)


async def recover_interrupted_automation_tasks(
    *,
    finished_at: str | None = None,
    error: str | None = '服务启动时检测到上次自动任务运行被中断',
) -> int:
    finished_at_value = _normalize_timestamp(finished_at, 'finished_at')
    error_value = _normalize_error(error)

    def _recover():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE automation_task_state SET
                        last_finished_at=?,
                        last_status='interrupted',
                        last_error=?
                    WHERE last_status='running'
                    """,
                    (finished_at_value, error_value),
                )
                return cursor.rowcount
        finally:
            conn.close()

    return await asyncio.to_thread(_recover)


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

_CHANNEL_IDENTITY_FIELDS = (
    'url',
    'source_type',
    'custom_ua',
    'referer',
    'force_proxy',
    'requires_proxy_declared',
    'adapter_provider',
    'market_package_id',
    'market_source_id',
    'market_channel_id',
    'market_source_item_id',
)

_CHANNEL_CONFIG_FIELDS = (
    'name',
    'url',
    'logo_url',
    'group_name',
    'tvg_id',
    'tvg_name',
    'source_type',
    'youtube_video_id',
    'referer',
    'custom_ua',
    'force_proxy',
    'requires_headers',
    'requires_proxy_declared',
    'proxy_required_hint',
    'adapter_provider',
    'adapter_title',
    'market_package_id',
    'market_source_id',
    'market_channel_id',
    'market_source_item_id',
)

_CHANNEL_UPDATE_FIELDS = tuple(
    field for field in _CHANNEL_CONFIG_FIELDS
    if field not in {
        'youtube_video_id',
        'requires_headers',
        'proxy_required_hint',
        'adapter_title',
    }
)

_CHANNEL_BOOLEAN_FIELDS = {
    'force_proxy',
    'requires_headers',
    'requires_proxy_declared',
    'proxy_required_hint',
}


def _channel_bool(value) -> int:
    if isinstance(value, str):
        return 0 if value.strip().lower() in {'', '0', 'false', 'no', 'off', 'none', 'null'} else 1
    return 1 if value else 0


def _channel_config_value(channel: dict, field: str):
    if field in _CHANNEL_BOOLEAN_FIELDS:
        return _channel_bool(channel.get(field))
    if field == 'source_type':
        return str(channel.get(field) or 'hls').strip().lower()
    if field == 'adapter_provider':
        return str(channel.get(field) or channel.get('adapter') or '').strip().lower()
    return str(channel.get(field) or '').strip()


def _channel_identity_key(channel: dict) -> tuple:
    values = []
    for field in _CHANNEL_IDENTITY_FIELDS:
        value = _channel_config_value(channel, field)
        if field == 'market_source_item_id' and str(value).startswith('auto-'):
            value = ''
        values.append(value)
    return tuple(values)


def _prepare_channels(channels: list[dict]) -> list[tuple[dict, dict]]:
    prepared = []
    for channel in channels:
        values = {field: _channel_config_value(channel, field) for field in _CHANNEL_CONFIG_FIELDS}
        if not values['name']:
            raise ValueError('channel name 不能为空')
        if not values['url']:
            raise ValueError('channel url 不能为空')
        prepared.append((channel, values))
    return prepared


def _sync_channels_conn(conn: sqlite3.Connection, sub_id: int, prepared: list[tuple[dict, dict]]) -> None:
    existing_rows = conn.execute(
        "SELECT * FROM channels WHERE subscription_id=? ORDER BY id",
        (sub_id,),
    ).fetchall()
    existing_by_key: dict[tuple, list[sqlite3.Row]] = {}
    for row in existing_rows:
        existing_by_key.setdefault(_channel_identity_key(dict(row)), []).append(row)

    retained_ids = []
    update_assignments = ', '.join(f"{field}=?" for field in _CHANNEL_UPDATE_FIELDS)
    insert_fields = ('subscription_id', *_CHANNEL_CONFIG_FIELDS)
    insert_columns = ', '.join(insert_fields)
    insert_placeholders = ', '.join('?' for _ in insert_fields)

    for original, values in prepared:
        matches = existing_by_key.get(_channel_identity_key(original)) or []
        existing = matches.pop(0) if matches else None
        if existing is not None:
            row_id = int(existing['id'])
            update_values = tuple(values[field] for field in _CHANNEL_UPDATE_FIELDS)
            conn.execute(
                f"UPDATE channels SET {update_assignments} WHERE id=? AND subscription_id=?",
                (*update_values, row_id, sub_id),
            )
        else:
            config_values = tuple(values[field] for field in _CHANNEL_CONFIG_FIELDS)
            cursor = conn.execute(
                f"INSERT INTO channels({insert_columns}) VALUES({insert_placeholders})",
                (sub_id, *config_values),
            )
            row_id = int(cursor.lastrowid)
        retained_ids.append(row_id)

    if retained_ids:
        placeholders = ', '.join('?' for _ in retained_ids)
        conn.execute(
            f"DELETE FROM channels WHERE subscription_id=? AND id NOT IN ({placeholders})",
            (sub_id, *retained_ids),
        )
    else:
        conn.execute("DELETE FROM channels WHERE subscription_id=?", (sub_id,))

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE subscriptions SET channel_count=?, last_updated=? WHERE id=?",
        (len(prepared), now, sub_id),
    )


async def add_channels_bulk(sub_id: int, channels: list[dict]):
    prepared = _prepare_channels(channels)

    def _add():
        conn = _connect()
        try:
            with conn:
                _sync_channels_conn(conn, sub_id, prepared)
        finally:
            conn.close()
    await asyncio.to_thread(_add)


async def install_market_package_atomic(
    *,
    package_id: str,
    market_url: str,
    title: str,
    subscription_url: str,
    channels: list[dict],
    installed_version: str = '',
    metadata_json: str = '',
    custom_ua: str = '',
    force_proxy: int = 0,
    auto_update: int = 0,
) -> int:
    if not channels:
        raise ValueError('没有可导入的频道源')
    prepared = _prepare_channels(channels)

    def _install():
        conn = _connect()
        try:
            with conn:
                install = conn.execute(
                    "SELECT * FROM market_packages_installed WHERE package_id=?",
                    (package_id,),
                ).fetchone()
                sub_id = int(install['installed_subscription_id']) if install and install['installed_subscription_id'] else 0
                subscription = conn.execute(
                    "SELECT * FROM subscriptions WHERE id=?",
                    (sub_id,),
                ).fetchone() if sub_id else None

                now = datetime.now(timezone.utc).isoformat()
                if subscription is None:
                    existing = conn.execute(
                        "SELECT id FROM subscriptions WHERE url=?",
                        (subscription_url,),
                    ).fetchone()
                    if existing:
                        raise DuplicateSubscriptionError(subscription_url)
                    cursor = conn.execute(
                        """
                        INSERT INTO subscriptions(
                            title, url, channel_count, valid, last_updated, created_at,
                            custom_ua, force_proxy
                        ) VALUES(?, ?, ?, 1, ?, ?, ?, ?)
                        """,
                        (title, subscription_url, len(channels), now, now, custom_ua, force_proxy),
                    )
                    sub_id = int(cursor.lastrowid)
                else:
                    conn.execute(
                        """
                        UPDATE subscriptions SET
                            title=?, url=?, channel_count=?, valid=1, last_updated=?,
                            custom_ua=?, force_proxy=?
                        WHERE id=?
                        """,
                        (title, subscription_url, len(channels), now, custom_ua, force_proxy, sub_id),
                    )

                _sync_channels_conn(conn, sub_id, prepared)
                conn.execute(
                    """
                    INSERT INTO market_packages_installed(
                        package_id, market_url, installed_subscription_id, installed_version,
                        installed_at, auto_update, metadata_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(package_id) DO UPDATE SET
                        market_url=excluded.market_url,
                        installed_subscription_id=excluded.installed_subscription_id,
                        installed_version=excluded.installed_version,
                        installed_at=excluded.installed_at,
                        auto_update=excluded.auto_update,
                        metadata_json=excluded.metadata_json
                    """,
                    (package_id, market_url, sub_id, installed_version, now, auto_update, metadata_json),
                )
                return sub_id
        finally:
            conn.close()

    return await asyncio.to_thread(_install)


async def uninstall_market_package_atomic(package_id: str) -> bool:
    def _uninstall():
        conn = _connect()
        try:
            with conn:
                install = conn.execute(
                    "SELECT installed_subscription_id FROM market_packages_installed WHERE package_id=?",
                    (package_id,),
                ).fetchone()
                if not install:
                    return False
                sub_id = install['installed_subscription_id']
                conn.execute("DELETE FROM market_packages_installed WHERE package_id=?", (package_id,))
                if sub_id:
                    conn.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
                return True
        finally:
            conn.close()

    return await asyncio.to_thread(_uninstall)


def _apply_sub_fallbacks(rows: list[dict]) -> list[dict]:
    """频道级 custom_ua/force_proxy 为空时，用订阅级 sub_custom_ua/sub_force_proxy 兜底。"""
    for row in rows:
        if not (row.get('custom_ua') or '').strip():
            row['custom_ua'] = row.get('sub_custom_ua', '') or ''
        # force_proxy：channels.force_proxy=1 优先；否则取订阅级
        if not int(row.get('force_proxy') or 0):
            row['force_proxy'] = int(row.get('sub_force_proxy') or 0)
    return rows


async def get_channels(sub_id: int, group: str = '', search: str = '') -> list[dict]:
    """读频道列表；custom_ua/force_proxy 频道级优先，回退到订阅级。"""
    def _get():
        conn = _connect()
        # 同名列 sqlite3.Row → dict 会去重，所以订阅级用 sub_* 别名，
        # 在 Python 侧做"频道级空 → 用订阅级"的回退。
        query = (
            "SELECT c.*, "
            "s.custom_ua AS sub_custom_ua, "
            "s.force_proxy AS sub_force_proxy "
            "FROM channels c JOIN subscriptions s ON c.subscription_id=s.id "
            "WHERE c.subscription_id=?"
        )
        params: list = [sub_id]
        if group:
            query += " AND c.group_name=?"
            params.append(group)
        if search:
            query += " AND c.name LIKE ?"
            params.append(f"%{search}%")
        query += " ORDER BY c.id"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return _apply_sub_fallbacks([dict(r) for r in rows])
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
            SELECT c.*, s.title as sub_title,
                   s.custom_ua AS sub_custom_ua,
                   s.force_proxy AS sub_force_proxy
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
        return _apply_sub_fallbacks([dict(r) for r in rows])
    return await asyncio.to_thread(_get)


def _new_iptv_logical_channel_id() -> str:
    return f'lc_{uuid.uuid4().hex}'


async def get_iptv_logical_channels() -> list[dict]:
    def _get():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM iptv_logical_channels ORDER BY created_at, id"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_get)


async def get_iptv_logical_channel_members() -> list[dict]:
    def _get():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM iptv_logical_channel_members ORDER BY logical_channel_id, channel_id"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_get)


async def sync_iptv_logical_channel_shadow_atomic(groups: list[dict]) -> dict:
    """Atomically reconcile the persisted IPTV logical-channel shadow model.

    ``groups`` is a projection input produced from the current raw channel
    rows.  Membership uniqueness is enforced by SQLite so a partial write can
    never leave one raw channel attached to two logical channels.
    """

    if not isinstance(groups, list):
        raise TypeError('groups 必须是列表')

    def _sync():
        conn = _connect()
        now = _utc_now()
        created_logical_count = 0
        reused_logical_count = 0
        updated_logical_count = 0
        created_member_count = 0
        removed_member_count = 0
        split_conflicts: list[dict] = []
        merge_conflicts: list[dict] = []
        try:
            conn.execute('BEGIN IMMEDIATE')
            raw_ids = {
                int(row['id'])
                for row in conn.execute('SELECT id FROM channels').fetchall()
            }

            normalized_groups = []
            seen_group_keys = set()
            seen_channel_ids = set()
            for group in groups:
                if not isinstance(group, dict):
                    raise TypeError('logical channel group 必须是对象')
                canonical_key = str(group.get('canonical_key') or '').strip()
                display_name = str(group.get('display_name') or '').strip()
                channel_ids = [int(channel_id) for channel_id in (group.get('channel_ids') or [])]
                if not canonical_key or not display_name:
                    raise ValueError('logical channel group 缺少 canonical_key 或 display_name')
                if canonical_key in seen_group_keys:
                    raise ValueError(f'重复 logical canonical_key: {canonical_key}')
                seen_group_keys.add(canonical_key)
                current_channel_ids = [channel_id for channel_id in channel_ids if channel_id in raw_ids]
                cross_group_duplicates = set(current_channel_ids) & seen_channel_ids
                if cross_group_duplicates:
                    duplicate_ids = ', '.join(str(channel_id) for channel_id in sorted(cross_group_duplicates))
                    raise ValueError(f'同一 raw channel 不能属于多个 logical group: {duplicate_ids}')
                seen_channel_ids.update(current_channel_ids)
                if not current_channel_ids:
                    # A stale caller projection may contain only rows deleted
                    # after it was read. Do not materialize a new orphan row
                    # for such an empty target group.
                    continue
                normalized_groups.append({
                    'canonical_key': canonical_key,
                    'display_name': display_name,
                    'channel_ids': current_channel_ids,
                })

            # Foreign keys remove most stale rows automatically, but this
            # explicit cleanup also repairs databases created before the
            # shadow table existed.
            stale_cursor = conn.execute(
                """
                DELETE FROM iptv_logical_channel_members
                WHERE channel_id NOT IN (SELECT id FROM channels)
                """
            )
            removed_member_count += stale_cursor.rowcount

            logical_rows = conn.execute(
                "SELECT * FROM iptv_logical_channels ORDER BY created_at, id"
            ).fetchall()
            logical_by_id = {row['id']: dict(row) for row in logical_rows}
            member_rows = conn.execute(
                "SELECT * FROM iptv_logical_channel_members ORDER BY logical_channel_id, channel_id"
            ).fetchall()
            members_by_logical: dict[str, set[int]] = {logical_id: set() for logical_id in logical_by_id}
            logical_by_channel: dict[int, str] = {}
            for row in member_rows:
                channel_id = int(row['channel_id'])
                logical_id = row['logical_channel_id']
                members_by_logical.setdefault(logical_id, set()).add(channel_id)
                logical_by_channel[channel_id] = logical_id

            target_key_by_channel = {
                channel_id: group['canonical_key']
                for group in normalized_groups
                for channel_id in group['channel_ids']
            }
            # The input projection is authoritative for current membership. A
            # raw row omitted from every target group is no longer groupable
            # (for example, its name normalized to an empty key), so detach it
            # before evaluating split conflicts and orphan state.
            for channel_id, logical_id in list(logical_by_channel.items()):
                if channel_id in target_key_by_channel:
                    continue
                conn.execute(
                    'DELETE FROM iptv_logical_channel_members WHERE channel_id=?',
                    (channel_id,),
                )
                members_by_logical.setdefault(logical_id, set()).discard(channel_id)
                del logical_by_channel[channel_id]
                removed_member_count += 1

            logical_target_keys: dict[str, set[str]] = {}
            for logical_id, channel_ids in members_by_logical.items():
                logical_target_keys[logical_id] = {
                    target_key_by_channel[channel_id]
                    for channel_id in channel_ids
                    if channel_id in target_key_by_channel
                }
            split_ids = {
                logical_id
                for logical_id, target_keys in logical_target_keys.items()
                if len(target_keys) > 1
            }
            for logical_id in sorted(split_ids):
                row = logical_by_id[logical_id]
                split_conflicts.append({
                    'logical_channel_id': logical_id,
                    'canonical_key': row['canonical_key'],
                    'channel_ids': sorted(members_by_logical.get(logical_id, set())),
                    'target_keys': sorted(logical_target_keys[logical_id]),
                })

            handled_logical_ids: set[str] = set()
            touched_logical_ids: set[str] = set()

            def _create_logical(group: dict, status: str) -> str:
                nonlocal created_logical_count
                logical_id = _new_iptv_logical_channel_id()
                conn.execute(
                    """
                    INSERT INTO iptv_logical_channels(
                        id, canonical_key, display_name, status, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (logical_id, group['canonical_key'], group['display_name'], status, now, now),
                )
                logical_by_id[logical_id] = {
                    'id': logical_id,
                    'canonical_key': group['canonical_key'],
                    'display_name': group['display_name'],
                    'status': status,
                }
                members_by_logical[logical_id] = set()
                created_logical_count += 1
                return logical_id

            def _update_logical(logical_id: str, group: dict, status: str) -> None:
                nonlocal updated_logical_count
                old = logical_by_id[logical_id]
                if (
                    old['canonical_key'] != group['canonical_key']
                    or old['display_name'] != group['display_name']
                    or old['status'] != status
                ):
                    conn.execute(
                        """
                        UPDATE iptv_logical_channels
                        SET canonical_key=?, display_name=?, status=?, updated_at=?
                        WHERE id=?
                        """,
                        (group['canonical_key'], group['display_name'], status, now, logical_id),
                    )
                    logical_by_id[logical_id].update(
                        canonical_key=group['canonical_key'],
                        display_name=group['display_name'],
                        status=status,
                    )
                    updated_logical_count += 1

            def _add_members(logical_id: str, channel_ids: list[int]) -> None:
                nonlocal created_member_count
                for channel_id in channel_ids:
                    conn.execute(
                        """
                        INSERT INTO iptv_logical_channel_members(
                            logical_channel_id, channel_id, membership_reason,
                            membership_confidence, variant_type, created_at, updated_at
                        ) VALUES(?, ?, 'normalized_name', 100, 'unknown', ?, ?)
                        """,
                        (logical_id, channel_id, now, now),
                    )
                    members_by_logical.setdefault(logical_id, set()).add(channel_id)
                    logical_by_channel[channel_id] = logical_id
                    created_member_count += 1

            for group in normalized_groups:
                channel_ids = group['channel_ids']
                candidates = sorted({logical_by_channel[channel_id] for channel_id in channel_ids if channel_id in logical_by_channel})
                unassigned = [channel_id for channel_id in channel_ids if channel_id not in logical_by_channel]

                if len(candidates) > 1:
                    for logical_id in candidates:
                        _update_logical(logical_id, logical_by_id[logical_id], 'merge_conflict')
                        touched_logical_ids.add(logical_id)
                    merge_conflicts.append({
                        'canonical_key': group['canonical_key'],
                        'logical_channel_ids': candidates,
                        'channel_ids': sorted(channel_ids),
                    })
                    if unassigned:
                        new_id = _create_logical(group, 'merge_conflict')
                        _add_members(new_id, unassigned)
                        touched_logical_ids.add(new_id)
                    continue

                if len(candidates) == 1 and candidates[0] not in split_ids:
                    logical_id = candidates[0]
                    _update_logical(logical_id, group, 'active')
                    reused_logical_count += 1
                    handled_logical_ids.add(logical_id)
                    touched_logical_ids.add(logical_id)
                    if unassigned:
                        _add_members(logical_id, unassigned)
                    continue

                if len(candidates) == 1 and candidates[0] in split_ids:
                    logical_id = candidates[0]
                    _update_logical(logical_id, logical_by_id[logical_id], 'split_conflict')
                    touched_logical_ids.add(logical_id)
                    if unassigned:
                        new_id = _create_logical(group, 'split_conflict')
                        _add_members(new_id, unassigned)
                        touched_logical_ids.add(new_id)
                    continue

                new_id = _create_logical(group, 'active')
                _add_members(new_id, channel_ids)
                touched_logical_ids.add(new_id)

            for logical_id, row in logical_by_id.items():
                member_count = len(members_by_logical.get(logical_id, set()))
                if member_count == 0:
                    _update_logical(logical_id, row, 'orphaned')
                elif logical_id in split_ids and logical_id not in touched_logical_ids:
                    _update_logical(logical_id, row, 'split_conflict')

            conn.commit()
            return {
                'created_logical_count': created_logical_count,
                'reused_logical_count': reused_logical_count,
                'updated_logical_count': updated_logical_count,
                'created_member_count': created_member_count,
                'removed_member_count': removed_member_count,
                'split_conflicts': split_conflicts,
                'merge_conflicts': merge_conflicts,
            }
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


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


async def update_market_install_check_state(
    package_id: str,
    *,
    checked_at: str | None = None,
    remote_version: str = '',
    version_status: str,
) -> bool:
    package_id = _normalize_identifier(package_id, 'package_id')
    if version_status not in MARKET_VERSION_STATUSES:
        raise ValueError(f'非法 Market 版本状态: {version_status}')
    if not isinstance(remote_version, str):
        raise TypeError('remote_version 必须是字符串')
    checked_at_value = _normalize_timestamp(checked_at, 'checked_at')
    remote_version_value = remote_version.strip()[:256]

    def _update():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE market_packages_installed SET
                        last_checked_at=?,
                        remote_version=?,
                        version_status=?
                    WHERE package_id=?
                    """,
                    (checked_at_value, remote_version_value, version_status, package_id),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_update)


async def mark_market_install_update_started(
    package_id: str,
    *,
    run_token: str,
    started_at: str | None = None,
) -> bool:
    package_id = _normalize_identifier(package_id, 'package_id')
    run_token = _normalize_identifier(run_token, 'run_token')
    started_at_value = _normalize_timestamp(started_at, 'started_at')

    def _start():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE market_packages_installed SET
                        last_update_started_at=?,
                        last_update_finished_at='',
                        last_update_status='running',
                        last_update_error='',
                        last_update_run_token=?
                    WHERE package_id=?
                    """,
                    (started_at_value, run_token, package_id),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_start)


async def complete_market_install_update(
    package_id: str,
    *,
    run_token: str,
    status: str,
    finished_at: str | None = None,
    error: str | None = '',
) -> bool:
    package_id = _normalize_identifier(package_id, 'package_id')
    run_token = _normalize_identifier(run_token, 'run_token')
    if status not in MARKET_UPDATE_FINAL_STATUSES:
        raise ValueError(f'非法 Market 更新完成状态: {status}')
    finished_at_value = _normalize_timestamp(finished_at, 'finished_at')
    error_value = _normalize_error(error)

    def _complete():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE market_packages_installed SET
                        last_update_finished_at=?,
                        last_update_status=?,
                        last_update_error=?
                    WHERE package_id=?
                      AND last_update_run_token=?
                      AND last_update_status='running'
                    """,
                    (finished_at_value, status, error_value, package_id, run_token),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_complete)


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
                youtube_video_id=COALESCE(NULLIF(?, ''), youtube_video_id),
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
                str(result.get('youtube_video_id') or ''),
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


async def get_epg_source(source_id: int) -> dict | None:
    def _get():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM epg_sources WHERE id=?", (source_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    return await asyncio.to_thread(_get)


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
    allowed = {'name', 'url', 'enabled'}
    unknown = set(kwargs) - allowed
    if unknown:
        raise ValueError(f"不支持的 EPG 来源字段: {', '.join(sorted(unknown))}")
    if not kwargs:
        return await get_epg_source(source_id)

    def _update():
        conn = _connect()
        try:
            with conn:
                current = conn.execute("SELECT * FROM epg_sources WHERE id=?", (source_id,)).fetchone()
                if current is None:
                    return None
                updates = dict(kwargs)
                if 'enabled' in updates:
                    updates['enabled'] = _normalize_enabled(updates['enabled'])
                identity_changed = any(
                    field in updates and updates[field] != current[field]
                    for field in ('url', 'enabled')
                )
                if identity_changed:
                    updates['revision'] = int(current['revision'] or 1) + 1
                    updates['last_status'] = (
                        'disabled' if updates.get('enabled', current['enabled']) == 0
                        else 'revision_discarded'
                    )
                    updates['last_error'] = ''
                updates['updated_at'] = _utc_now()
                sets = ', '.join(f"{key}=?" for key in updates)
                conn.execute(
                    f"UPDATE epg_sources SET {sets} WHERE id=?",
                    (*updates.values(), source_id),
                )
                row = conn.execute("SELECT * FROM epg_sources WHERE id=?", (source_id,)).fetchone()
                return dict(row)
        finally:
            conn.close()
    return await asyncio.to_thread(_update)


def _normalize_epg_error(value: str | None) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise TypeError('EPG error 必须是字符串')
    return value.replace('\x00', '').strip()[:EPG_ERROR_MAX_LENGTH]


async def begin_epg_source_refresh(
    source_id: int,
    expected_revision: int,
    *,
    attempted_at: str | None = None,
) -> bool:
    attempted = _normalize_timestamp(attempted_at, 'attempted_at')

    def _begin():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE epg_sources
                    SET last_attempt_at=?, last_status='running', last_error='', updated_at=?
                    WHERE id=? AND revision=? AND enabled=1
                    """,
                    (attempted, attempted, source_id, expected_revision),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_begin)


async def record_epg_source_disabled(
    source_id: int,
    expected_revision: int,
    *,
    attempted_at: str | None = None,
) -> bool:
    attempted = _normalize_timestamp(attempted_at, 'attempted_at')

    def _record():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE epg_sources
                    SET last_attempt_at=?, last_status='disabled', last_error='', updated_at=?
                    WHERE id=? AND revision=? AND enabled=0
                    """,
                    (attempted, attempted, source_id, expected_revision),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_record)


async def record_epg_source_refresh_failure(
    source_id: int,
    expected_revision: int,
    *,
    status: str,
    attempted_at: str | None = None,
    error: str = '',
) -> bool:
    if status not in {'stale', 'failed', 'cancelled'}:
        raise ValueError('EPG 来源失败状态必须是 stale、failed 或 cancelled')
    attempted = _normalize_timestamp(attempted_at, 'attempted_at')
    normalized_error = _normalize_epg_error(error)

    def _record():
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE epg_sources
                    SET last_attempt_at=?, last_status=?, last_error=?, updated_at=?
                    WHERE id=? AND revision=?
                    """,
                    (
                        attempted,
                        status,
                        normalized_error,
                        _utc_now(),
                        source_id,
                        expected_revision,
                    ),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_record)


async def has_epg_dataset(source_id: int) -> bool:
    def _has():
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT EXISTS(SELECT 1 FROM epg_channels WHERE source_id=? LIMIT 1) AS has_channels,
                       EXISTS(SELECT 1 FROM epg_programs WHERE source_id=? LIMIT 1) AS has_programmes
                """,
                (source_id, source_id),
            ).fetchone()
            return bool(row['has_channels'] and row['has_programmes'])
        finally:
            conn.close()

    return await asyncio.to_thread(_has)


async def replace_epg_dataset_atomic(
    source_id: int,
    expected_revision: int,
    channels: list[dict],
    programmes: list[dict],
    *,
    stats: dict,
) -> dict:
    channel_count = _normalize_count(stats.get('channel_count'), 'channel_count')
    programme_count = _normalize_count(stats.get('programme_count'), 'programme_count')
    if channel_count != len(channels) or programme_count != len(programmes):
        raise ValueError('EPG 数据集统计与实际记录数量不一致')
    data_start_at = _normalize_timestamp(stats.get('data_start_at'), 'data_start_at')
    data_end_at = _normalize_timestamp(stats.get('data_end_at'), 'data_end_at')
    finished_at = _normalize_timestamp(stats.get('finished_at'), 'finished_at')
    attempted_at = _normalize_timestamp(stats.get('attempted_at') or finished_at, 'attempted_at')

    def _replace():
        conn = _connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            source = conn.execute("SELECT * FROM epg_sources WHERE id=?", (source_id,)).fetchone()
            if source is None:
                conn.rollback()
                return {'committed': False, 'reason': 'revision_discarded', 'source': None}
            if int(source['revision'] or 1) != expected_revision:
                conn.rollback()
                return {'committed': False, 'reason': 'revision_discarded', 'source': dict(source)}
            if not source['enabled']:
                conn.rollback()
                return {'committed': False, 'reason': 'disabled', 'source': dict(source)}

            conn.execute("DELETE FROM epg_channels WHERE source_id=?", (source_id,))
            conn.execute("DELETE FROM epg_programs WHERE source_id=?", (source_id,))
            conn.executemany(
                "INSERT INTO epg_channels(source_id, channel_id, display_names, normalized_names) VALUES(?, ?, ?, ?)",
                [
                    (source_id, item['channel_id'], item['display_names'], item['normalized_names'])
                    for item in channels
                ],
            )
            conn.executemany(
                "INSERT INTO epg_programs(source_id, channel_id, start, stop, title, description) VALUES(?, ?, ?, ?, ?, ?)",
                [
                    (
                        source_id,
                        item['channel_id'],
                        item['start'],
                        item['stop'],
                        item['title'],
                        item.get('description', ''),
                    )
                    for item in programmes
                ],
            )
            cursor = conn.execute(
                """
                UPDATE epg_sources
                SET last_fetched_at=?, last_attempt_at=?, last_success_at=?,
                    last_status='success', last_error='', channel_count=?, programme_count=?,
                    data_start_at=?, data_end_at=?, updated_at=?
                WHERE id=? AND revision=? AND enabled=1
                """,
                (
                    finished_at,
                    attempted_at,
                    finished_at,
                    channel_count,
                    programme_count,
                    data_start_at,
                    data_end_at,
                    finished_at,
                    source_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return {'committed': False, 'reason': 'revision_discarded', 'source': None}
            conn.commit()
            current = conn.execute("SELECT * FROM epg_sources WHERE id=?", (source_id,)).fetchone()
            return {'committed': True, 'reason': '', 'source': dict(current)}
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_replace)


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
