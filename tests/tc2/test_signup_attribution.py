"""
The signup attribution TC2 sends on the meta Client webhook (TC2 #17741).

TC2 nests it under meta_agency.signup_data; Hermes flattens it onto the Company so the existing
field-map machinery can sync it to the Pipedrive organisation, where Zapier reads it to import the
signup into Google Ads as an offline conversion.
"""

import pytest

from app.main_app.models import Company
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP
from app.pipedrive.models import Organisation
from app.pipedrive.process import OrganisationProcessor
from app.pipedrive.tasks import _company_to_org_data
from app.tc2.models import TCClient
from app.tc2.process import SIGNUP_DATA_FIELDS, process_tc_client

SIGNUP_DATA = {
    'utm_medium': 'cpc',
    'utm_term': 'tutoring software',
    'utm_content': 'headline_b',
    'ga4_client_id': '123456.7890',
    'email': 'aoife@brightside-tutoring.test',
    'phone': '+447700900123',
    'company_name': 'Brightside Tutoring',
}


@pytest.fixture
def sample_tc_client_data(test_admin):
    return {
        'id': 123,
        'meta_agency': {
            'id': 456,
            'name': 'Test Agency',
            'country': 'United Kingdom (GB)',
            'website': 'https://example.com',
            'status': 'active',
            'paid_invoice_count': 5,
            'created': '2024-01-01T00:00:00Z',
            'price_plan': 'monthly-payg',
            'narc': False,
        },
        'user': {'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com', 'phone': '+1234567890'},
        'status': 'active',
        'sales_person': {'id': test_admin.tc2_admin_id},
        'paid_recipients': [{'id': 789, 'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'}],
        'extra_attrs': [],
    }


class TestSignupAttribution:
    async def test_signup_data_mapped_to_company(self, db, test_admin, sample_tc_client_data):
        """The nested signup_data lands on the company's own columns."""
        sample_tc_client_data['meta_agency']['signup_data'] = SIGNUP_DATA

        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        assert company.utm_medium == 'cpc'
        assert company.utm_term == 'tutoring software'
        assert company.utm_content == 'headline_b'
        assert company.ga4_client_id == '123456.7890'
        assert company.signup_email == 'aoife@brightside-tutoring.test'
        assert company.signup_phone == '+447700900123'
        assert company.signup_company_name == 'Brightside Tutoring'

    async def test_signup_data_updated_on_an_existing_company(self, db, test_admin, sample_tc_client_data):
        """A later webhook for a company we already have refreshes the attribution."""
        await process_tc_client(TCClient(**sample_tc_client_data), db)

        sample_tc_client_data['meta_agency']['signup_data'] = SIGNUP_DATA
        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        assert company.utm_medium == 'cpc'
        assert company.signup_email == 'aoife@brightside-tutoring.test'

    async def test_missing_signup_data_is_not_an_error(self, db, test_admin, sample_tc_client_data):
        """
        TC2 only started sending this recently, so every company that signed up before it has no
        signup_data at all. The payload has to parse and the columns stay empty.
        """
        assert 'signup_data' not in sample_tc_client_data['meta_agency']

        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        assert company.utm_medium is None
        assert company.signup_email is None
        assert company.signup_company_name is None

    async def test_signup_data_reaches_the_pipedrive_organisation(self, db, test_admin, sample_tc_client_data):
        """The values are sent on as Pipedrive custom fields, keyed by the field map."""
        sample_tc_client_data['meta_agency']['signup_data'] = SIGNUP_DATA
        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        custom_fields = _company_to_org_data(company)['custom_fields']

        assert custom_fields[COMPANY_PD_FIELD_MAP['utm_medium']] == 'cpc'
        assert custom_fields[COMPANY_PD_FIELD_MAP['utm_term']] == 'tutoring software'
        assert custom_fields[COMPANY_PD_FIELD_MAP['utm_content']] == 'headline_b'
        assert custom_fields[COMPANY_PD_FIELD_MAP['signup_email']] == 'aoife@brightside-tutoring.test'
        assert custom_fields[COMPANY_PD_FIELD_MAP['signup_phone']] == '+447700900123'
        assert custom_fields[COMPANY_PD_FIELD_MAP['signup_company_name']] == 'Brightside Tutoring'


class TestFieldMapIntegrity:
    """
    OrganisationProcessor._add_obj does getattr(pd_obj, f) for every name in custom_field_names, so
    one of those missing from the Organisation model raises AttributeError on every incoming
    Pipedrive organisation webhook. These pin that the models stay in step with the field map.
    """

    def test_every_synced_field_exists_on_the_organisation_model(self):
        """
        Only the names custom_field_names yields are read off the parsed organisation. The ones it
        excludes (hermes_id, the admin ids, tc2_cligency_url, receive_marketing_emails) are
        deliberately absent from the model so Pipedrive cannot write them back.
        """
        processor = OrganisationProcessor.__new__(OrganisationProcessor)
        missing = [f for f in processor.custom_field_names if f not in Organisation.model_fields]
        assert missing == []

    def test_every_mapped_field_exists_on_the_company_model(self):
        exempt = {'hermes_id', 'tc2_cligency_url'}  # derived in _company_to_org_data, not columns
        missing = [f for f in COMPANY_PD_FIELD_MAP if f not in exempt and f not in Company.model_fields]
        assert missing == []

    def test_every_signup_data_column_exists_on_the_company_model(self):
        missing = [c for c in SIGNUP_DATA_FIELDS if c not in Company.model_fields]
        assert missing == []

    def test_no_placeholder_field_ids(self):
        """
        Fails until the new Pipedrive custom fields have been created and their real ids pasted in.
        Deploying a placeholder would send Pipedrive a custom-field key that does not exist.

            python create_pipedrive_fields.py   # creates them in Pipedrive
            make setup-fields                   # writes field_mappings_override.py with the ids
        """
        placeholders = {name: fid for name, fid in COMPANY_PD_FIELD_MAP.items() if fid.startswith('REPLACE_ME')}
        assert placeholders == {}
