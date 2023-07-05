from httpx import AsyncClient
from tortoise.contrib.test import TestCase, finalizer, initializer

from app.main import app, settings


class HermesTestCase(TestCase):
    def setUp(self):
        initializer(['app.models'], db_url=settings.pg_dsn)
        self.client = AsyncClient(app=app, base_url='http://test')

    def tearDown(self):
        finalizer()
