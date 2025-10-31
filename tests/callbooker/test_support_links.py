"""
Tests for support link generation and validation.
"""

import re
from datetime import datetime, timedelta
from unittest.mock import patch

from app.common.utils import sign_args
from app.core.config import settings
from app.main_app.models import Admin, Company


class TestSupportLinks:
    """Test support link generation and validation"""

    async def test_generate_support_link(self, client, db):
        """Test generating a support link from TC2"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com', tc2_admin_id=20))
        company = db.create(
            Company(
                name='Junes Ltd',
                website='https://junes.com',
                country='GB',
                tc2_cligency_id=10,
                sales_person_id=admin.id,
            )
        )

        headers = {'Authorization': f'Bearer {settings.tc2_api_key}'}
        r = client.get(
            client.app.url_path_for('generate-support-link'),
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': company.tc2_cligency_id},
            headers=headers,
        )

        assert r.status_code == 200
        link = r.json()['link']

        company_id = int(re.search(r'company_id=(\d+)', link).group(1))
        assert company_id == company.id

        admin_id = int(re.search(r'admin_id=(\d+)', link).group(1))
        assert admin_id == admin.id

        expiry = datetime.fromtimestamp(int(re.search(r'e=(\d+)', link).group(1)))
        assert expiry > datetime.now()

    async def test_generate_support_link_requires_auth(self, client, db):
        """Test that generating support link requires authentication"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com', tc2_admin_id=20))
        company = db.create(Company(name='Junes Ltd', sales_person_id=admin.id, tc2_cligency_id=10, country='GB'))

        r = client.get(
            client.app.url_path_for('generate-support-link'),
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': company.tc2_cligency_id},
        )

        assert r.status_code == 403

    @patch('app.tc2.process.get_client')
    async def test_generate_support_link_creates_company_if_not_exists(self, mock_get_client, client, db):
        """Test that generating support link creates company from TC2 if it doesn't exist"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com', tc2_admin_id=20))

        mock_get_client.return_value = {
            'id': 10,
            'model': 'Client',
            'meta_agency': {
                'id': 100,
                'name': 'New Company',
                'country': 'United Kingdom (GB)',
                'status': 'active',
                'paid_invoice_count': 0,
                'created': '2024-01-01T00:00:00Z',
                'price_plan': 'monthly-payg',
                'narc': False,
            },
            'user': {'first_name': 'Test', 'last_name': 'User', 'email': 'test@example.com'},
            'status': 'active',
            'sales_person': {'id': 20},
            'paid_recipients': [],
        }

        headers = {'Authorization': f'Bearer {settings.tc2_api_key}'}
        r = client.get(
            client.app.url_path_for('generate-support-link'),
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': 10},
            headers=headers,
        )

        assert r.status_code == 200
        assert 'link' in r.json()

    async def test_generate_support_link_admin_not_found(self, client, db):
        """Test that generating support link returns 404 when admin not found"""
        company = db.create(Company(name='Test Company', sales_person_id=1, tc2_cligency_id=10, country='GB'))

        headers = {'Authorization': f'Bearer {settings.tc2_api_key}'}
        r = client.get(
            client.app.url_path_for('generate-support-link'),
            params={'tc2_admin_id': 999, 'tc2_cligency_id': company.tc2_cligency_id},
            headers=headers,
        )

        assert r.status_code == 404

    async def test_validate_support_link(self, client, db):
        """Test validating a support link"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=admin.id, country='GB'))

        expiry = datetime.now() + timedelta(minutes=10)
        sig = await sign_args(admin.id, company.id, int(expiry.timestamp()))
        params = {'s': sig, 'e': int(expiry.timestamp()), 'company_id': company.id, 'admin_id': admin.id}

        r = client.get(client.app.url_path_for('validate-support-link'), params=params)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok', 'company_name': 'Junes Ltd'}

    async def test_validate_support_link_invalid_signature(self, client, db):
        """Test validating support link with invalid signature"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=admin.id, country='GB'))

        expiry = datetime.now() + timedelta(minutes=10)
        params = {
            's': 'invalid_signature',
            'e': int(expiry.timestamp()),
            'company_id': company.id,
            'admin_id': admin.id,
        }

        r = client.get(client.app.url_path_for('validate-support-link'), params=params)

        assert r.status_code == 403
        assert r.json() == {'status': 'error', 'message': 'Invalid signature'}

    async def test_validate_support_link_expired(self, client, db):
        """Test validating expired support link"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=admin.id, country='GB'))

        expiry = datetime.now() - timedelta(minutes=10)
        sig = await sign_args(admin.id, company.id, int(expiry.timestamp()))
        params = {'s': sig, 'e': int(expiry.timestamp()), 'company_id': company.id, 'admin_id': admin.id}

        r = client.get(client.app.url_path_for('validate-support-link'), params=params)

        assert r.status_code == 403
        assert r.json() == {'status': 'error', 'message': 'Link has expired'}

    async def test_validate_support_link_admin_not_found(self, client, db):
        """Test validating support link when admin not found"""
        company = db.create(Company(name='Test Company', sales_person_id=1, country='GB'))

        expiry = datetime.now() + timedelta(minutes=10)
        sig = await sign_args(999, company.id, int(expiry.timestamp()))
        params = {'s': sig, 'e': int(expiry.timestamp()), 'company_id': company.id, 'admin_id': 999}

        r = client.get(client.app.url_path_for('validate-support-link'), params=params)

        assert r.status_code == 404
        assert r.json() == {'status': 'error', 'message': 'Admin or Company not found'}

    async def test_validate_support_link_company_not_found(self, client, db):
        """Test validating support link when company not found"""
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='test@example.com'))

        expiry = datetime.now() + timedelta(minutes=10)
        sig = await sign_args(admin.id, 999, int(expiry.timestamp()))
        params = {'s': sig, 'e': int(expiry.timestamp()), 'company_id': 999, 'admin_id': admin.id}

        r = client.get(client.app.url_path_for('validate-support-link'), params=params)

        assert r.status_code == 404

    async def test_generate_support_link_company_id_exists(self, client, db):
        """Test generating support link when company already exists"""
        admin = db.create(Admin(first_name='Steve', last_name='Jobs', username='steve@example.com', tc2_admin_id=20))
        db.create(
            Company(
                name='Existing Company',
                sales_person_id=admin.id,
                tc2_cligency_id=10,
                country='GB',
            )
        )

        headers = {'Authorization': f'Bearer {settings.tc2_api_key}'}
        r = client.get(
            client.app.url_path_for('generate-support-link'),
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': 10},
            headers=headers,
        )

        assert r.status_code == 200
        assert 'link' in r.json()
