import unittest
from unittest.mock import AsyncMock, patch

import setup_database


class DatabaseSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_configured_database_without_removing_data(self):
        connection = AsyncMock()
        with patch.object(setup_database.asyncpg, 'connect', AsyncMock(return_value=connection)) as connect:
            await setup_database.initialize_database('postgresql://custom/target')
        self.assertEqual(connect.call_args.args[0], 'postgresql://custom/target')
        sql = connection.execute.call_args.args[0].upper()
        self.assertIn('CREATE TABLE IF NOT EXISTS MESSAGES', sql)
        self.assertNotIn('DROP TABLE', sql)
        self.assertNotIn('TRUNCATE', sql)
        connection.close.assert_awaited_once()
