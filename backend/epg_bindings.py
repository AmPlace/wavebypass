"""Shadow bindings between IPTV logical channels and source-aware EPG targets.

This module is intentionally isolated from the production matcher and all
existing EPG reads.  It provides a conservative, explicit migration path from
``channel_epg_map`` into a durable shadow relationship.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

import database as db
from epg_catalog import EpgChannelIdentity, build_epg_channel_catalog


BINDING_STATUSES = {
    'matched',
    'ambiguous',
    'unmatched',
    'not_applicable',
    'conflict',
    'orphan_target',
}
BINDING_ORIGINS = {'legacy_migrated', 'automatic', 'manual'}
MIGRATABLE_MATCH_STATUSES = {'matched', 'locked'}
LOGICAL_CONFLICT_STATUSES = {'split_conflict', 'merge_conflict'}


@dataclass(frozen=True)
class EpgLogicalChannelBinding:
    id: int
    logical_channel_id: str
    target: EpgChannelIdentity
    status: str
    match_type: str
    confidence: int
    locked: bool
    origin: str
    legacy_canonical_key: str
    created_at: str
    updated_at: str
    shadow_run_id: str | None = None

    @property
    def epg_source_id(self) -> int:
        return self.target.source_id

    @property
    def epg_channel_id(self) -> str:
        return self.target.channel_id

    def as_dict(self) -> dict:
        return {
            'id': self.id,
            'logical_channel_id': self.logical_channel_id,
            'epg_source_id': self.epg_source_id,
            'epg_channel_id': self.epg_channel_id,
            'target': self.target.as_dict(),
            'status': self.status,
            'match_type': self.match_type,
            'confidence': self.confidence,
            'locked': self.locked,
            'origin': self.origin,
            'legacy_canonical_key': self.legacy_canonical_key,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'shadow_run_id': self.shadow_run_id,
        }


_BINDING_SELECT = """
    SELECT id, logical_channel_id, epg_source_id, epg_channel_id,
           status, match_type, confidence, locked, origin,
           legacy_canonical_key, created_at, updated_at, shadow_run_id
    FROM iptv_logical_channel_epg_bindings
"""


def _binding_from_row(row: Mapping[str, object]) -> EpgLogicalChannelBinding:
    return EpgLogicalChannelBinding(
        id=int(row['id']),
        logical_channel_id=str(row['logical_channel_id']),
        target=EpgChannelIdentity(int(row['epg_source_id']), str(row['epg_channel_id'])),
        status=str(row['status']),
        match_type=str(row.get('match_type') or ''),
        confidence=int(row.get('confidence') or 0),
        locked=bool(row.get('locked')),
        origin=str(row.get('origin') or ''),
        legacy_canonical_key=str(row.get('legacy_canonical_key') or ''),
        created_at=str(row.get('created_at') or ''),
        updated_at=str(row.get('updated_at') or ''),
        shadow_run_id=(str(row['shadow_run_id']) if row.get('shadow_run_id') else None),
    )


def _validate_confidence(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError('confidence 必须是 0 到 100 的整数')
    if not 0 <= value <= 100:
        raise ValueError('confidence 必须是 0 到 100 的整数')
    return value


def _validate_text(value: str, field: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{field} 必须是字符串')
    if not value:
        raise ValueError(f'{field} 不能为空')
    if len(value) > max_length:
        raise ValueError(f'{field} 长度不能超过 {max_length}')
    return value


def _validate_status(status: str) -> str:
    if status not in BINDING_STATUSES:
        raise ValueError(f'非法 binding 状态: {status}')
    return status


def _validate_origin(origin: str) -> str:
    if origin not in BINDING_ORIGINS:
        raise ValueError(f'非法 binding 来源: {origin}')
    return origin


def _target_exists(conn, target: EpgChannelIdentity) -> bool:
    row = conn.execute(
        "SELECT 1 FROM epg_channels WHERE source_id=? AND channel_id=? LIMIT 1",
        (target.source_id, target.channel_id),
    ).fetchone()
    return row is not None


def _logical_row(conn, logical_channel_id: str):
    return conn.execute(
        "SELECT id, canonical_key, status FROM iptv_logical_channels WHERE id=?",
        (logical_channel_id,),
    ).fetchone()


def _load_binding_rows(conn) -> list[dict]:
    return [dict(row) for row in conn.execute(_BINDING_SELECT + ' ORDER BY id').fetchall()]


async def get_epg_binding(logical_channel_id: str) -> EpgLogicalChannelBinding | None:
    logical_channel_id = _validate_text(logical_channel_id, 'logical_channel_id')

    def _get():
        conn = db._connect()
        try:
            row = conn.execute(
                _BINDING_SELECT + ' WHERE logical_channel_id=?',
                (logical_channel_id,),
            ).fetchone()
            return _binding_from_row(dict(row)) if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_get)


async def list_epg_bindings() -> list[EpgLogicalChannelBinding]:
    def _list():
        conn = db._connect()
        try:
            return [_binding_from_row(row) for row in _load_binding_rows(conn)]
        finally:
            conn.close()

    return await asyncio.to_thread(_list)


async def validate_epg_binding_target(source_id: int, channel_id: str) -> bool:
    target = EpgChannelIdentity(int(source_id), _validate_text(channel_id, 'epg_channel_id'))

    def _validate():
        conn = db._connect()
        try:
            return _target_exists(conn, target)
        finally:
            conn.close()

    return await asyncio.to_thread(_validate)


async def create_matched_epg_binding(
    logical_channel_id: str,
    epg_source_id: int,
    epg_channel_id: str,
    *,
    match_type: str = '',
    confidence: int = 0,
    locked: bool = False,
    origin: str = 'manual',
    legacy_canonical_key: str = '',
    shadow_run_id: str | None = None,
) -> EpgLogicalChannelBinding:
    logical_channel_id = _validate_text(logical_channel_id, 'logical_channel_id')
    target = EpgChannelIdentity(int(epg_source_id), _validate_text(epg_channel_id, 'epg_channel_id'))
    confidence = _validate_confidence(confidence)
    match_type = '' if match_type is None else _validate_text(match_type, 'match_type') if match_type else ''
    origin = _validate_origin(origin)
    if not isinstance(locked, bool) and locked not in (0, 1):
        raise TypeError('locked 必须是布尔值')
    if shadow_run_id is not None and shadow_run_id != '':
        shadow_run_id = _validate_text(str(shadow_run_id), 'shadow_run_id')
    else:
        shadow_run_id = None
    if legacy_canonical_key is None or legacy_canonical_key == '':
        legacy_canonical_key = ''
    else:
        legacy_canonical_key = _validate_text(
            str(legacy_canonical_key), 'legacy_canonical_key'
        )

    def _create():
        conn = db._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            logical = _logical_row(conn, logical_channel_id)
            if logical is None:
                raise ValueError('logical channel 不存在')
            if logical['status'] in LOGICAL_CONFLICT_STATUSES:
                raise ValueError('logical channel 处于 conflict 状态')
            if not _target_exists(conn, target):
                raise ValueError('EPG composite target 不存在')
            existing = conn.execute(
                _BINDING_SELECT + ' WHERE logical_channel_id=?',
                (logical_channel_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError('logical channel 已有 binding')
            now = db._utc_now()
            cursor = conn.execute(
                """
                INSERT INTO iptv_logical_channel_epg_bindings(
                    logical_channel_id, epg_source_id, epg_channel_id,
                    status, match_type, confidence, locked, origin,
                    legacy_canonical_key, shadow_run_id, created_at, updated_at
                ) VALUES(?, ?, ?, 'matched', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    logical_channel_id,
                    target.source_id,
                    target.channel_id,
                    match_type,
                    confidence,
                    int(bool(locked)),
                    origin,
                    legacy_canonical_key,
                    shadow_run_id,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                _BINDING_SELECT + ' WHERE id=?',
                (cursor.lastrowid,),
            ).fetchone()
            conn.commit()
            return _binding_from_row(dict(row))
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_create)


async def update_epg_binding_status(
    logical_channel_id: str,
    status: str,
) -> EpgLogicalChannelBinding | None:
    logical_channel_id = _validate_text(logical_channel_id, 'logical_channel_id')
    status = _validate_status(status)

    def _update():
        conn = db._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute(
                _BINDING_SELECT + ' WHERE logical_channel_id=?',
                (logical_channel_id,),
            ).fetchone()
            if current is None:
                conn.commit()
                return None
            current_dict = dict(current)
            target = EpgChannelIdentity(
                int(current_dict['epg_source_id']),
                str(current_dict['epg_channel_id']),
            )
            if status == 'matched' and not _target_exists(conn, target):
                raise ValueError('EPG composite target 不存在')
            conn.execute(
                "UPDATE iptv_logical_channel_epg_bindings SET status=?, updated_at=? WHERE logical_channel_id=?",
                (status, db._utc_now(), logical_channel_id),
            )
            row = conn.execute(
                _BINDING_SELECT + ' WHERE logical_channel_id=?',
                (logical_channel_id,),
            ).fetchone()
            conn.commit()
            return _binding_from_row(dict(row))
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_update)


async def delete_epg_binding(logical_channel_id: str) -> bool:
    logical_channel_id = _validate_text(logical_channel_id, 'logical_channel_id')

    def _delete():
        conn = db._connect()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM iptv_logical_channel_epg_bindings WHERE logical_channel_id=?",
                    (logical_channel_id,),
                )
                return cursor.rowcount == 1
        finally:
            conn.close()

    return await asyncio.to_thread(_delete)


async def list_orphan_target_bindings() -> list[EpgLogicalChannelBinding]:
    def _list():
        conn = db._connect()
        try:
            rows = conn.execute(
                _BINDING_SELECT + " b WHERE NOT EXISTS (SELECT 1 FROM epg_channels c WHERE c.source_id=b.epg_source_id AND c.channel_id=b.epg_channel_id) ORDER BY b.id"
            ).fetchall()
            return [_binding_from_row(dict(row)) for row in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_list)


async def list_conflict_bindings() -> list[EpgLogicalChannelBinding]:
    def _list():
        conn = db._connect()
        try:
            rows = conn.execute(
                _BINDING_SELECT + " WHERE status='conflict' ORDER BY id"
            ).fetchall()
            return [_binding_from_row(dict(row)) for row in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_list)


def _safe_summary(record: Mapping[str, object]) -> dict:
    return {
        'mapping_id': int(record['mapping_id']),
        'reason': str(record['reason']),
        'logical_channel_id': record.get('logical_channel_id'),
        'canonical_key': str(record.get('canonical_key') or ''),
        'epg_source_id': record.get('epg_source_id'),
        'epg_channel_id': record.get('epg_channel_id'),
    }


def _classify_legacy_records(
    legacy_rows: Iterable[Mapping[str, object]],
    logical_rows: Iterable[Mapping[str, object]],
    target_identities: set[EpgChannelIdentity],
) -> list[dict]:
    logical_by_key: dict[str, list[dict]] = defaultdict(list)
    for row in logical_rows:
        logical_by_key[str(row.get('canonical_key') or '')].append(dict(row))

    base_records: list[dict] = []
    resolved: list[dict] = []
    for row in legacy_rows:
        mapping_id = int(row['id'])
        canonical_key = str(row.get('canonical_key') or '')
        match_status = str(row.get('match_status') or '').lower()
        base = {
            'mapping_id': mapping_id,
            'canonical_key': canonical_key,
            'logical_channel_id': None,
            'epg_source_id': row.get('epg_source_id'),
            'epg_channel_id': row.get('epg_channel_id'),
            'locked': bool(row.get('locked')),
            'confidence': int(row.get('confidence') or 0),
            'match_type': str(row.get('match_type') or ''),
        }
        if match_status not in MIGRATABLE_MATCH_STATUSES:
            base['reason'] = 'legacy_unmatched'
            base_records.append(base)
            continue

        source_id = row.get('epg_source_id')
        channel_id = row.get('epg_channel_id')
        if source_id is None or channel_id is None or str(channel_id) == '':
            base['reason'] = 'legacy_unmatched'
            base_records.append(base)
            continue
        try:
            target = EpgChannelIdentity(int(source_id), str(channel_id))
        except (TypeError, ValueError):
            base['reason'] = 'legacy_unmatched'
            base_records.append(base)
            continue

        logical_candidates = logical_by_key.get(canonical_key, [])
        active = [row for row in logical_candidates if row.get('status') == 'active']
        if (
            len(logical_candidates) != 1
            or len(active) != 1
            or any(row.get('status') in LOGICAL_CONFLICT_STATUSES for row in logical_candidates)
        ):
            base['reason'] = 'orphan_key' if not logical_candidates else 'ambiguous_logical'
            base_records.append(base)
            continue
        base['logical_channel_id'] = active[0]['id']
        base['target'] = target
        resolved.append(base)

    by_logical: dict[str, list[dict]] = defaultdict(list)
    for record in resolved:
        by_logical[str(record['logical_channel_id'])].append(record)

    classified = list(base_records)
    for logical_id, records in by_logical.items():
        distinct_targets = {record['target'] for record in records}
        if len(distinct_targets) > 1:
            for record in records:
                record['reason'] = 'conflicting_target'
                classified.append(record)
            continue
        target = next(iter(distinct_targets))
        if target not in target_identities:
            for record in records:
                record['reason'] = 'orphan_target'
                classified.append(record)
            continue
        canonical_record = sorted(
            records,
            key=lambda record: (
                -int(record['locked']),
                -int(record['confidence']),
                int(record['mapping_id']),
            ),
        )[0]
        canonical_record['reason'] = 'eligible'
        classified.append(canonical_record)
        for record in records:
            if record is canonical_record:
                continue
            record['reason'] = 'duplicate_same_target'
            classified.append(record)

    return sorted(classified, key=lambda record: int(record['mapping_id']))


def _preview_result(legacy_rows: list[Mapping[str, object]], records: list[dict]) -> dict:
    counts = defaultdict(int)
    for record in records:
        counts[record['reason']] += 1
    samples: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        reason = str(record['reason'])
        if len(samples[reason]) < 10:
            samples[reason].append(_safe_summary(record))
    eligible_records = [record for record in records if record['reason'] == 'eligible']
    return {
        'total_legacy_count': len(legacy_rows),
        'eligible_count': len(eligible_records),
        'orphan_key_count': counts['orphan_key'],
        'ambiguous_logical_count': counts['ambiguous_logical'],
        'orphan_target_count': counts['orphan_target'],
        'legacy_unmatched_count': counts['legacy_unmatched'],
        'duplicate_same_target_count': counts['duplicate_same_target'],
        'conflicting_target_count': counts['conflicting_target'],
        'locked_count': sum(bool(row.get('locked')) for row in legacy_rows),
        'samples': dict(samples),
        'records': [_safe_summary(record) for record in records],
        'eligible_records': [_safe_summary(record) for record in eligible_records],
    }


async def preview_legacy_epg_binding_migration() -> dict:
    legacy_rows = await db.get_all_channel_epg_maps()
    logical_rows = await db.get_iptv_logical_channels()
    catalog = await build_epg_channel_catalog()
    records = _classify_legacy_records(legacy_rows, logical_rows, set(catalog.by_identity))
    return _preview_result(legacy_rows, records)


def _migration_snapshot(conn) -> tuple[list[dict], list[dict], set[EpgChannelIdentity]]:
    legacy_rows = [dict(row) for row in conn.execute('SELECT * FROM channel_epg_map ORDER BY id').fetchall()]
    logical_rows = [dict(row) for row in conn.execute('SELECT * FROM iptv_logical_channels ORDER BY id').fetchall()]
    target_identities = {
        EpgChannelIdentity(int(row['source_id']), str(row['channel_id']))
        for row in conn.execute('SELECT source_id, channel_id FROM epg_channels').fetchall()
    }
    return legacy_rows, logical_rows, target_identities


async def migrate_legacy_epg_bindings_shadow() -> dict:
    """Conservatively migrate eligible legacy mappings in one transaction."""

    def _migrate():
        conn = db._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            legacy_rows, logical_rows, target_identities = _migration_snapshot(conn)
            records = _classify_legacy_records(legacy_rows, logical_rows, target_identities)
            result = _preview_result(legacy_rows, records)
            created_count = 0
            already_migrated_count = 0
            locked_conflict_count = 0
            existing_conflict_count = 0
            for record in records:
                if record['reason'] != 'eligible':
                    continue
                logical_id = str(record['logical_channel_id'])
                existing = conn.execute(
                    _BINDING_SELECT + ' WHERE logical_channel_id=?',
                    (logical_id,),
                ).fetchone()
                target = record['target']
                if existing is not None:
                    existing_target = EpgChannelIdentity(
                        int(existing['epg_source_id']),
                        str(existing['epg_channel_id']),
                    )
                    if existing_target == target:
                        already_migrated_count += 1
                    elif bool(existing['locked']):
                        locked_conflict_count += 1
                    else:
                        existing_conflict_count += 1
                    continue
                logical = _logical_row(conn, logical_id)
                if logical is None or logical['status'] in LOGICAL_CONFLICT_STATUSES:
                    existing_conflict_count += 1
                    continue
                if not _target_exists(conn, target):
                    existing_conflict_count += 1
                    continue
                now = db._utc_now()
                conn.execute(
                    """
                    INSERT INTO iptv_logical_channel_epg_bindings(
                        logical_channel_id, epg_source_id, epg_channel_id,
                        status, match_type, confidence, locked, origin,
                        legacy_canonical_key, created_at, updated_at
                    ) VALUES(?, ?, ?, 'matched', ?, ?, ?, 'legacy_migrated', ?, ?, ?)
                    """,
                    (
                        logical_id,
                        target.source_id,
                        target.channel_id,
                        record['match_type'],
                        max(0, min(100, int(record['confidence']))),
                        int(record['locked']),
                        record['canonical_key'],
                        now,
                        now,
                    ),
                )
                created_count += 1
            conn.commit()
            result.update({
                'created_count': created_count,
                'already_migrated_count': already_migrated_count,
                'locked_conflict_count': locked_conflict_count,
                'existing_conflict_count': existing_conflict_count,
            })
            return result
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    return await asyncio.to_thread(_migrate)


async def validate_epg_binding_shadow() -> dict:
    def _validate():
        conn = db._connect()
        try:
            bindings = _load_binding_rows(conn)
            logical_rows = {
                str(row['id']): dict(row)
                for row in conn.execute('SELECT id, status FROM iptv_logical_channels').fetchall()
            }
            targets = {
                EpgChannelIdentity(int(row['source_id']), str(row['channel_id']))
                for row in conn.execute('SELECT source_id, channel_id FROM epg_channels').fetchall()
            }
            valid_target_count = 0
            orphan_target_count = 0
            logical_orphan_count = 0
            conflict_count = 0
            cross_source_resolution_errors = 0
            orphan_samples = []
            for row in bindings:
                target = EpgChannelIdentity(int(row['epg_source_id']), str(row['epg_channel_id']))
                if target in targets:
                    valid_target_count += 1
                else:
                    orphan_target_count += 1
                    if len(orphan_samples) < 10:
                        orphan_samples.append(_safe_summary({
                            'mapping_id': row['id'],
                            'reason': 'orphan_target',
                            'logical_channel_id': row['logical_channel_id'],
                            'canonical_key': row['legacy_canonical_key'],
                            'epg_source_id': row['epg_source_id'],
                            'epg_channel_id': row['epg_channel_id'],
                        }))
                    same_channel_other_source = conn.execute(
                        "SELECT 1 FROM epg_channels WHERE channel_id=? AND source_id<>? LIMIT 1",
                        (row['epg_channel_id'], row['epg_source_id']),
                    ).fetchone()
                    cross_source_resolution_errors += int(same_channel_other_source is not None)
                logical = logical_rows.get(str(row['logical_channel_id']))
                if logical is None or logical['status'] == 'orphaned':
                    logical_orphan_count += 1
                if row['status'] == 'conflict' or (logical and logical['status'] in LOGICAL_CONFLICT_STATUSES):
                    conflict_count += 1
            duplicate_rows = conn.execute(
                """
                SELECT COALESCE(SUM(binding_count - 1), 0) AS duplicate_count
                FROM (
                    SELECT logical_channel_id, COUNT(*) AS binding_count
                    FROM iptv_logical_channel_epg_bindings
                    GROUP BY logical_channel_id
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()
            return {
                'binding_count': len(bindings),
                'valid_target_count': valid_target_count,
                'orphan_target_count': orphan_target_count,
                'logical_orphan_count': logical_orphan_count,
                'conflict_count': conflict_count,
                'locked_count': sum(bool(row['locked']) for row in bindings),
                'migrated_count': sum(row['origin'] == 'legacy_migrated' for row in bindings),
                'duplicate_logical_binding_count': int(duplicate_rows['duplicate_count'] or 0),
                'cross_source_resolution_errors': cross_source_resolution_errors,
                'orphan_samples': orphan_samples,
            }
        finally:
            conn.close()

    return await asyncio.to_thread(_validate)
