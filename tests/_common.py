import pytest
from tortoise.contrib.test import TestCase, finalizer, initializer

from app.main import settings
from app.models import PipelineStages, Pipelines, Configs


@pytest.mark.usefixtures('client')
class HermesTestCase(TestCase):
    def setUp(self) -> None:
        initializer(['app.models'], db_url=f'{settings.pg_dsn}_test')
        # self.client = AsyncClient(app=create_app(), base_url='http://test')

    # @pytest.fixture(autouse=True)
    # async def prepare_client(self, client):
    #     self.client = client

    def tearDown(self):
        finalizer()

    async def _basic_setup(self) -> None:
        # TODO: Find a way to call this everywhere
        self.pipeline_stage = await PipelineStages.create(name='New', pd_stage_id=1)
        self.pipeline = await Pipelines.create(name='payg', pd_pipeline_id=1)
        self.config = await Configs.create(
            payg_pipeline_id=self.pipeline.id,
            startup_pipeline_Id=self.pipeline.id,
            enterprise_pipeline_id=self.pipeline.id,
        )
