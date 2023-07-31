from app.models import Admin, Company
from tests._common import HermesTestCase


class SalesPersonDeciderTestCase(HermesTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.url = '/choose-sales-person/'
        sp_kwargs = {'is_sales_person': True, 'sells_payg': True, 'sells_startup': True}
        self.admin_1 = await Admin.create(last_name='1', username='admin_1@example.com', **sp_kwargs)
        self.admin_2 = await Admin.create(last_name='2', username='admin_2@example.com', **sp_kwargs)
        self.admin_3 = await Admin.create(last_name='3', username='admin_3@example.com', **sp_kwargs)
        self.admin_enterprise = await Admin.create(
            last_name='enterprise', username='enterprise@example.com', is_sales_person=True, sells_enterprise=True
        )

    async def test_no_companies(self):
        r = await self.client.get(self.url + '?plan=payg')
        assert r.status_code == 200
        assert r.json() == {'admin_id': self.admin_1.id}

    async def test_payg_round_robin(self):
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', price_plan='payg', sales_person=self.admin_1
        )
        r = await self.client.get(self.url + '?plan=payg')
        assert r.status_code == 200
        assert r.json() == {'admin_id': self.admin_2.id}
        company.sales_person = self.admin_2
        await company.save()
        r = await self.client.get(self.url + '?plan=payg')
        assert r.json() == {'admin_id': self.admin_3.id}
        company.sales_person = self.admin_3
        await company.save()
        r = await self.client.get(self.url + '?plan=payg')
        assert r.json() == {'admin_id': self.admin_1.id}

    async def test_startup(self):
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', price_plan='startup', sales_person=self.admin_1
        )
        r = await self.client.get(self.url + '?plan=startup')
        assert r.status_code == 200
        assert r.json() == {'admin_id': self.admin_2.id}
        company.sales_person = self.admin_2
        await company.save()
        r = await self.client.get(self.url + '?plan=startup')
        assert r.json() == {'admin_id': self.admin_3.id}
        company.sales_person = self.admin_3
        await company.save()
        r = await self.client.get(self.url + '?plan=startup')
        assert r.json() == {'admin_id': self.admin_1.id}

    async def test_enterprise(self):
        company = await Company.create(
            name='Junes Ltd',
            website='https://junes.com',
            country='GB',
            price_plan='enterprise',
            sales_person=self.admin_1,
        )
        r = await self.client.get(self.url + '?plan=enterprise')
        assert r.status_code == 200
        assert r.json() == {'admin_id': self.admin_enterprise.id}
        company.sales_person = self.admin_enterprise
        await company.save()
        r = await self.client.get(self.url + '?plan=enterprise')
        assert r.json() == {'admin_id': self.admin_enterprise.id}

    async def test_invalid_plan(self):
        r = await self.client.get(self.url + '?plan=foobar')
        assert r.status_code == 422
        assert r.json() == {'detail': 'Price plan must be one of "payg,startup,enterprise"'}
