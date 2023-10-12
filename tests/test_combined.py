from unittest import mock

from app.models import Admin, Company
from app.utils import settings
from tests._common import HermesTestCase
from tests.test_pipedrive import fake_pd_request, FakePipedrive
from tests.test_tc2 import mock_tc2_request


class TestMultipleServices(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.pipedrive = FakePipedrive()

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_generate_support_link_company_doesnt_exist_get_from_tc(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = mock_tc2_request()

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        headers = {'Authorization': f'token {settings.tc2_api_key}'}
        r = await self.client.get(
            '/callbooker/support-link/generate/tc2/',
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': 10},
            headers=headers,
        )
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
