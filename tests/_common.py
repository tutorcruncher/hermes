from httpx import AsyncClient, ASGITransport
from tortoise.contrib.test import TestCase

from app.main import app
from app.models import Pipeline, Stage
from app.utils import get_config, settings


class HermesTestCase(TestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        settings.testing = True
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')
        self.stage = await Stage.create(name='New', pd_stage_id=1)
        self.pipeline = await Pipeline.create(name='payg', pd_pipeline_id=1, dft_entry_stage=self.stage)
        self.config = await get_config()
        self.config.payg_pipeline_id = self.pipeline.id
        self.config.startup_pipeline_id = self.pipeline.id
        self.config.enterprise_pipeline_id = self.pipeline.id
        await self.config.save()
