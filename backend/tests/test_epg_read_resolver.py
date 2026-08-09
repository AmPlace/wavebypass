import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock


def _clear_modules():
    for name in (
        'main', 'epg_binding_management', 'epg_read_resolver',
        'epg_bindings', 'epg_catalog', 'epg_maintenance',
        'epg_match_shadow', 'epg_matcher',
        'iptv_channels', 'database', 'security.source_ids', 'security.secrets',
        'core.config',
    ):
        sys.modules.pop(name, None)


class EpgReadResolverTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = os.environ.get('WAVEFLOW_DB_PATH')
        self.db_path = os.path.join(self.tmpdir.name, 'waveflow.db')
        os.environ['WAVEFLOW_DB_PATH'] = self.db_path
        _clear_modules()
        self.db = importlib.import_module('database')
        self.resolver = importlib.import_module('epg_read_resolver')
        await self.db.initialize()

    async def asyncTearDown(self):
        if self.old_db_path is None:
            os.environ.pop('WAVEFLOW_DB_PATH', None)
        else:
            os.environ['WAVEFLOW_DB_PATH'] = self.old_db_path
        _clear_modules()
        self.tmpdir.cleanup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    async def _source(
        self,
        name,
        channel_id,
        *,
        status='success',
        enabled=1,
        with_programmes=True,
    ):
        source_id = await self.db.add_epg_source(name, f'https://source.example/{name}')
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc)
            now_text = now.isoformat()
            conn.execute(
                "UPDATE epg_sources SET enabled=?, last_status=?, revision=1, updated_at=? WHERE id=?",
                (enabled, status, now_text, source_id),
            )
            conn.execute(
                "INSERT INTO epg_channels(source_id, channel_id, display_names, normalized_names) VALUES(?, ?, ?, ?)",
                (source_id, channel_id, json.dumps([channel_id]), json.dumps([channel_id.lower()])),
            )
            if with_programmes:
                conn.execute(
                    "INSERT INTO epg_programs(source_id, channel_id, start, stop, title, description) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        source_id,
                        channel_id,
                        (now - timedelta(minutes=30)).isoformat(),
                        (now + timedelta(minutes=30)).isoformat(),
                        f'{name} programme',
                        f'{name} description',
                    ),
                )
                conn.execute(
                    "INSERT INTO epg_programs(source_id, channel_id, start, stop, title, description) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        source_id,
                        channel_id,
                        (now + timedelta(hours=1)).isoformat(),
                        (now + timedelta(hours=2)).isoformat(),
                        f'{name} next',
                        '',
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return source_id

    async def _logical(self, logical_id='logical-1', key='demo', status='active'):
        conn = self._connect()
        try:
            now = '2026-08-06T00:00:00+00:00'
            conn.execute(
                "INSERT INTO iptv_logical_channels(id, canonical_key, display_name, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (logical_id, key, key, status, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return logical_id

    async def _legacy(self, key, source_id=None, channel_id=None, *, status='matched'):
        await self.db.upsert_channel_epg_map(
            key,
            epg_source_id=source_id,
            epg_channel_id=channel_id,
            match_type='exact',
            confidence=90,
            match_status=status,
            match_detail='contains https://secret.invalid/token and must stay private',
            locked=1 if status == 'locked' else 0,
        )

    async def _binding(
        self,
        logical_id,
        source_id,
        channel_id='CCTV1',
        *,
        origin='manual',
        locked=False,
        shadow_run_id=None,
    ):
        bindings = importlib.import_module('epg_bindings')
        return await bindings.create_matched_epg_binding(
            logical_id,
            source_id,
            channel_id,
            match_type='exact',
            confidence=90,
            origin=origin,
            locked=locked,
            shadow_run_id=shadow_run_id,
        )

    def _binding_count(self):
        conn = self._connect()
        try:
            return conn.execute('SELECT COUNT(*) FROM iptv_logical_channel_epg_bindings').fetchone()[0]
        finally:
            conn.close()

    def _legacy_rows(self):
        conn = self._connect()
        try:
            return [tuple(row) for row in conn.execute('SELECT * FROM channel_epg_map ORDER BY canonical_key')]
        finally:
            conn.close()

    async def test_actionable_comparisons_emit_bounded_structured_diagnostics(self):
        actionable = (
            'target_changed',
            'logical_ambiguous',
            'logical_conflict',
            'shadow_orphan_target',
        )
        for status in actionable:
            with self.assertLogs('epg_read_resolver', level='WARNING') as captured:
                self.resolver.emit_epg_read_diagnostic(
                    {
                        'canonical_key': 'diagnostic-key',
                        'logical_channel_ids': ['logical-1'],
                        'logical_channel_id': 'logical-1',
                        'comparison_status': status,
                        'fallback_reason': 'legacy_target_preserved',
                        'legacy_target': {'source_id': 1, 'channel_id': 'legacy'},
                        'shadow_target': {'source_id': 2, 'channel_id': 'shadow'},
                    },
                    context='test',
                )
            record = captured.records[0]
            self.assertEqual(record.epg_read_diagnostic['status'], status)
            self.assertEqual(record.epg_read_diagnostic['context'], 'test')
            self.assertNotIn('token', captured.output[0])

        with self.assertLogs('epg_read_resolver', level='WARNING') as captured:
            self.resolver.emit_epg_read_diagnostic(
                {
                    'canonical_key': 'migrated-key',
                    'comparison_status': 'target_changed',
                    'fallback_reason': 'migrated_target_mismatch',
                    'legacy_target': {'source_id': 1, 'channel_id': 'legacy'},
                    'shadow_target': {'source_id': 2, 'channel_id': 'shadow'},
                },
                context='programme',
            )
        self.assertEqual(
            captured.records[0].epg_read_diagnostic['status'],
            'migrated_target_mismatch',
        )

        for status in ('same_target', 'neither'):
            with self.assertNoLogs('epg_read_resolver', level='WARNING'):
                self.resolver.emit_epg_read_diagnostic(
                    {'comparison_status': status},
                    context='test',
                )

    async def test_resolver_error_emits_type_only_diagnostic(self):
        with self.assertLogs('epg_read_resolver', level='WARNING') as captured:
            self.resolver.emit_epg_read_resolver_error(
                context='programme',
                error=RuntimeError('secret token must not be logged'),
            )
        record = captured.records[0]
        self.assertEqual(record.epg_read_diagnostic['status'], 'resolver_error')
        self.assertEqual(record.epg_read_diagnostic['error_type'], 'RuntimeError')
        self.assertNotIn('secret token', captured.output[0])

    async def test_batch_shadow_snapshot_loaders_are_constant_with_batch_size(self):
        bindings = importlib.import_module('epg_bindings')
        originals = {
            'legacy': self.resolver.db.get_all_channel_epg_maps,
            'logical': self.resolver.db.get_iptv_logical_channels,
            'catalog': self.resolver.db.list_epg_channel_catalog_rows,
            'bindings': bindings.list_epg_bindings,
            'policies': bindings.list_epg_binding_policies,
        }
        calls = {key: 0 for key in originals}

        async def counted(name, function, *args, **kwargs):
            calls[name] += 1
            return await function(*args, **kwargs)

        async def legacy(*args, **kwargs):
            return await counted('legacy', originals['legacy'], *args, **kwargs)

        async def logical(*args, **kwargs):
            return await counted('logical', originals['logical'], *args, **kwargs)

        async def catalog(*args, **kwargs):
            return await counted('catalog', originals['catalog'], *args, **kwargs)

        async def binding_rows(*args, **kwargs):
            return await counted('bindings', originals['bindings'], *args, **kwargs)

        async def policy_rows(*args, **kwargs):
            return await counted('policies', originals['policies'], *args, **kwargs)

        with (
            mock.patch.object(self.resolver.db, 'get_all_channel_epg_maps', legacy),
            mock.patch.object(self.resolver.db, 'get_iptv_logical_channels', logical),
            mock.patch.object(self.resolver.db, 'list_epg_channel_catalog_rows', catalog),
            mock.patch.object(bindings, 'list_epg_bindings', binding_rows),
            mock.patch.object(bindings, 'list_epg_binding_policies', policy_rows),
        ):
            await self.resolver.resolve_epg_read_many(['key-1', 'key-2'])
            small_batch_calls = dict(calls)
            await self.resolver.resolve_epg_read_many([f'key-{index}' for index in range(20)])

        self.assertEqual(small_batch_calls, {
            'legacy': 1, 'logical': 1, 'catalog': 1, 'bindings': 1,
            'policies': 1,
        })
        self.assertEqual(calls, {
            'legacy': 2, 'logical': 2, 'catalog': 2, 'bindings': 2,
            'policies': 2,
        })

    async def test_pure_same_target_uses_composite_identity(self):
        target = {'source_id': 1, 'channel_id': 'same', 'source_enabled': 1, 'source_status': 'success'}
        result = self.resolver.resolve_epg_read_snapshot(
            'demo',
            legacy_mapping={
                'canonical_key': 'demo', 'epg_source_id': 1, 'epg_channel_id': 'same',
                'match_status': 'matched', 'match_detail': 'secret https://invalid/token',
            },
            logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'}],
            binding_rows=[{'logical_channel_id': 'logical-1', 'epg_source_id': 1, 'epg_channel_id': 'same', 'status': 'matched'}],
            target_rows=[target],
        )
        self.assertEqual(result.comparison_status, 'same_target')
        self.assertEqual(result.effective_target.identity, result.legacy_target.identity)
        self.assertEqual(result.effective_source, 'shadow')

    async def test_explicit_no_epg_suppresses_shadow_and_legacy_targets(self):
        result = self.resolver.resolve_epg_read_snapshot(
            'demo',
            legacy_mapping={
                'canonical_key': 'demo',
                'epg_source_id': 1,
                'epg_channel_id': 'legacy',
            },
            logical_rows=[{
                'id': 'logical-1',
                'canonical_key': 'demo',
                'status': 'active',
            }],
            binding_rows=[{
                'logical_channel_id': 'logical-1',
                'epg_source_id': 2,
                'epg_channel_id': 'shadow',
                'status': 'matched',
                'origin': 'manual',
                'locked': 1,
            }],
            target_rows=[
                {
                    'source_id': 1,
                    'channel_id': 'legacy',
                    'source_enabled': 1,
                    'source_status': 'success',
                },
                {
                    'source_id': 2,
                    'channel_id': 'shadow',
                    'source_enabled': 1,
                    'source_status': 'success',
                },
            ],
            policy_rows=[{
                'logical_channel_id': 'logical-1',
                'mode': 'no_epg',
            }],
        )

        self.assertEqual(result.comparison_status, 'not_applicable')
        self.assertEqual(result.management_mode, 'no_epg')
        self.assertEqual(result.fallback_reason, 'explicit_no_epg')
        self.assertIsNone(result.effective_target)
        self.assertEqual(result.effective_source, 'none')

    async def test_explicit_automatic_without_binding_does_not_remigrate_legacy_read(self):
        result = self.resolver.resolve_epg_read_snapshot(
            'demo',
            legacy_mapping={
                'canonical_key': 'demo',
                'epg_source_id': 1,
                'epg_channel_id': 'legacy',
            },
            logical_rows=[{
                'id': 'logical-1',
                'canonical_key': 'demo',
                'status': 'active',
            }],
            binding_rows=[],
            target_rows=[{
                'source_id': 1,
                'channel_id': 'legacy',
                'source_enabled': 1,
                'source_status': 'success',
            }],
            policy_rows=[{
                'logical_channel_id': 'logical-1',
                'mode': 'automatic',
            }],
        )

        self.assertEqual(result.comparison_status, 'legacy_only')
        self.assertEqual(result.management_mode, 'automatic')
        self.assertEqual(
            result.fallback_reason,
            'explicit_automatic_without_shadow',
        )
        self.assertIsNone(result.effective_target)
        self.assertEqual(result.effective_source, 'none')

    async def test_explicit_automatic_still_reads_current_shadow_binding(self):
        result = self.resolver.resolve_epg_read_snapshot(
            'demo',
            legacy_mapping=None,
            logical_rows=[{
                'id': 'logical-1',
                'canonical_key': 'demo',
                'status': 'active',
            }],
            binding_rows=[{
                'logical_channel_id': 'logical-1',
                'epg_source_id': 2,
                'epg_channel_id': 'shadow',
                'status': 'matched',
                'origin': 'automatic',
                'shadow_run_id': 'run-1',
            }],
            target_rows=[{
                'source_id': 2,
                'channel_id': 'shadow',
                'source_enabled': 0,
                'source_status': 'failed',
            }],
            policy_rows=[{
                'logical_channel_id': 'logical-1',
                'mode': 'automatic',
            }],
        )

        self.assertEqual(result.comparison_status, 'shadow_only')
        self.assertEqual(result.management_mode, 'automatic')
        self.assertEqual(result.effective_source, 'shadow')
        self.assertEqual(result.effective_target.identity.source_id, 2)
        self.assertNotIn('secret', repr(result.as_dict()))

    async def test_composite_target_changed_when_bare_channel_id_matches(self):
        result = self.resolver.resolve_epg_read_snapshot(
            'demo',
            legacy_mapping={'canonical_key': 'demo', 'epg_source_id': 1, 'epg_channel_id': 'same', 'match_status': 'matched'},
            logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'}],
            binding_rows=[{'logical_channel_id': 'logical-1', 'epg_source_id': 2, 'epg_channel_id': 'same', 'status': 'matched'}],
            target_rows=[
                {'source_id': 1, 'channel_id': 'same', 'source_enabled': 1, 'source_status': 'success'},
                {'source_id': 2, 'channel_id': 'same', 'source_enabled': 1, 'source_status': 'success'},
            ],
        )
        self.assertEqual(result.comparison_status, 'target_changed')
        self.assertNotEqual(result.legacy_target.identity, result.shadow_target.identity)
        self.assertEqual(result.effective_target.identity.source_id, 1)
        self.assertEqual(result.effective_source, 'legacy')

    async def test_legacy_shadow_and_neither_categories(self):
        target = {'source_id': 1, 'channel_id': 'one', 'source_enabled': 1, 'source_status': 'success'}
        base = dict(
            logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'}],
            binding_rows=[],
            target_rows=[target],
        )
        legacy_only = self.resolver.resolve_epg_read_snapshot(
            'demo', legacy_mapping={'canonical_key': 'demo', 'epg_source_id': 1, 'epg_channel_id': 'one'}, **base
        )
        neither = self.resolver.resolve_epg_read_snapshot('demo', legacy_mapping=None, **base)
        shadow_only = self.resolver.resolve_epg_read_snapshot(
            'demo', legacy_mapping=None,
            logical_rows=base['logical_rows'],
            binding_rows=[{'logical_channel_id': 'logical-1', 'epg_source_id': 1, 'epg_channel_id': 'one', 'status': 'matched'}],
            target_rows=base['target_rows'],
        )
        self.assertEqual(legacy_only.comparison_status, 'legacy_only')
        self.assertEqual(legacy_only.effective_source, 'legacy')
        self.assertEqual(neither.comparison_status, 'neither')
        self.assertEqual(neither.effective_source, 'none')
        self.assertEqual(shadow_only.comparison_status, 'shadow_only')
        self.assertEqual(shadow_only.effective_source, 'shadow')
        self.assertEqual(shadow_only.effective_target.identity.source_id, 1)
        self.assertEqual(shadow_only.effective_target.identity.channel_id, 'one')

    async def test_logical_missing_ambiguous_and_conflict_do_not_use_shadow(self):
        target = {'source_id': 1, 'channel_id': 'one', 'source_enabled': 1, 'source_status': 'success'}
        common = dict(
            legacy_mapping={'canonical_key': 'demo', 'epg_source_id': 1, 'epg_channel_id': 'one'},
            binding_rows=[{'logical_channel_id': 'logical-1', 'epg_source_id': 1, 'epg_channel_id': 'one', 'status': 'matched'}],
            target_rows=[target],
        )
        missing = self.resolver.resolve_epg_read_snapshot('demo', logical_rows=[], **common)
        ambiguous = self.resolver.resolve_epg_read_snapshot(
            'demo', logical_rows=[
                {'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'},
                {'id': 'logical-2', 'canonical_key': 'demo', 'status': 'active'},
            ], **common
        )
        conflict = self.resolver.resolve_epg_read_snapshot(
            'demo', logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'merge_conflict'}], **common
        )
        self.assertEqual(missing.comparison_status, 'logical_missing')
        self.assertEqual(ambiguous.comparison_status, 'logical_ambiguous')
        self.assertEqual(conflict.comparison_status, 'logical_conflict')
        self.assertIsNone(conflict.shadow_target)

    async def test_shadow_orphan_target_and_stale_disabled_failed_are_readable(self):
        common = dict(
            legacy_mapping={'canonical_key': 'demo', 'epg_source_id': 1, 'epg_channel_id': 'legacy'},
            logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'}],
            binding_rows=[{
                'logical_channel_id': 'logical-1',
                'epg_source_id': 2,
                'epg_channel_id': 'shadow',
                'status': 'matched',
                'origin': 'manual',
            }],
        )
        orphan = self.resolver.resolve_epg_read_snapshot('demo', target_rows=[], **common)
        self.assertEqual(orphan.comparison_status, 'shadow_orphan_target')
        self.assertEqual(orphan.effective_target.identity.source_id, 1)
        for status, enabled in (('stale', 1), ('failed', 1), ('disabled', 0)):
            result = self.resolver.resolve_epg_read_snapshot(
                'demo',
                target_rows=[
                    {'source_id': 1, 'channel_id': 'legacy', 'source_enabled': 1, 'source_status': 'success'},
                    {'source_id': 2, 'channel_id': 'shadow', 'source_enabled': enabled, 'source_status': status},
                ],
                **common,
            )
            self.assertEqual(result.comparison_status, 'target_changed')
            self.assertTrue(result.shadow_target.exists)
            self.assertTrue(result.shadow_target.readable)
            self.assertEqual(result.shadow_target.source_status, status)
            self.assertEqual(result.effective_target.identity.source_id, 2)
            self.assertEqual(result.effective_source, 'shadow')

    async def test_target_changed_origin_policy_is_explicit(self):
        base = dict(
            legacy_mapping={
                'canonical_key': 'demo',
                'epg_source_id': 1,
                'epg_channel_id': 'legacy',
                'match_status': 'matched',
            },
            logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'}],
            target_rows=[
                {'source_id': 1, 'channel_id': 'legacy', 'source_status': 'success'},
                {'source_id': 2, 'channel_id': 'shadow', 'source_status': 'success'},
            ],
        )
        cases = (
            ({'origin': 'manual'}, 'shadow', 'trusted_shadow_binding'),
            ({'locked': 1, 'origin': 'legacy_migrated'}, 'shadow', 'trusted_shadow_binding'),
            ({'origin': 'automatic', 'shadow_run_id': 'run-1'}, 'shadow', 'trusted_shadow_binding'),
            ({'origin': 'legacy_migrated'}, 'legacy', 'migrated_target_mismatch'),
            ({'origin': 'unknown'}, 'legacy', 'unknown_shadow_origin'),
        )
        for binding_extra, expected_source, expected_reason in cases:
            binding = {
                'logical_channel_id': 'logical-1',
                'epg_source_id': 2,
                'epg_channel_id': 'shadow',
                'status': 'matched',
                **binding_extra,
            }
            result = self.resolver.resolve_epg_read_snapshot(
                'demo', binding_rows=[binding], **base
            )
            self.assertEqual(result.comparison_status, 'target_changed')
            self.assertEqual(result.effective_source, expected_source)
            self.assertEqual(result.fallback_reason, expected_reason)

    async def test_non_matched_shadow_binding_is_not_readable(self):
        target = {'source_id': 1, 'channel_id': 'one', 'source_enabled': 1, 'source_status': 'success'}
        result = self.resolver.resolve_epg_read_snapshot(
            'demo',
            legacy_mapping={'canonical_key': 'demo', 'epg_source_id': 1, 'epg_channel_id': 'one'},
            logical_rows=[{'id': 'logical-1', 'canonical_key': 'demo', 'status': 'active'}],
            binding_rows=[{'logical_channel_id': 'logical-1', 'epg_source_id': 1, 'epg_channel_id': 'one', 'status': 'conflict'}],
            target_rows=[target],
        )
        self.assertEqual(result.comparison_status, 'legacy_only')
        self.assertIsNone(result.shadow_target)

    async def test_empty_shadow_tables_and_missing_logical_projection_are_legacy_compatible(self):
        source = await self._source('legacy-only', 'LEGACY')
        await self._legacy('legacy-key', source, 'LEGACY')
        result = await self.resolver.resolve_epg_read('legacy-key')
        self.assertEqual(result['comparison_status'], 'logical_missing')
        self.assertEqual(result['effective_target']['source_id'], source)
        self.assertEqual(self._binding_count(), 0)

    async def test_programme_path_uses_trusted_shadow_target_when_changed(self):
        legacy_source = await self._source('legacy-programme', 'LEGACY')
        shadow_source = await self._source('shadow-programme', 'SHADOW')
        await self._legacy('programme-key', legacy_source, 'LEGACY')
        logical_id = await self._logical(key='programme-key')
        await self._binding(logical_id, shadow_source, 'SHADOW')
        main = importlib.import_module('main')
        requested_date = datetime.now(timezone.utc).date().isoformat()
        response = await main.get_epg_programs('programme-key', date=requested_date, tz='UTC')
        self.assertEqual(response['epg_source_id'], shadow_source)
        self.assertEqual(response['epg_channel_id'], 'SHADOW')
        self.assertEqual(response['current']['title'], 'shadow-programme programme')
        self.assertEqual(set(response), {
            'canonical_key', 'epg_source_id', 'epg_channel_id', 'match_status',
            'current', 'next', 'programs', 'date', 'requested_date', 'tz', 'available_dates',
        })

    async def test_programme_resolver_exception_falls_back_to_legacy(self):
        source = await self._source('legacy-fallback', 'LEGACY')
        await self._legacy('fallback-key', source, 'LEGACY')
        main = importlib.import_module('main')
        requested_date = datetime.now(timezone.utc).date().isoformat()
        with self.assertLogs('epg_read_resolver', level='WARNING') as captured:
            with mock.patch.object(
                main.epg_read_resolver,
                'resolve_epg_read',
                side_effect=RuntimeError('diagnostic failure'),
            ):
                response = await main.get_epg_programs('fallback-key', date=requested_date, tz='UTC')
        self.assertEqual(captured.records[0].epg_read_diagnostic['status'], 'resolver_error')
        self.assertEqual(response['epg_source_id'], source)
        self.assertEqual(response['epg_channel_id'], 'LEGACY')
        self.assertEqual(response['current']['title'], 'legacy-fallback programme')

    async def test_batch_current_uses_trusted_shadow_and_keeps_shape(self):
        legacy_source = await self._source('legacy-batch', 'LEGACY')
        shadow_source = await self._source('shadow-batch', 'SHADOW')
        await self._legacy('batch-key', legacy_source, 'LEGACY')
        logical_id = await self._logical(key='batch-key')
        await self._binding(logical_id, shadow_source, 'SHADOW')
        result = await self.db.batch_get_current_programs(['batch-key', 'missing-key'])
        self.assertEqual(result['batch-key']['current']['title'], 'shadow-batch programme')
        self.assertIsNone(result['missing-key'])
        self.assertEqual(set(result['batch-key']), {'current', 'next'})
        self.assertEqual(
            set(result['batch-key']['current']),
            {'title', 'start', 'stop', 'description'},
        )
        self.assertEqual(
            set(result['batch-key']['next']),
            {'title', 'start', 'stop'},
        )

    async def test_batch_current_program_queries_are_batched_not_per_channel(self):
        for index in range(20):
            source_id = await self._source(f'batch-scale-{index}', f'CHANNEL-{index}')
            await self._legacy(f'batch-scale-key-{index}', source_id, f'CHANNEL-{index}')
            await self._logical(
                logical_id=f'batch-scale-logical-{index}',
                key=f'batch-scale-key-{index}',
            )
            await self._binding(
                f'batch-scale-logical-{index}', source_id, f'CHANNEL-{index}',
            )

        original_connect = self.db._connect

        def run_with_trace(keys):
            statements = []

            def traced_connect():
                conn = original_connect()
                conn.set_trace_callback(statements.append)
                return conn

            async def run():
                with mock.patch.object(self.db, '_connect', side_effect=traced_connect):
                    result = await self.db.batch_get_current_programs(keys)
                return result

            return statements, run()

        small_statements, small_run = run_with_trace(['batch-scale-key-0'])
        await small_run
        large_keys = [f'batch-scale-key-{index}' for index in range(20)]
        large_statements, large_run = run_with_trace(large_keys)
        result = await large_run

        small_selects = [sql for sql in small_statements if sql.lstrip().upper().startswith('SELECT')]
        large_selects = [sql for sql in large_statements if sql.lstrip().upper().startswith('SELECT')]
        self.assertEqual(len(small_selects), len(large_selects))
        self.assertEqual(
            sum('FROM epg_programs' in sql for sql in small_selects),
            1,
        )
        self.assertEqual(
            sum('FROM epg_programs' in sql for sql in large_selects),
            1,
        )
        self.assertEqual(
            [result[key]['current']['title'] for key in large_keys],
            [f'batch-scale-{index} programme' for index in range(20)],
        )

    async def test_batch_resolver_exception_falls_back_and_does_not_write(self):
        source = await self._source('batch-fallback', 'LEGACY')
        await self._legacy('batch-fallback-key', source, 'LEGACY')
        before_legacy = self._legacy_rows()
        before_binding_count = self._binding_count()
        resolver = importlib.import_module('epg_read_resolver')
        with self.assertLogs('epg_read_resolver', level='WARNING') as captured:
            with mock.patch.object(
                resolver,
                'resolve_epg_read_many',
                side_effect=RuntimeError('diagnostic failure'),
            ):
                result = await self.db.batch_get_current_programs(['batch-fallback-key'])
        self.assertEqual(captured.records[0].epg_read_diagnostic['status'], 'resolver_error')
        self.assertEqual(result['batch-fallback-key']['current']['title'], 'batch-fallback programme')
        self.assertEqual(self._legacy_rows(), before_legacy)
        self.assertEqual(self._binding_count(), before_binding_count)

    async def test_batch_resolver_exception_chunks_legacy_key_fallback(self):
        source = await self._source('batch-large-fallback', 'LEGACY')
        keys = [f'batch-large-fallback-key-{index}' for index in range(801)]
        await self._legacy(keys[-1], source, 'LEGACY')
        statements = []
        original_connect = self.db._connect

        def traced_connect():
            conn = original_connect()
            conn.set_trace_callback(statements.append)
            return conn

        with mock.patch.object(self.db, '_connect', side_effect=traced_connect), \
             mock.patch.object(
                 self.resolver,
                 'resolve_epg_read_many',
                 side_effect=RuntimeError('snapshot failed'),
             ):
            result = await self.db.batch_get_current_programs(keys)

        legacy_selects = [sql for sql in statements if 'FROM channel_epg_map' in sql]
        self.assertEqual(len(legacy_selects), 2)
        self.assertEqual(result[keys[-1]]['current']['title'], 'batch-large-fallback programme')

    async def test_read_comparison_does_not_write_bindings_or_legacy_mapping(self):
        source = await self._source('readonly', 'READONLY')
        await self._legacy('readonly-key', source, 'READONLY')
        logical_id = await self._logical(key='readonly-key')
        await self._binding(logical_id, source, 'READONLY')
        before_legacy = self._legacy_rows()
        before_binding_count = self._binding_count()
        await self.resolver.resolve_epg_read('readonly-key')
        await self.resolver.resolve_epg_read_many(['readonly-key'])
        self.assertEqual(self._legacy_rows(), before_legacy)
        self.assertEqual(self._binding_count(), before_binding_count)


if __name__ == '__main__':
    unittest.main()
