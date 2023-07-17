from httpx import AsyncClient
from tortoise.contrib.test import TestCase

from app.main import app
from app.models import Pipelines, PipelineStages
from app.utils import get_config


class HermesTestCase(TestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.client = AsyncClient(app=app, base_url='http://test')
        self.pipeline_stage = await PipelineStages.create(name='New', pd_stage_id=1)
        self.pipeline = await Pipelines.create(name='payg', pd_pipeline_id=1, dft_entry_stage=self.pipeline_stage)
        self.config = await get_config()
        self.config.payg_pipeline_id = self.pipeline.id
        self.config.startup_pipeline_Id = self.pipeline.id
        self.config.enterprise_pipeline_id = self.pipeline.id
        await self.config.save()
