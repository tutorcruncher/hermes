from datetime import datetime

from app.models import Admins
from tests._common import HermesTestCase


CB_MEETING_DATA = {
    'name': 'Brain Junes',
    'start_time': '2021-01-01T00:00:00Z',
    'timezone': 'Europe/Kiev',
    'email': 'brain@junes.com',
    'company_name': 'Junes Ltd',
    'website': 'https://junes.com',
    'country': 'GB',
    'estimated_income': 1000,
    'currency': 'GBP',
    'client_manager': 20,
    'meeting_dt': int(datetime(2023, 4, 3).timestamp()),
}


class CBTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.url = '/callback/callbooker/'

    async def test_cb_working(self):
        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='daniel@tutorcruncher.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        r = await self.client.post(self.url, json=CB_MEETING_DATA)
        assert r.status_code == 200, r.json()
        assert False
