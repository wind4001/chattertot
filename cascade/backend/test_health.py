import importlib
import importlib.util
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx
import app


class HealthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('health'), 'Readiness checks are missing')
        self.health = importlib.import_module('health')

    def test_missing_and_placeholder_keys_are_reported_without_secret_values(self):
        values = {'LLM_API_KEY':'change_me','TTS_API_KEY':'secret-do-not-print','LLM_BASE_URL':'https://example.com','LLM_MODEL':'test','DB_URL':'postgresql://user:password-do-not-print@localhost/db'}
        result = self.health.check_configuration(values)
        self.assertFalse(all(item['ok'] for item in result))
        data = json.dumps(result)
        self.assertIn('LLM_API_KEY', data)
        self.assertNotIn('secret-do-not-print', data)
        self.assertNotIn('password-do-not-print', data)
        self.assertFalse(any(item['ok'] for item in self.health.check_configuration({}) if item['name']=='LLM_API_KEY'))

    async def test_model_openapi_must_contain_expected_route(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'paths':{}}))) as client:
            result = await self.health.check_model(client,'kws','http://localhost:8002/openapi.json','/detect')
        self.assertFalse(result['ok'], 'Unrelated HTTP 200 must not count as healthy KWS')

    async def test_database_errors_never_expose_connection_password(self):
        with patch.object(self.health.asyncpg,'connect',AsyncMock(side_effect=RuntimeError('postgresql://u:secret@host/db'))):
            result = await self.health.check_database()
        self.assertFalse(result['ok'])
        self.assertNotIn('secret',json.dumps(result))

    async def test_live_route_precedes_static_mount_and_identifies_workspace(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
            response=await client.get('/health/live')
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data['service'],'chattertot')
        self.assertEqual(data['project_id'],self.health.project_id())

    async def test_readiness_failure_uses_503_and_actionable_checks(self):
        report={'service':'chattertot','status':'not_ready','checks':[{'name':'kws','ok':False,'message':'未就绪','action':'启动模型服务'}]}
        with patch.object(self.health,'check_readiness',AsyncMock(return_value=report)):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app),base_url='http://test') as client:
                response=await client.get('/health/ready')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),report)


if __name__=='__main__':
    unittest.main()
