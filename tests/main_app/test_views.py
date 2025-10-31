"""
Tests for core Hermes endpoints.
"""

from unittest.mock import patch

from app.main_app.models import Admin, Company


class TestRoundRobinEndpoints:
    """Test round-robin assignment endpoints"""

    async def test_choose_sales_person_for_payg_gb(self, client, db, test_admin):
        """Test choosing sales person for PAYG GB company"""
        test_admin.sells_payg = True
        test_admin.sells_gb = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'GB'})

        assert r.status_code == 200
        assert r.json() == {
            'id': test_admin.id,
            'first_name': 'Test',
            'last_name': 'Admin',
            'email': 'test@example.com',
            'tc2_admin_id': 1,
            'pd_owner_id': 1,
        }

    async def test_choose_sales_person_round_robin(self, client, db, test_admin):
        """Test that round-robin cycles through admins"""
        admin1 = db.create(
            Admin(
                first_name='Admin',
                last_name='One',
                username='admin1@example.com',
                tc2_admin_id=2,
                pd_owner_id=2,
                is_sales_person=True,
                sells_payg=True,
                sells_gb=True,
            )
        )
        admin2 = db.create(
            Admin(
                first_name='Admin',
                last_name='Two',
                username='admin2@example.com',
                tc2_admin_id=3,
                pd_owner_id=3,
                is_sales_person=True,
                sells_payg=True,
                sells_gb=True,
            )
        )

        db.create(Company(name='Latest Company', sales_person_id=admin1.id, price_plan='payg', country='GB'))

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'GB'})

        assert r.status_code == 200
        data = r.json()
        assert data['id'] == admin2.id

    async def test_choose_sales_person_round_robin_missing_person(self, client, db):
        """Test round robin when current person is missing from list"""
        admin_1 = db.create(
            Admin(
                first_name='Admin1',
                last_name='Test',
                username='admin1@example.com',
                is_sales_person=True,
                sells_payg=True,
                sells_gb=True,
            )
        )
        db.create(
            Admin(
                first_name='Admin2',
                last_name='Test',
                username='admin2@example.com',
                is_sales_person=True,
                sells_payg=True,
                sells_gb=True,
            )
        )

        # Create a company with a sales person that no longer exists or is not active
        db.create(
            Company(
                name='Test Company',
                price_plan='payg',
                sales_person_id=999,  # Non-existent admin
            )
        )

        # Should start from the beginning of the list
        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'GB'})

        assert r.status_code == 200
        assert r.json()['id'] == admin_1.id

    async def test_choose_sales_person_invalid_plan(self, client):
        """Test that invalid plan returns 422"""
        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'invalid', 'country_code': 'GB'})

        assert r.status_code == 422

    async def test_choose_sales_person_startup_plan(self, client, db, test_admin):
        """Test choosing sales person for startup plan"""
        test_admin.is_sales_person = True
        test_admin.sells_startup = True
        test_admin.sells_gb = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'startup', 'country_code': 'GB'})

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_enterprise_plan(self, client, db, test_admin):
        """Test choosing sales person for enterprise plan"""
        test_admin.is_sales_person = True
        test_admin.sells_enterprise = True
        test_admin.sells_gb = True
        db.add(test_admin)
        db.commit()

        r = client.get(
            client.app.url_path_for('choose-sales-person'), params={'plan': 'enterprise', 'country_code': 'GB'}
        )

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_us_region(self, client, db, test_admin):
        """Test choosing sales person for US region"""
        test_admin.is_sales_person = True
        test_admin.sells_payg = True
        test_admin.sells_us = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'US'})

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_au_region(self, client, db, test_admin):
        """Test choosing sales person for AU region"""
        test_admin.is_sales_person = True
        test_admin.sells_payg = True
        test_admin.sells_au = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'AU'})

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_ca_region(self, client, db, test_admin):
        """Test choosing sales person for CA region"""
        test_admin.is_sales_person = True
        test_admin.sells_payg = True
        test_admin.sells_ca = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'CA'})

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_eu_region(self, client, db, test_admin):
        """Test choosing sales person for EU region (France)"""
        test_admin.is_sales_person = True
        test_admin.sells_payg = True
        test_admin.sells_eu = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'FR'})

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_row_region(self, client, db, test_admin):
        """Test choosing sales person for rest of world region"""
        test_admin.is_sales_person = True
        test_admin.sells_payg = True
        test_admin.sells_row = True
        db.add(test_admin)
        db.commit()

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'JP'})

        assert r.status_code == 200
        assert r.json()['id'] == test_admin.id

    async def test_choose_sales_person_no_regional_admins_fallback(self, client, db):
        """Test choosing sales person falls back to all admins when no regional admins"""
        # Create admin who sells payg but not in the requested region
        admin = db.create(
            Admin(
                first_name='Global',
                last_name='Admin',
                username='global@example.com',
                is_sales_person=True,
                sells_payg=True,
                sells_gb=True,  # Only sells in GB, not US
            )
        )

        # Request for US region should still return the admin (fallback)
        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'US'})

        assert r.status_code == 200
        assert r.json()['id'] == admin.id

    async def test_choose_sales_person_no_admins_at_all(self, client, db):
        """Test that 404 is returned when no admins exist"""
        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'GB'})

        assert r.status_code == 404

    async def test_choose_support_person(self, client, db):
        """Test choosing support person"""
        admin = db.create(
            Admin(
                first_name='Support',
                last_name='Person',
                username='support@example.com',
                tc2_admin_id=10,
                pd_owner_id=10,
                is_support_person=True,
            )
        )

        r = client.get(client.app.url_path_for('choose-support-person'))

        assert r.status_code == 200
        assert r.json() == {
            'id': admin.id,
            'first_name': 'Support',
            'last_name': 'Person',
            'email': 'support@example.com',
            'tc2_admin_id': 10,
            'pd_owner_id': 10,
        }

    async def test_choose_support_person_no_admins(self, client, db):
        """Test choosing support person when none exist"""
        r = client.get(client.app.url_path_for('choose-support-person'))

        assert r.status_code == 404

    async def test_choose_support_person_round_robin(self, client, db):
        """Test support person round robin assignment"""
        admin1 = db.create(
            Admin(
                first_name='Support1',
                last_name='Admin',
                username='support1@example.com',
                is_support_person=True,
            )
        )
        admin2 = db.create(
            Admin(
                first_name='Support2',
                last_name='Admin',
                username='support2@example.com',
                is_support_person=True,
            )
        )

        # First call should return admin1
        response1 = client.get(client.app.url_path_for('choose-support-person'))
        assert response1.status_code == 200
        assert response1.json()['id'] == admin1.id

        # Create a company with admin1 as support
        db.create(Company(name='Test', sales_person_id=admin1.id, support_person_id=admin1.id))

        # Second call should return admin2
        response2 = client.get(client.app.url_path_for('choose-support-person'))
        assert response2.status_code == 200
        assert response2.json()['id'] == admin2.id

    async def test_choose_support_person_round_robin_wrap_around(self, client, db):
        """Test support person round robin wraps around to first admin"""
        admin1 = db.create(
            Admin(first_name='Support1', last_name='Admin', username='support1@example.com', is_support_person=True)
        )
        admin2 = db.create(
            Admin(first_name='Support2', last_name='Admin', username='support2@example.com', is_support_person=True)
        )

        # Create a company with admin2 as support (last in list)
        db.create(Company(name='Test', sales_person_id=admin1.id, support_person_id=admin2.id))

        # Next call should wrap around to admin1
        r = client.get(client.app.url_path_for('choose-support-person'))
        assert r.status_code == 200
        assert r.json()['id'] == admin1.id


class TestLocationEndpoint:
    """Test location/country code endpoint"""

    def test_get_country_returns_cloudflare_header(self, client):
        """Test that location endpoint returns Cloudflare country header"""
        r = client.get(client.app.url_path_for('get-country-code'), headers={'cf-ipcountry': 'US'})

        assert r.status_code == 200
        assert r.json() == {'country_code': 'US'}

    def test_get_country_defaults_to_gb(self, client):
        """Test that location endpoint defaults to GB"""
        r = client.get(client.app.url_path_for('get-country-code'))

        assert r.status_code == 200
        assert r.json() == {'country_code': 'GB'}


class TestCompanySearchEndpoint:
    """Test company search endpoint"""

    async def test_get_companies_by_name(self, client, db, test_admin):
        """Test getting companies by name"""
        db.create(Company(name='Alpha Company', sales_person_id=test_admin.id, price_plan='payg'))
        db.create(Company(name='Beta Company', sales_person_id=test_admin.id, price_plan='startup'))

        r = client.get(client.app.url_path_for('get-companies'), params={'name': 'Alpha Company'})

        assert r.status_code == 200
        companies = r.json()
        assert len(companies) == 1
        assert companies[0]['name'] == 'Alpha Company'

    async def test_get_companies_requires_params(self, client):
        """Test that companies endpoint requires at least one parameter"""
        r = client.get(client.app.url_path_for('get-companies'))

        assert r.status_code == 422

    async def test_get_companies_limits_to_10(self, client, db, test_admin):
        """Test that companies endpoint limits results to 10"""
        for i in range(15):
            db.create(Company(name=f'Company {i}', sales_person_id=test_admin.id, price_plan='payg', country='US'))

        r = client.get(client.app.url_path_for('get-companies'), params={'country': 'US'})

        assert r.status_code == 200
        companies = r.json()
        assert len(companies) == 10

    @patch('app.main_app.views.get_next_sales_person')
    async def test_choose_sales_person_admin_not_found_edge_case(self, mock_get_next, client, db, test_admin):
        """Test edge case where get_next_sales_person returns ID that doesn't exist"""
        test_admin.sells_payg = True
        test_admin.sells_gb = True
        db.add(test_admin)
        db.commit()

        # Mock to return non-existent admin ID
        mock_get_next.return_value = 999

        r = client.get(client.app.url_path_for('choose-sales-person'), params={'plan': 'payg', 'country_code': 'GB'})

        assert r.status_code == 404
