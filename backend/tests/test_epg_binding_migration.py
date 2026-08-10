import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


def _clear_modules():
    for name in ('epg_bindings', 'epg_catalog', 'iptv_channels', 'database'):
        sys.modules.pop(name, None)


class EpgBindingMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = os.environ.get('WAVEFLOW_DB_PATH')
        self.db_path = os.path.join(self.tmpdir.name, 'waveflow.db')
        os.environ['WAVEFLOW_DB_PATH'] = self.db_path
        _clear_modules()
        self.db = importlib.import_module('database')
        self.catalog = importlib.import_module('epg_catalog')
        self.bindings = importlib.import_module('epg_bindings')
        self.iptv = importlib.import_module('iptv_channels')
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

    @staticmethod
    def _channel(channel_id, *names):
        return {
            'channel_id': channel_id,
            'display_names': json.dumps(names or (channel_id,), ensure_ascii=False),
            'normalized_names': json.dumps([name.lower() for name in (names or (channel_id,))], ensure_ascii=False),
        }

    @staticmethod
    def _stats(channel_count=1, programme_count=0):
        return {
            'channel_count': channel_count,
            'programme_count': programme_count,
            'data_start_at': '2026-08-06T00:00:00+00:00',
            'data_end_at': '2026-08-06T01:00:00+00:00',
            'finished_at': '2026-08-06T00:05:00+00:00',
        }

    async def _seed_source(self, name, url, channel_id='CCTV1'):
        source_id = await self.db.add_epg_source(name, url)
        source = await self.db.get_epg_source(source_id)
        await self.db.replace_epg_dataset_atomic(
            source_id,
            source['revision'],
            [self._channel(channel_id, channel_id)],
            [],
            stats=self._stats(),
        )
        return source_id

    async def _seed_logical(self, canonical_key='cctv1', display_name='CCTV1'):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO iptv_logical_channels(id, canonical_key, display_name, status, created_at, updated_at) VALUES(?, ?, ?, 'active', ?, ?)",
                ('lc-test-' + canonical_key, canonical_key, display_name, '2026-08-06T00:00:00+00:00', '2026-08-06T00:00:00+00:00'),
            )
            conn.commit()
        finally:
            conn.close()
        return 'lc-test-' + canonical_key

    async def _seed_logical_via_projection(self, name='CCTV1'):
        sub_id = await self.db.add_subscription('test', 'https://example.test/test.m3u')
        await self.db.add_channels_bulk(sub_id, [{
            'name': name,
            'url': 'https://stream.example/live',
            'group_name': 'test',
            'logo_url': '',
            'tvg_id': '',
            'tvg_name': '',
        }])
        await self.iptv.sync_iptv_logical_channels()
        return (await self.db.get_iptv_logical_channels())[0]

    async def _legacy(self, canonical_key, source_id=None, channel_id=None, *, status='matched', confidence=90, locked=0, match_type='exact'):
        kwargs = {
            'match_type': match_type,
            'confidence': confidence,
            'match_status': status,
            'match_detail': 'test detail https://secret.invalid/token',
            'locked': locked,
        }
        if source_id is not None:
            kwargs['epg_source_id'] = source_id
        if channel_id is not None:
            kwargs['epg_channel_id'] = channel_id
        await self.db.upsert_channel_epg_map(canonical_key, **kwargs)

    async def test_schema_is_idempotent_and_enforces_one_binding_per_logical(self):
        await self.db.initialize()
        await self.db.initialize()
        conn = self._connect()
        try:
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(iptv_logical_channel_epg_bindings)')}
            indexes = {row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            foreign_tables = {
                row['table'] for row in conn.execute('PRAGMA foreign_key_list(iptv_logical_channel_epg_bindings)')
            }
        finally:
            conn.close()
        self.assertTrue({'logical_channel_id', 'epg_source_id', 'epg_channel_id', 'status', 'origin'}.issubset(columns))
        self.assertIn('idx_iptv_logical_epg_bindings_target', indexes)
        self.assertIn('idx_iptv_logical_epg_bindings_status', indexes)
        self.assertEqual(foreign_tables, {'iptv_logical_channels'})

        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        logical_id = await self._seed_logical()
        first = await self.bindings.create_matched_epg_binding(logical_id, source_id, 'CCTV1')
        self.assertEqual(first.target, self.catalog.EpgChannelIdentity(source_id, 'CCTV1'))
        with self.assertRaises(ValueError):
            await self.bindings.create_matched_epg_binding(logical_id, source_id, 'CCTV1')
        with self.assertRaises(ValueError):
            await self.bindings.create_matched_epg_binding('missing', source_id, 'CCTV1')

    async def test_repository_validates_composite_target_and_persists_metadata(self):
        source_a = await self._seed_source('A', 'https://a.example/epg.xml', 'CCTV1')
        source_b = await self._seed_source('B', 'https://b.example/epg.xml', 'CCTV1')
        logical_id = await self._seed_logical()
        self.assertTrue(await self.bindings.validate_epg_binding_target(source_a, 'CCTV1'))
        self.assertFalse(await self.bindings.validate_epg_binding_target(source_a, 'missing'))
        with self.assertRaises(ValueError):
            await self.bindings.create_matched_epg_binding(logical_id, source_a, 'missing')
        binding = await self.bindings.create_matched_epg_binding(
            logical_id, source_b, 'CCTV1', match_type='manual', confidence=77,
            locked=True, origin='legacy_migrated', legacy_canonical_key='old-key',
        )
        self.assertEqual(binding.epg_source_id, source_b)
        self.assertEqual(binding.epg_channel_id, 'CCTV1')
        self.assertEqual(binding.match_type, 'manual')
        self.assertEqual(binding.confidence, 77)
        self.assertTrue(binding.locked)
        self.assertEqual(binding.origin, 'legacy_migrated')
        self.assertEqual(binding.legacy_canonical_key, 'old-key')
        self.assertNotIn('url', repr(binding.as_dict()))

    async def test_preview_classifies_unknown_key_invalid_target_and_unmatched(self):
        source_id = await self._seed_source('source', 'https://secret.example/epg.xml')
        await self._seed_logical('known', 'Known')
        await self._legacy('known', source_id, 'CCTV1', status='matched')
        await self._legacy('unknown', source_id, 'CCTV1', status='matched')
        await self._legacy('invalid', source_id, None, status='matched')
        await self._legacy('unmatched', None, None, status='unmatched')
        preview = await self.bindings.preview_legacy_epg_binding_migration()
        reasons = {record['canonical_key']: record['reason'] for record in preview['records']}
        self.assertEqual(reasons, {
            'known': 'eligible',
            'unknown': 'orphan_key',
            'invalid': 'legacy_unmatched',
            'unmatched': 'legacy_unmatched',
        })
        self.assertEqual(preview['eligible_count'], 1)
        self.assertEqual(preview['orphan_key_count'], 1)
        self.assertEqual(preview['legacy_unmatched_count'], 2)
        self.assertNotIn('secret.example', repr(preview))
        self.assertNotIn('token', repr(preview))

    async def test_pure_classifier_covers_ambiguous_duplicate_and_conflicting_targets(self):
        target_a = self.catalog.EpgChannelIdentity(1, 'A')
        target_b = self.catalog.EpgChannelIdentity(2, 'B')
        logical_rows = [
            {'id': 'lc-a', 'canonical_key': 'a', 'status': 'active'},
            {'id': 'lc-b', 'canonical_key': 'b', 'status': 'active'},
        ]
        legacy_rows = [
            {'id': 1, 'canonical_key': 'a', 'epg_source_id': 1, 'epg_channel_id': 'A', 'match_status': 'matched', 'locked': 0, 'confidence': 80, 'match_type': 'exact'},
            {'id': 2, 'canonical_key': 'b', 'epg_source_id': 1, 'epg_channel_id': 'A', 'match_status': 'matched', 'locked': 0, 'confidence': 70, 'match_type': 'exact'},
        ]
        records = self.bindings._classify_legacy_records(legacy_rows, logical_rows, {target_a})
        self.assertEqual([row['reason'] for row in records], ['eligible', 'eligible'])
        # Two records for one logical channel are only possible in synthetic input
        # (the legacy table itself has a unique canonical key); this verifies the
        # conservative fold logic independently from SQLite constraints.
        same_logical_rows = [
            {'id': 'lc-a', 'canonical_key': 'a', 'status': 'active'},
            {'id': 'lc-a', 'canonical_key': 'b', 'status': 'active'},
        ]
        same_logical_legacy = [
            dict(legacy_rows[0]),
            dict(legacy_rows[1], **{'epg_source_id': 1, 'epg_channel_id': 'A'}),
        ]
        records = self.bindings._classify_legacy_records(same_logical_legacy, same_logical_rows, {target_a})
        self.assertEqual([row['reason'] for row in records], ['eligible', 'duplicate_same_target'])
        same_logical_legacy[1]['epg_source_id'] = target_b.source_id
        same_logical_legacy[1]['epg_channel_id'] = target_b.channel_id
        records = self.bindings._classify_legacy_records(same_logical_legacy, same_logical_rows, {target_a, target_b})
        self.assertEqual({row['reason'] for row in records}, {'conflicting_target'})

        ambiguous_rows = [
            {'id': 'lc-a', 'canonical_key': 'a', 'status': 'active'},
            {'id': 'lc-b', 'canonical_key': 'a', 'status': 'active'},
        ]
        records = self.bindings._classify_legacy_records([legacy_rows[0]], ambiguous_rows, {target_a})
        self.assertEqual(records[0]['reason'], 'ambiguous_logical')
        active_with_orphan = [
            {'id': 'lc-a', 'canonical_key': 'a', 'status': 'active'},
            {'id': 'lc-old', 'canonical_key': 'a', 'status': 'orphaned'},
        ]
        records = self.bindings._classify_legacy_records([legacy_rows[0]], active_with_orphan, {target_a})
        self.assertEqual(records[0]['reason'], 'eligible')

    async def test_migration_is_conservative_idempotent_and_does_not_touch_legacy(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        logical = await self._seed_logical('known', 'Known')
        await self._legacy('known', source_id, 'CCTV1', confidence=88, locked=0, match_type='exact')
        before = await self.db.get_all_channel_epg_maps()
        first = await self.bindings.migrate_legacy_epg_bindings_shadow()
        second = await self.bindings.migrate_legacy_epg_bindings_shadow()
        self.assertEqual(first['created_count'], 1)
        self.assertEqual(second['created_count'], 0)
        self.assertEqual(second['already_migrated_count'], 1)
        self.assertEqual(await self.db.get_all_channel_epg_maps(), before)
        binding = await self.bindings.get_epg_binding(logical)
        self.assertEqual(binding.origin, 'legacy_migrated')
        self.assertEqual(binding.confidence, 88)
        self.assertFalse(binding.locked)
        self.assertEqual(binding.match_type, 'exact')

    async def test_legacy_fallback_with_active_and_orphan_identity_uses_active_first(self):
        source_id = await self._seed_source(
            'source', 'https://source.example/epg.xml', 'CCTV1'
        )
        logical_id = await self._seed_logical('known', 'Known')
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO iptv_logical_channels(
                    id, canonical_key, display_name, status, created_at, updated_at
                ) VALUES('lc-old-known', 'known', 'Known history', 'orphaned', ?, ?)
                """,
                ('2026-08-06T00:00:00+00:00', '2026-08-06T00:00:00+00:00'),
            )
            conn.commit()
        finally:
            conn.close()
        await self._legacy('known', source_id, 'CCTV1')
        before = await self.db.get_all_channel_epg_maps()

        preview = await self.bindings.preview_legacy_epg_binding_migration()
        result = await self.bindings.migrate_legacy_epg_bindings_shadow()

        self.assertEqual(preview['eligible_count'], 1)
        self.assertEqual(result['created_count'], 1)
        self.assertEqual((await self.bindings.get_epg_binding(logical_id)).logical_channel_id, logical_id)
        self.assertEqual(await self.db.get_all_channel_epg_maps(), before)

    async def test_active_first_allows_multiple_orphans_but_rejects_active_conflicts(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        logical_id = await self._seed_logical('known', 'Known')
        conn = self._connect()
        try:
            for index, status in enumerate(('orphaned', 'orphaned')):
                conn.execute(
                    "INSERT INTO iptv_logical_channels(id, canonical_key, display_name, status, created_at, updated_at) VALUES(?, 'known', ?, ?, ?, ?)",
                    (f'lc-old-known-{index}', f'Known history {index}', status, '2026-08-06T00:00:00+00:00', '2026-08-06T00:00:00+00:00'),
                )
            conn.commit()
        finally:
            conn.close()
        await self._legacy('known', source_id, 'CCTV1')
        records = await self.bindings.preview_legacy_epg_binding_migration()
        self.assertEqual(records['eligible_count'], 1)

        conn = self._connect()
        try:
            conn.execute("UPDATE iptv_logical_channels SET status='active' WHERE id='lc-old-known-0'")
            conn.commit()
        finally:
            conn.close()
        records = await self.bindings.preview_legacy_epg_binding_migration()
        self.assertEqual(records['eligible_count'], 0)
        self.assertEqual(records['ambiguous_logical_count'], 1)

    async def test_active_conflict_missing_target_and_no_epg_are_refused(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        logical_id = await self._seed_logical('known', 'Known')
        await self._legacy('known', source_id, 'MISSING')
        self.assertEqual((await self.bindings.preview_legacy_epg_binding_migration())['eligible_count'], 0)
        await self.bindings.set_epg_binding_management_mode(logical_id, 'no_epg')
        self.assertEqual((await self.bindings.preview_legacy_epg_binding_migration())['eligible_count'], 0)

    async def test_automatic_policy_does_not_suppress_legacy_migration(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        logical_id = await self._seed_logical('known', 'Known')
        await self.bindings.set_epg_binding_management_mode(logical_id, 'automatic')
        await self._legacy('known', source_id, 'CCTV1')
        preview = await self.bindings.preview_legacy_epg_binding_migration()
        self.assertEqual(preview['eligible_count'], 1)
        result = await self.bindings.migrate_legacy_epg_bindings_shadow()
        self.assertEqual(result['created_count'], 1)

    async def test_locked_or_manual_legacy_intent_is_not_bootstrapped(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        await self._seed_logical('locked', 'Locked')
        await self._legacy('locked', source_id, 'CCTV1', locked=1, match_type='manual')
        preview = await self.bindings.preview_legacy_epg_binding_migration()
        self.assertEqual(preview['eligible_count'], 0)
        self.assertEqual(preview['management_policy_count'], 1)

    async def test_existing_binding_different_target_is_never_overwritten(self):
        source_a = await self._seed_source('A', 'https://a.example/epg.xml', 'A')
        source_b = await self._seed_source('B', 'https://b.example/epg.xml', 'B')
        logical = await self._seed_logical('known', 'Known')
        await self.bindings.create_matched_epg_binding(logical, source_a, 'A', locked=True)
        await self._legacy('known', source_b, 'B')
        result = await self.bindings.migrate_legacy_epg_bindings_shadow()
        self.assertEqual(result['created_count'], 0)
        self.assertEqual(result['locked_conflict_count'], 1)
        current = await self.bindings.get_epg_binding(logical)
        self.assertEqual(current.target, self.catalog.EpgChannelIdentity(source_a, 'A'))

        await self.bindings.delete_epg_binding(logical)
        await self.bindings.create_matched_epg_binding(logical, source_a, 'A', locked=False)
        result = await self.bindings.migrate_legacy_epg_bindings_shadow()
        self.assertEqual(result['existing_conflict_count'], 1)
        self.assertEqual((await self.bindings.get_epg_binding(logical)).target, self.catalog.EpgChannelIdentity(source_a, 'A'))

    async def test_migration_rolls_back_all_writes_on_database_failure(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        await self._seed_logical('one', 'One')
        await self._seed_logical('two', 'Two')
        await self._legacy('one', source_id, 'CCTV1')
        await self._legacy('two', source_id, 'CCTV1')
        original = self.bindings._target_exists
        calls = 0

        def fail_on_second(conn, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('synthetic database failure')
            return original(conn, target)

        with mock.patch.object(self.bindings, '_target_exists', side_effect=fail_on_second):
            with self.assertRaises(RuntimeError):
                await self.bindings.migrate_legacy_epg_bindings_shadow()
        self.assertEqual(await self.bindings.list_epg_bindings(), [])

    async def test_refresh_stale_delete_and_recover_preserve_binding_and_composite_source(self):
        source_a = await self._seed_source('A', 'https://a.example/epg.xml', 'CCTV1')
        source_b = await self._seed_source('B', 'https://b.example/epg.xml', 'CCTV1')
        logical = await self._seed_logical()
        binding = await self.bindings.create_matched_epg_binding(logical, source_a, 'CCTV1')
        source = await self.db.get_epg_source(source_a)
        await self.db.replace_epg_dataset_atomic(source_a, source['revision'], [self._channel('CCTV1')], [], stats=self._stats())
        self.assertEqual((await self.bindings.get_epg_binding(logical)).id, binding.id)
        current = await self.db.get_epg_source(source_a)
        await self.db.record_epg_source_refresh_failure(source_a, current['revision'], status='stale', attempted_at='2026-08-06T02:00:00+00:00', error='timeout')
        self.assertEqual((await self.bindings.get_epg_binding(logical)).target.source_id, source_a)
        current = await self.db.get_epg_source(source_a)
        await self.db.replace_epg_dataset_atomic(source_a, current['revision'], [], [], stats=self._stats(0, 0))
        validation = await self.bindings.validate_epg_binding_shadow()
        self.assertEqual(validation['orphan_target_count'], 1)
        self.assertEqual(validation['cross_source_resolution_errors'], 1)
        self.assertEqual((await self.bindings.list_orphan_target_bindings())[0].target.source_id, source_a)
        current = await self.db.get_epg_source(source_a)
        await self.db.replace_epg_dataset_atomic(source_a, current['revision'], [self._channel('CCTV1')], [], stats=self._stats())
        validation = await self.bindings.validate_epg_binding_shadow()
        self.assertEqual(validation['valid_target_count'], 1)
        self.assertEqual(validation['orphan_target_count'], 0)
        self.assertEqual((await self.bindings.get_epg_binding(logical)).target.source_id, source_a)
        self.assertNotEqual(source_a, source_b)

    async def test_orphaned_and_conflict_logicals_keep_or_reject_bindings(self):
        source_id = await self._seed_source('source', 'https://source.example/epg.xml')
        logical = await self._seed_logical('known', 'Known')
        binding = await self.bindings.create_matched_epg_binding(logical, source_id, 'CCTV1')
        conn = self._connect()
        try:
            conn.execute("UPDATE iptv_logical_channels SET status='orphaned' WHERE id=?", (logical,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual((await self.bindings.get_epg_binding(logical)).id, binding.id)
        conflict = await self._seed_logical('conflict', 'Conflict')
        conn = self._connect()
        try:
            conn.execute("UPDATE iptv_logical_channels SET status='split_conflict' WHERE id=?", (conflict,))
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(ValueError):
            await self.bindings.create_matched_epg_binding(conflict, source_id, 'CCTV1')
        validation = await self.bindings.validate_epg_binding_shadow()
        self.assertEqual(validation['logical_orphan_count'], 1)
        self.assertEqual(validation['conflict_count'], 0)

    async def test_validation_counts_locked_migrated_and_safe_orphan_samples(self):
        source_id = await self._seed_source('source', 'https://secret.example/epg.xml')
        logical = await self._seed_logical('known', 'Known')
        await self.bindings.create_matched_epg_binding(logical, source_id, 'CCTV1', locked=True, origin='legacy_migrated')
        result = await self.bindings.validate_epg_binding_shadow()
        self.assertEqual(result['binding_count'], 1)
        self.assertEqual(result['valid_target_count'], 1)
        self.assertEqual(result['locked_count'], 1)
        self.assertEqual(result['migrated_count'], 1)
        self.assertEqual(result['duplicate_logical_binding_count'], 0)
        self.assertNotIn('secret.example', repr(result))


if __name__ == '__main__':
    unittest.main()
