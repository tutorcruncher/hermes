from app.models import Admin, Company
from tests._common import HermesTestCase


class SalesPersonDeciderTestCase(HermesTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.url = '/choose-roundrobin/sales/'
        sp_kwargs = {'is_sales_person': True, 'sells_payg': True, 'sells_startup': True, 'sells_gb': True}
        self.admin_1 = await Admin.create(last_name='1', username='admin_1@example.com', tc2_admin_id=10, **sp_kwargs)
        self.admin_2 = await Admin.create(last_name='2', username='admin_2@example.com', tc2_admin_id=20, **sp_kwargs)
        self.admin_3 = await Admin.create(last_name='3', username='admin_3@example.com', tc2_admin_id=30, **sp_kwargs)
        self.admin_enterprise = await Admin.create(
            last_name='enterprise',
            username='enterprise@example.com',
            is_sales_person=True,
            sells_enterprise=True,
            sells_gb=True,
            sells_us=True,
            sells_au=True,
            sells_ca=True,
            sells_eu=True,
            sells_row=True,
            tc2_admin_id=40,
        )
        self.admin_payg_us = await Admin.create(
            last_name='us',
            username='us-payg@example.com',
            is_sales_person=True,
            sells_payg=True,
            sells_us=True,
            tc2_admin_id=50,
        )
        self.admin_payg_ca = await Admin.create(
            last_name='ca',
            username='ca-payg@example.com',
            is_sales_person=True,
            sells_payg=True,
            sells_ca=True,
            tc2_admin_id=60,
        )
        self.admin_startup_eu = await Admin.create(
            last_name='eu',
            username='eu-startup@example.com',
            is_sales_person=True,
            sells_startup=True,
            sells_eu=True,
            tc2_admin_id=70,
        )
        self.admin_startup_au = await Admin.create(
            last_name='au',
            username='au-startup@example.com',
            is_sales_person=True,
            sells_startup=True,
            sells_au=True,
            tc2_admin_id=80,
        )
        self.admin_startup_row = await Admin.create(
            last_name='row',
            username='row-startup@example.com',
            is_sales_person=True,
            sells_startup=True,
            sells_row=True,
            tc2_admin_id=90,
        )

    async def test_no_companies(self):
        r = await self.client.get(self.url + '?plan=payg&country_code=GB')
        assert r.status_code == 200
        assert r.json() == {
            'username': 'admin_1@example.com',
            'id': self.admin_1.id,
            'tc2_admin_id': 10,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '1',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        r = await self.client.get(self.url + '?plan=payg&country_code=US')
        assert r.json() == {
            'username': 'us-payg@example.com',
            'id': self.admin_payg_us.id,
            'tc2_admin_id': 50,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'us',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': False,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': True,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        r = await self.client.get(self.url + '?plan=payg&country_code=CA')
        assert r.json() == {
            'username': 'ca-payg@example.com',
            'id': self.admin_payg_ca.id,
            'tc2_admin_id': 60,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'ca',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': False,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': True,
            'sells_eu': False,
            'sells_row': False,
        }
        r = await self.client.get(self.url + '?plan=startup&country_code=FR')
        assert r.json() == {
            'username': 'eu-startup@example.com',
            'id': self.admin_startup_eu.id,
            'tc2_admin_id': 70,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'eu',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': True,
            'sells_row': False,
        }
        r = await self.client.get(self.url + '?plan=startup&country_code=AU')
        assert r.json() == {
            'username': 'au-startup@example.com',
            'id': self.admin_startup_au.id,
            'tc2_admin_id': 80,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'au',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': True,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        r = await self.client.get(self.url + '?plan=startup&country_code=JP')
        assert r.json() == {
            'username': 'row-startup@example.com',
            'id': self.admin_startup_row.id,
            'tc2_admin_id': 90,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'row',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': True,
        }

    async def test_no_companies_no_regional_admin(self):
        admin = await Admin.all()
        for a in admin:
            a.sells_gb = False
            a.sells_us = False
            a.sells_au = False
            a.sells_ca = False
            a.sells_eu = False
            a.sells_row = False
            await a.save()

        r = await self.client.get(self.url + '?plan=payg&country_code=GB')
        assert r.status_code == 200
        assert r.json() == {
            'username': 'admin_1@example.com',
            'id': self.admin_1.id,
            'tc2_admin_id': 10,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '1',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }

    async def test_payg_round_robin(self):
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', price_plan='payg', sales_person=self.admin_1
        )
        r = await self.client.get(self.url + '?plan=payg&country_code=GB')
        assert r.status_code == 200
        assert r.json() == {
            'username': 'admin_2@example.com',
            'id': self.admin_2.id,
            'tc2_admin_id': 20,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '2',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        company.sales_person = self.admin_2
        await company.save()
        r = await self.client.get(self.url + '?plan=payg&country_code=GB')
        assert r.json() == {
            'username': 'admin_3@example.com',
            'id': self.admin_3.id,
            'tc2_admin_id': 30,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '3',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        company.sales_person = self.admin_3
        await company.save()
        r = await self.client.get(self.url + '?plan=payg&country_code=GB')
        assert r.json() == {
            'username': 'admin_1@example.com',
            'id': self.admin_1.id,
            'tc2_admin_id': 10,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '1',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }

    async def test_startup(self):
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', price_plan='startup', sales_person=self.admin_1
        )
        r = await self.client.get(self.url + '?plan=startup&country_code=GB')
        assert r.status_code == 200
        assert r.json() == {
            'username': 'admin_2@example.com',
            'id': self.admin_2.id,
            'tc2_admin_id': 20,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '2',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        company.sales_person = self.admin_2
        await company.save()
        r = await self.client.get(self.url + '?plan=startup&country_code=GB')
        assert r.json() == {
            'username': 'admin_3@example.com',
            'id': self.admin_3.id,
            'tc2_admin_id': 30,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '3',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        company.sales_person = self.admin_3
        await company.save()
        r = await self.client.get(self.url + '?plan=startup&country_code=GB')
        assert r.json() == {
            'username': 'admin_1@example.com',
            'id': self.admin_1.id,
            'tc2_admin_id': 10,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '1',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': True,
            'sells_startup': True,
            'sells_enterprise': False,
            'sells_gb': True,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }

    async def test_enterprise(self):
        company = await Company.create(
            name='Junes Ltd',
            website='https://junes.com',
            country='GB',
            price_plan='enterprise',
            sales_person=self.admin_1,
        )
        r = await self.client.get(self.url + '?plan=enterprise&country_code=GB')
        assert r.status_code == 200
        assert r.json() == {
            'username': 'enterprise@example.com',
            'id': self.admin_enterprise.id,
            'tc2_admin_id': 40,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'enterprise',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': True,
            'sells_gb': True,
            'sells_us': True,
            'sells_au': True,
            'sells_ca': True,
            'sells_eu': True,
            'sells_row': True,
        }
        company.sales_person = self.admin_enterprise
        await company.save()
        r = await self.client.get(self.url + '?plan=enterprise&country_code=US')
        assert r.json() == {
            'username': 'enterprise@example.com',
            'id': self.admin_enterprise.id,
            'tc2_admin_id': 40,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': 'enterprise',
            'timezone': 'Europe/London',
            'is_sales_person': True,
            'is_support_person': False,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': True,
            'sells_gb': True,
            'sells_us': True,
            'sells_au': True,
            'sells_ca': True,
            'sells_eu': True,
            'sells_row': True,
        }

    async def test_invalid_plan(self):
        r = await self.client.get(self.url + '?plan=foobar&country_code=GB')
        assert r.status_code == 422
        assert r.json() == {'detail': 'Price plan must be one of "payg,startup,enterprise"'}

    async def test_no_country_code(self):
        r = await self.client.get(self.url + '?plan=payg')
        assert r.status_code == 422


class SupportPersonDeciderTestCase(HermesTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.url = '/choose-roundrobin/support/'
        self.admin_1 = await Admin.create(
            last_name='1', username='admin_1@example.com', tc2_admin_id=10, is_support_person=True
        )
        self.admin_2 = await Admin.create(
            last_name='2', username='admin_2@example.com', tc2_admin_id=20, is_support_person=True
        )
        self.admin_3 = await Admin.create(
            last_name='3', username='admin_3@example.com', tc2_admin_id=30, is_support_person=True
        )

    async def test_no_companies(self):
        r = await self.client.get(self.url)
        assert r.status_code == 200
        assert r.json() == {
            'username': 'admin_1@example.com',
            'id': self.admin_1.id,
            'tc2_admin_id': 10,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '1',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': True,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }

    async def test_support_round_robin(self):
        company = await Company.create(
            name='Junes Ltd',
            website='https://junes.com',
            country='GB',
            sales_person=self.admin_1,
            support_person=self.admin_1,
        )
        r = await self.client.get(self.url)
        assert r.status_code == 200, r.json()
        assert r.json() == {
            'username': 'admin_2@example.com',
            'id': self.admin_2.id,
            'tc2_admin_id': 20,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '2',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': True,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        company.support_person = self.admin_2
        await company.save()
        r = await self.client.get(self.url)
        assert r.json() == {
            'username': 'admin_3@example.com',
            'id': self.admin_3.id,
            'tc2_admin_id': 30,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '3',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': True,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }
        company.support_person = self.admin_3
        await company.save()
        r = await self.client.get(self.url)
        assert r.json() == {
            'username': 'admin_1@example.com',
            'id': self.admin_1.id,
            'tc2_admin_id': 10,
            'pd_owner_id': None,
            'first_name': '',
            'last_name': '1',
            'timezone': 'Europe/London',
            'is_sales_person': False,
            'is_support_person': True,
            'is_bdr_person': False,
            'sells_payg': False,
            'sells_startup': False,
            'sells_enterprise': False,
            'sells_gb': False,
            'sells_us': False,
            'sells_au': False,
            'sells_ca': False,
            'sells_eu': False,
            'sells_row': False,
        }


class CountryTestCase(HermesTestCase):
    def setUp(self) -> None:
        self.url = '/loc/'

    async def test_country(self):
        r = await self.client.get(self.url, headers={'CF-IPCountry': 'US'})
        assert r.status_code == 200
        assert r.json() == {'country_code': 'US'}

        r = await self.client.get(self.url)
        assert r.status_code == 200
        assert r.json() == {'country_code': 'GB'}


class GetCompaniesTestCase(HermesTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.url = '/companies/'
        self.admin = await Admin.create(
            last_name='1', username='admin_1@example.com', tc2_admin_id=10, is_support_person=True
        )

    async def test_get_companies_no_kwargs(self):
        r = await self.client.get(self.url)
        assert r.status_code == 422

    async def test_get_companies_by_id(self):
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', sales_person_id=self.admin.id
        )
        r = await self.client.get(self.url + f'?id={company.id}')

        assert r.json() == [
            {
                'id': company.id,
                'name': 'Junes Ltd',
                'tc2_agency_id': None,
                'tc2_cligency_id': None,
                'tc2_status': 'pending_email_conf',
                'pd_org_id': None,
                'created': company.created.isoformat().replace('+00:00', 'Z'),
                'price_plan': 'payg',
                'country': 'GB',
                'custom_field_values': [],
                'deals': [],
                'contacts': [],
                'bdr_person': None,
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'estimated_income': None,
                'currency': None,
                'has_booked_call': False,
                'has_signed_up': False,
                'utm_campaign': None,
                'utm_source': None,
                'narc': False,
                'signup_questionnaire': None,
                'sales_person': {
                    'username': 'admin_1@example.com',
                    'password': None,
                    'id': self.admin.id,
                    'tc2_admin_id': self.admin.tc2_admin_id,
                    'pd_owner_id': None,
                    'first_name': '',
                    'last_name': '1',
                    'timezone': 'Europe/London',
                    'is_sales_person': False,
                    'is_support_person': True,
                    'is_bdr_person': False,
                    'sells_payg': False,
                    'sells_startup': False,
                    'sells_enterprise': False,
                    'sells_gb': False,
                    'sells_us': False,
                    'sells_au': False,
                    'sells_ca': False,
                    'sells_eu': False,
                    'sells_row': False,
                    'deals': [],
                    'meetings': [],
                },
                'support_person': None,
            },
        ]

    async def test_get_companies_by_tc2_id(self):
        company = await Company.create(
            name='Junes Ltd',
            website='https://junes.com',
            country='GB',
            tc2_agency_id=123,
            sales_person_id=self.admin.id,
        )
        r = await self.client.get(self.url + '?tc2_agency_id=123')
        assert r.json() == [
            {
                'id': company.id,
                'name': 'Junes Ltd',
                'tc2_agency_id': 123,
                'tc2_cligency_id': None,
                'tc2_status': 'pending_email_conf',
                'pd_org_id': None,
                'created': company.created.isoformat().replace('+00:00', 'Z'),
                'price_plan': 'payg',
                'country': 'GB',
                'custom_field_values': [],
                'deals': [],
                'contacts': [],
                'bdr_person': None,
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'estimated_income': None,
                'currency': None,
                'has_booked_call': False,
                'has_signed_up': False,
                'utm_campaign': None,
                'utm_source': None,
                'narc': False,
                'signup_questionnaire': None,
                'sales_person': {
                    'username': 'admin_1@example.com',
                    'password': None,
                    'id': self.admin.id,
                    'tc2_admin_id': self.admin.tc2_admin_id,
                    'pd_owner_id': None,
                    'first_name': '',
                    'last_name': '1',
                    'timezone': 'Europe/London',
                    'is_sales_person': False,
                    'is_support_person': True,
                    'is_bdr_person': False,
                    'sells_payg': False,
                    'sells_startup': False,
                    'sells_enterprise': False,
                    'sells_gb': False,
                    'sells_us': False,
                    'sells_au': False,
                    'sells_ca': False,
                    'sells_eu': False,
                    'sells_row': False,
                    'deals': [],
                    'meetings': [],
                },
                'support_person': None,
            },
        ]
