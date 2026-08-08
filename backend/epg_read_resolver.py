"""Read-only comparison between legacy EPG mappings and shadow bindings.

EPG read resolution compares the legacy mapping with the source-aware
shadow binding without writing either table.  The effective target policy is
kept here so programme and batch reads cannot diverge.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable, Mapping

import database as db
from epg_catalog import EpgChannelIdentity


LOGICAL_CONFLICT_STATUSES = {'orphaned', 'split_conflict', 'merge_conflict'}
READABLE_BINDING_STATUSES = {'matched'}
_UNSET = object()

logger = logging.getLogger(__name__)
_DIAGNOSTIC_STATUSES = {
    'target_changed',
    'logical_ambiguous',
    'logical_conflict',
    'shadow_orphan_target',
    'migrated_target_mismatch',
}


@dataclass(frozen=True)
class EpgReadTarget:
    """A source-aware EPG target plus the current dataset/source state."""

    source_id: int
    channel_id: str
    exists: bool
    source_enabled: bool | None = None
    source_status: str = ''

    @property
    def identity(self) -> EpgChannelIdentity:
        return EpgChannelIdentity(self.source_id, self.channel_id)

    @property
    def readable(self) -> bool:
        # EPG-1 preserves the last committed dataset and programme reads do
        # not filter on enabled/last_status. Therefore stale, failed, and
        # disabled sources remain queryable while the composite channel row
        # exists; those states are diagnostics, not read blockers.
        return self.exists

    def as_dict(self) -> dict:
        return {
            'source_id': self.source_id,
            'channel_id': self.channel_id,
            'exists': self.exists,
            'readable': self.readable,
            'source_enabled': self.source_enabled,
            'source_status': self.source_status,
        }


@dataclass(frozen=True)
class EpgReadResolution:
    """A safe, internal diagnostic for one canonical-key read."""

    canonical_key: str
    logical_channel_ids: tuple[str, ...]
    logical_channel_id: str | None
    legacy_target: EpgReadTarget | None
    shadow_target: EpgReadTarget | None
    comparison_status: str
    effective_target: EpgReadTarget | None
    effective_source: str
    fallback_reason: str
    legacy_mapping: dict | None
    shadow_binding: dict | None

    def as_dict(self) -> dict:
        return {
            'canonical_key': self.canonical_key,
            'logical_channel_ids': list(self.logical_channel_ids),
            'logical_channel_id': self.logical_channel_id,
            'legacy_target': self.legacy_target.as_dict() if self.legacy_target else None,
            'shadow_target': self.shadow_target.as_dict() if self.shadow_target else None,
            'comparison_status': self.comparison_status,
            'effective_target': self.effective_target.as_dict() if self.effective_target else None,
            'effective_source': self.effective_source,
            'fallback_reason': self.fallback_reason,
            'legacy_mapping': self.legacy_mapping,
            'shadow_binding': self.shadow_binding,
        }


def _identity_from_mapping(row: Mapping[str, object] | None) -> EpgChannelIdentity | None:
    if not row:
        return None
    source_id = row.get('epg_source_id')
    channel_id = row.get('epg_channel_id')
    if source_id is None or channel_id is None or str(channel_id) == '':
        return None
    try:
        return EpgChannelIdentity(int(source_id), str(channel_id))
    except (TypeError, ValueError):
        return None


def _target_from_identity(
    identity: EpgChannelIdentity | None,
    target_rows: Mapping[EpgChannelIdentity, Mapping[str, object]],
) -> EpgReadTarget | None:
    if identity is None:
        return None
    row = target_rows.get(identity)
    return EpgReadTarget(
        source_id=identity.source_id,
        channel_id=identity.channel_id,
        exists=row is not None,
        source_enabled=(bool(row.get('source_enabled')) if row is not None else None),
        source_status=(str(row.get('source_status') or '') if row is not None else ''),
    )


def _safe_legacy_mapping(row: Mapping[str, object] | None) -> dict | None:
    if row is None:
        return None
    # Do not carry match_detail into diagnostics; historical records may
    # contain URLs or other secret-bearing text.
    fields = (
        'id', 'canonical_key', 'epg_source_id', 'epg_channel_id',
        'match_type', 'confidence', 'match_status', 'locked', 'updated_at',
    )
    return {field: row.get(field) for field in fields if field in row}


def _safe_shadow_binding(row: Mapping[str, object] | None) -> dict | None:
    if row is None:
        return None
    fields = (
        'id', 'logical_channel_id', 'epg_source_id', 'epg_channel_id',
        'status', 'match_type', 'confidence', 'locked', 'origin',
        'shadow_run_id', 'legacy_canonical_key', 'created_at', 'updated_at',
    )
    return {field: row.get(field) for field in fields if field in row}


def resolve_epg_read_snapshot(
    canonical_key: str,
    *,
    legacy_mapping: Mapping[str, object] | None,
    logical_rows: Iterable[Mapping[str, object]],
    binding_rows: Iterable[Mapping[str, object]],
    target_rows: Iterable[Mapping[str, object]],
) -> EpgReadResolution:
    """Resolve and select a read target from caller-provided snapshots."""
    indexes = _build_snapshot_indexes(logical_rows, binding_rows, target_rows)
    return _resolve_epg_read_indexed(
        canonical_key,
        legacy_mapping=legacy_mapping,
        indexes=indexes,
    )


def _build_snapshot_indexes(
    logical_rows: Iterable[Mapping[str, object]],
    binding_rows: Iterable[Mapping[str, object]],
    target_rows: Iterable[Mapping[str, object]],
) -> dict[str, dict]:
    """Build deterministic in-memory indexes for one read snapshot."""
    logical_by_key: dict[str, list[dict]] = {}
    for row in logical_rows:
        item = dict(row)
        key = str(item.get('canonical_key') or '')
        logical_by_key.setdefault(key, []).append(item)
    for rows in logical_by_key.values():
        rows.sort(key=lambda row: str(row.get('id') or ''))

    target_by_identity: dict[EpgChannelIdentity, Mapping[str, object]] = {}
    for row in target_rows:
        target_by_identity[EpgChannelIdentity(int(row['source_id']), str(row['channel_id']))] = row

    binding_by_logical: dict[str, dict] = {}
    for row in binding_rows:
        binding_by_logical[str(row.get('logical_channel_id') or '')] = dict(row)

    return {
        'logical_by_key': logical_by_key,
        'binding_by_logical': binding_by_logical,
        'target_by_identity': target_by_identity,
    }


def _resolve_epg_read_indexed(
    canonical_key: str,
    *,
    legacy_mapping: Mapping[str, object] | None,
    indexes: Mapping[str, Mapping],
) -> EpgReadResolution:
    """Resolve one key against indexes built from a single snapshot."""
    canonical_key = str(canonical_key)
    logical_candidates = list(indexes['logical_by_key'].get(canonical_key, ()))
    logical_ids = tuple(str(row.get('id') or '') for row in logical_candidates)
    logical_channel_id: str | None = None
    logical_status = ''
    if len(logical_candidates) == 1:
        logical_channel_id = logical_ids[0]
        logical_status = str(logical_candidates[0].get('status') or '')

    legacy_identity = _identity_from_mapping(legacy_mapping)
    target_by_identity = indexes['target_by_identity']
    legacy_target = _target_from_identity(legacy_identity, target_by_identity)

    binding_by_logical = indexes['binding_by_logical']
    binding = None
    shadow_target = None
    if len(logical_candidates) == 1 and logical_status == 'active':
        candidate_binding = binding_by_logical.get(logical_channel_id or '')
        if (
            candidate_binding is not None
            and str(candidate_binding.get('status') or '') in READABLE_BINDING_STATUSES
        ):
            binding = candidate_binding
            shadow_target = _target_from_identity(_identity_from_mapping(binding), target_by_identity)

    if not logical_candidates:
        comparison_status = 'logical_missing'
        fallback_reason = 'logical_channel_missing'
    elif len(logical_candidates) != 1:
        comparison_status = 'logical_ambiguous'
        fallback_reason = 'multiple_logical_channels'
    elif logical_status in LOGICAL_CONFLICT_STATUSES:
        comparison_status = 'logical_conflict'
        fallback_reason = f'logical_channel_{logical_status}'
    elif binding is not None and shadow_target is not None and not shadow_target.exists:
        comparison_status = 'shadow_orphan_target'
        fallback_reason = 'shadow_target_missing'
    elif binding is not None and shadow_target is not None:
        if legacy_target is None:
            comparison_status = 'shadow_only'
            fallback_reason = 'legacy_mapping_missing_shadow'
        elif legacy_target.identity == shadow_target.identity:
            comparison_status = 'same_target'
            fallback_reason = 'shadow_target_preferred'
        else:
            comparison_status = 'target_changed'
            origin = str(binding.get('origin') or '')
            if bool(binding.get('locked')) or origin == 'manual':
                fallback_reason = 'trusted_shadow_binding'
            elif origin == 'automatic' and binding.get('shadow_run_id'):
                fallback_reason = 'trusted_shadow_binding'
            elif origin == 'legacy_migrated':
                fallback_reason = 'migrated_target_mismatch'
            else:
                fallback_reason = 'unknown_shadow_origin'
    elif legacy_target is not None:
        comparison_status = 'legacy_only'
        fallback_reason = 'shadow_binding_unavailable'
    else:
        comparison_status = 'neither'
        fallback_reason = 'no_legacy_or_shadow_target'

    effective_target = legacy_target
    effective_source = 'legacy' if legacy_target is not None else 'none'
    if shadow_target is not None and shadow_target.readable:
        if comparison_status in {'same_target', 'shadow_only'}:
            effective_target = shadow_target
            effective_source = 'shadow'
        elif comparison_status == 'target_changed':
            origin = str((binding or {}).get('origin') or '')
            if (
                bool((binding or {}).get('locked'))
                or origin == 'manual'
                or (origin == 'automatic' and (binding or {}).get('shadow_run_id'))
            ):
                effective_target = shadow_target
                effective_source = 'shadow'

    return EpgReadResolution(
        canonical_key=canonical_key,
        logical_channel_ids=logical_ids,
        logical_channel_id=logical_channel_id,
        legacy_target=legacy_target,
        shadow_target=shadow_target,
        comparison_status=comparison_status,
        effective_target=effective_target,
        effective_source=effective_source,
        fallback_reason=fallback_reason,
        legacy_mapping=_safe_legacy_mapping(legacy_mapping),
        shadow_binding=_safe_shadow_binding(binding),
    )


def _diagnostic_payload(resolution: EpgReadResolution | Mapping[str, object], *, context: str) -> dict:
    """Build a bounded, non-sensitive payload for internal read diagnostics."""
    if isinstance(resolution, EpgReadResolution):
        data = resolution.as_dict()
    else:
        data = dict(resolution)
    legacy = data.get('legacy_target') or {}
    shadow = data.get('shadow_target') or {}
    comparison_status = str(data.get('comparison_status') or '')
    fallback_reason = str(data.get('fallback_reason') or '')
    diagnostic_status = (
        'migrated_target_mismatch'
        if fallback_reason == 'migrated_target_mismatch'
        else comparison_status
    )
    return {
        'context': context,
        'status': diagnostic_status,
        'comparison_status': comparison_status,
        'canonical_key': str(data.get('canonical_key') or ''),
        'logical_channel_id': data.get('logical_channel_id'),
        'logical_channel_count': len(data.get('logical_channel_ids') or []),
        'legacy_target': (legacy.get('source_id'), legacy.get('channel_id')) if legacy else None,
        'shadow_target': (shadow.get('source_id'), shadow.get('channel_id')) if shadow else None,
        'fallback_reason': fallback_reason,
    }

def emit_epg_read_diagnostic(
    resolution: EpgReadResolution | Mapping[str, object],
    *,
    context: str,
) -> None:
    """Emit low-noise structured diagnostics for actionable comparisons only."""
    payload = _diagnostic_payload(resolution, context=context)
    if payload['status'] in _DIAGNOSTIC_STATUSES:
        logger.warning('epg_read_shadow_diagnostic', extra={'epg_read_diagnostic': payload})

def emit_epg_read_resolver_error(*, context: str, error: BaseException) -> None:
    """Emit an error diagnostic without persisting or logging exception text."""
    payload = {
        'context': context,
        'status': 'resolver_error',
        'error_type': type(error).__name__,
    }
    logger.warning('epg_read_shadow_diagnostic', extra={'epg_read_diagnostic': payload})


async def _load_snapshot(legacy_mappings: Mapping[str, Mapping[str, object] | None] | None = None):
    if legacy_mappings is None:
        legacy_rows = await db.get_all_channel_epg_maps()
        legacy_mappings = {
            str(row.get('canonical_key') or ''): row
            for row in legacy_rows
        }
    logical_rows = await db.get_iptv_logical_channels()
    target_rows = await db.list_epg_channel_catalog_rows()
    from epg_bindings import list_epg_bindings

    bindings = [binding.as_dict() for binding in await list_epg_bindings()]
    return legacy_mappings, logical_rows, bindings, target_rows


async def resolve_epg_read(
    canonical_key: str,
    *,
    legacy_mapping: Mapping[str, object] | None | object = _UNSET,
) -> dict:
    """Resolve one production EPG read target with legacy fallback."""
    if legacy_mapping is _UNSET:
        legacy_mapping = await db.get_channel_epg_map(canonical_key)
    legacy_mappings, logical_rows, binding_rows, target_rows = await _load_snapshot({canonical_key: legacy_mapping})
    return resolve_epg_read_snapshot(
        canonical_key,
        legacy_mapping=legacy_mappings.get(canonical_key),
        logical_rows=logical_rows,
        binding_rows=binding_rows,
        target_rows=target_rows,
    ).as_dict()


async def resolve_epg_read_many(canonical_keys: Iterable[str]) -> dict[str, dict]:
    """Resolve a batch in one logical/catalog/binding snapshot."""
    keys = [str(key) for key in canonical_keys]
    legacy_rows = await db.get_all_channel_epg_maps()
    legacy_by_key = {str(row.get('canonical_key') or ''): row for row in legacy_rows}
    _, logical_rows, binding_rows, target_rows = await _load_snapshot(legacy_by_key)
    indexes = _build_snapshot_indexes(logical_rows, binding_rows, target_rows)
    return {
        key: _resolve_epg_read_indexed(
            key,
            legacy_mapping=legacy_by_key.get(key),
            indexes=indexes,
        ).as_dict()
        for key in keys
    }
