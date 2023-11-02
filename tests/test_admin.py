from app.main import app
from app.models import Admin, Config, Pipeline, Stage
from tests._common import HermesTestCase


class AdminTestCase(HermesTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # if not app.middleware_stack:
        #     # We need to call startup() to initialize the admin app, but since Tortoise's TestCase initializes the app
        #     # once for the entire test suite, we need to make sure we don't call startup() more than once.
        #     await startup()

    async def test_unauthenticated(self):
        r = await self.client.get('/')
        assert r.status_code == 200
        r = await self.client.get('admin/list')
        assert r.status_code == 401

    async def _login(self):
        await Admin.create(username='testing@example.com', password='testing', first_name='Brain', last_name='Jones')
        r = await self.client.post('/login', data={'username': 'testing@example.com', 'password': 'testing'})
        assert r.status_code == 303

    async def test_login(self):
        await Admin.create(username='testing@example.com', password='testing')
        admin = await Admin.get()
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
        r = await self.client.get('/admin/list')
        assert 'Brain' in r.text
        assert 'Jones' in r.text

    async def test_admins_create(self):
        await self._login()
        assert await Admin.all().count() == 1
        r = await self.client.get('/admin/create')
        assert r.status_code == 200
        admin_data = {
            'first_name': 'Jamie',
            'last_name': 'Small',
            'timezone': 'America/New_York',
            'username': 'jamie@example.com',
        }
        assert await Admin.all().count() == 1
        r = await self.client.post('/admin/create', data=admin_data)
        assert r.status_code == 200, r.content.decode()
        assert await Admin.all().count() == 2
        admin2 = await Admin.get(username='jamie@example.com')
        assert not admin2.password
        assert admin2.first_name == 'Jamie'
        assert admin2.last_name == 'Small'
        assert admin2.timezone == 'America/New_York'
        assert not admin2.is_sales_person
        assert not admin2.tc2_admin_id
        assert not admin2.pd_owner_id

    async def test_admins_update(self):
        await self._login()
        r = await self.client.get('/admin/list')
        assert 'Brain' in r.text
        assert 'Jones' in r.text
        admin_data = {
            'first_name': 'Jamie',
            'last_name': 'Small',
            'timezone': 'America/New_York',
            'username': 'testing@example.com',
        }
        admin = await Admin.get()
        r = await self.client.post(f'/admin/update/{admin.id}', data=admin_data)
        assert r.status_code == 303, r.content.decode()
        admin = await Admin.get()
        assert admin.first_name == 'Jamie'
        assert admin.last_name == 'Small'
        assert admin.timezone == 'America/New_York'

    async def test_admins_delete(self):
        await self._login()
        r = await self.client.get('/admin/list')
        assert 'Brain' in r.text
        assert 'Jones' in r.text
        admin2 = await Admin.create(first_name='Jamie', last_name='Small', username='testing@example.com')
        r = await self.client.delete(f'/admin/delete/{admin2.id}')
        assert r.status_code == 303, r.content.decode()
        admin = await Admin.get()
        assert admin.email == 'testing@example.com'

    async def test_config_view(self):
        await self._login()
        r = await self.client.get('/config/list')
        assert '17:30' in r.text

    async def test_config_update(self):
        await self._login()
        r = await self.client.get(f'/config/update/{self.config.id}')
        assert r.status_code == 200
        assert self.config.meeting_min_start == '10:00'
        an_other_pipeline = await Pipeline.create(name='An Other Pipeline', pd_pipeline_id='5')
        config_data = {'meeting_min_start': '10:30', 'payg_pipeline_id': an_other_pipeline.id}
        r = await self.client.post(f'/config/update/{self.config.id}', data=config_data)
        assert r.status_code == 303
        config = await Config.get()
        assert config.meeting_min_start == '10:30'
        assert await config.payg_pipeline == an_other_pipeline

    async def test_pipelines_view(self):
        await self._login()
        r = await self.client.get('/pipeline/list')
        assert r.status_code == 200
        assert 'payg' in r.text

    async def test_pipelines_update(self):
        await self._login()
        r = await self.client.get(f'/pipeline/update/{self.pipeline.id}')
        assert r.status_code == 200
        assert self.pipeline.dft_entry_stage_id == (await self.stage).id
        stage_2 = await Stage.create(name='Stage 2', pd_stage_id=2)
        data = {'name': 'Startup', 'pd_pipeline_id': '1234', 'dft_entry_stage_id': stage_2.id}
        r = await self.client.post(f'/pipeline/update/{self.pipeline.id}', data=data)
        assert r.status_code == 303
        pipeline = await Pipeline.get()
        assert pipeline.name == 'Startup'
        assert pipeline.pd_pipeline_id == 1234
        assert pipeline.dft_entry_stage_id == stage_2.id

    async def test_pipelines_stages_view(self):
        await self._login()
        r = await self.client.get('/stage/list')
        assert r.status_code == 200
        assert 'New' in r.text
