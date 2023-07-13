from tests._common import HermesTestCase


class AdminTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()

    async def test_unauthenticated(self, client):
        r = await client.get('/')
        assert r.status_code == 401

    async def test_login(self):
        pass

    async def test_captcha(self):
        pass

    async def test_admins_view(self):
        pass

    async def test_admins_create(self):
        pass

    async def test_admins_update(self):
        pass

    async def test_admins_delete(self):
        pass

    async def test_config_view(self):
        pass

    async def test_config_update(self):
        pass

    async def test_pipelines_view(self):
        pass

    async def test_pipelines_update(self):
        pass

    async def test_pipelines_stages_view(self):
        pass
