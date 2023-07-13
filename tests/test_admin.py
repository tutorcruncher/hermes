from app.main import app
from app.models import Admins, Configs, Pipelines, PipelineStages
from tests._common import HermesTestCase


class AdminTestCase(HermesTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await app.router.on_startup[1]()

    async def test_unauthenticated(self):
        r = await self.client.get('/')
        assert r.status_code == 200
        r = await self.client.get('admins/list')
        assert r.status_code == 401

    async def _login(self):
        await Admins.create(username='testing@example.com', password='testing', first_name='Brain', last_name='Jones')
        r = await self.client.post('/login', data={'username': 'testing@example.com', 'password': 'testing'})
        assert r.status_code == 303

    async def test_login(self):
        await Admins.create(username='testing@example.com', password='testing')
        admin = await Admins.get()
        assert admin.password != 'testing'
        r = await self.client.get('/')
        assert 'testing@example.com' not in r.text

        r = await self.client.post('/login', data={'username': 'testing@example.com', 'password': 'foo'})
        assert r.status_code == 401
        r = await self.client.get('/')
        assert 'testing@example.com' not in r.text

        r = await self.client.post('/login', data={'username': 'testing@example.com', 'password': 'testing'})
        assert r.status_code == 303
        r = await self.client.get('/')
        assert 'testing@example.com' in r.text

    async def test_admins_view(self):
        await self._login()
        r = await self.client.get('/admins/list')
        assert 'Brain' in r.text
        assert 'Jones' in r.text

    async def test_admins_create(self):
        await self._login()
        assert await Admins.all().count() == 1
        r = await self.client.get('/admins/create')
        assert r.status_code == 200
        admin_data = {
            'first_name': 'Jamie',
            'last_name': 'Small',
            'timezone': 'America/New_York',
            'username': 'jamie@example.com',
        }
        assert await Admins.all().count() == 1
        r = await self.client.post('/admins/create', data=admin_data)
        assert r.status_code == 200, r.content.decode()
        assert await Admins.all().count() == 2
        admin2 = await Admins.get(username='jamie@example.com')
        assert not admin2.password
        assert admin2.first_name == 'Jamie'
        assert admin2.last_name == 'Small'
        assert admin2.timezone == 'America/New_York'
        assert not admin2.is_sales_person
        assert not admin2.tc_admin_id
        assert not admin2.pd_owner_id

    async def test_admins_update(self):
        await self._login()
        r = await self.client.get('/admins/list')
        assert 'Brain' in r.text
        assert 'Jones' in r.text
        admin_data = {
            'first_name': 'Jamie',
            'last_name': 'Small',
            'timezone': 'America/New_York',
            'username': 'testing@example.com',
        }
        admin = await Admins.get()
        r = await self.client.post(f'/admins/update/{admin.id}', data=admin_data)
        assert r.status_code == 303, r.content.decode()
        admin = await Admins.get()
        assert admin.first_name == 'Jamie'
        assert admin.last_name == 'Small'
        assert admin.timezone == 'America/New_York'

    async def test_admins_delete(self):
        await self._login()
        r = await self.client.get('/admins/list')
        assert 'Brain' in r.text
        assert 'Jones' in r.text
        admin2 = await Admins.create(first_name='Jamie', last_name='Small', username='testing@example.com')
        r = await self.client.delete(f'/admins/delete/{admin2.id}')
        assert r.status_code == 303, r.content.decode()
        admin = await Admins.get()
        assert admin.email == 'testing@example.com'

    async def test_config_view(self):
        await self._login()
        r = await self.client.get('/configs/list')
        assert '17:30' in r.text

    async def test_config_update(self):
        await self._login()
        r = await self.client.get(f'/configs/update/{self.config.id}')
        assert r.status_code == 200
        assert self.config.meeting_min_start == '10:00'
        config_data = {
            'meeting_min_start': '10:30',
            'payg_pipeline': 4,
        }
        r = await self.client.post(f'/configs/update/{self.config.id}', data=config_data)
        assert r.status_code == 303
        config = await Configs.get()
        assert config.meeting_min_start == '10:30'

    async def test_pipelines_view(self):
        await self._login()
        r = await self.client.get('/pipelines/list')
        assert r.status_code == 200
        assert 'payg' in r.text

    async def test_pipelines_update(self):
        await self._login()
        r = await self.client.get(f'/pipelines/update/{self.pipeline.id}')
        assert r.status_code == 200
        assert self.pipeline.dft_entry_stage_id == (await self.pipeline_stage).id
        stage_2 = await PipelineStages.create(name='Stage 2', pd_stage_id=1)
        data = {'name': 'Pay As You Go', 'pd_pipeline_id': '1234', 'dft_entry_stage': stage_2.id}
        r = await self.client.post(f'/pipelines/update/{self.pipeline.id}', data=data)
        assert r.status_code == 303
        pipeline = await Pipelines.get()
        assert pipeline.name == 'Pay As You Go'
        assert pipeline.pd_pipeline_id == 1234
        assert pipeline.dft_entry_stage_id == stage_2.id

    async def test_pipelines_stages_view(self):
        await self._login()
        r = await self.client.get('/pipelinestages/list')
        assert r.status_code == 200
        assert 'New' in r.text
