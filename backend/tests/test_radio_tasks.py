from __future__ import annotations

import unittest

from radio_tasks import (
    RADIO_CATALOG_TASK_TYPE,
    RADIO_PROGRAMME_TASK_TYPE,
    create_radio_task_definition,
)


class RadioTasksTest(unittest.TestCase):
    def test_definitions_use_shared_automation_and_distinct_refresh_contracts(self):
        subsystem = object()
        catalog = create_radio_task_definition("org.waveflow/yunting", RADIO_CATALOG_TASK_TYPE, subsystem)
        programme = create_radio_task_definition("org.waveflow/yunting", RADIO_PROGRAMME_TASK_TYPE, subsystem)
        self.assertEqual(catalog.task_id, "radio_refresh:catalog:org.waveflow/yunting")
        self.assertEqual(programme.task_id, "radio_refresh:programme:org.waveflow/yunting")
        self.assertEqual(catalog.scheduled_task_type, RADIO_CATALOG_TASK_TYPE)
        self.assertEqual(programme.scheduled_task_type, RADIO_PROGRAMME_TASK_TYPE)
        self.assertTrue(catalog.allow_automatic_scheduling)
        self.assertEqual(catalog.conflict_group, programme.conflict_group)


if __name__ == "__main__":
    unittest.main()
