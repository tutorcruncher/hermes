"""
The signup contact details TC2 sends on the meta Client webhook (TC2 #17741).

They go to Google alongside the click id, which lets it fall back to matching on the person when the
click alone doesn't resolve. Hermes stores them on the Company and syncs them to the Pipedrive
organisation, where Zapier reads them for the offline conversion import.
"""

import pytest

from app.main_app.models import Company
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP
from app.pipedrive.models import Organisation
from app.pipedrive.process import OrganisationProcessor
from app.pipedrive.tasks import _company_to_org_data
from app.tc2.models import TCClient
from app.tc2.process import COMPANY_SYNCABLE_FIELDS, process_tc_client

SIGNUP_CONTACT = {
    'signup_email': 'aoife@brightside-tutoring.test',
    'signup_phone': '+447700900123',
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


class TestSignupContact:
    async def test_signup_contact_mapped_to_company(self, db, test_admin, sample_tc_client_data):
        """The contact details arrive flat on meta_agency and land on the company."""
        sample_tc_client_data['meta_agency'].update(SIGNUP_CONTACT)

        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        assert company.signup_email == 'aoife@brightside-tutoring.test'
        assert company.signup_phone == '+447700900123'

    async def test_signup_contact_updated_on_an_existing_company(self, db, test_admin, sample_tc_client_data):
        """They are syncable fields, so a later webhook refreshes them."""
        await process_tc_client(TCClient(**sample_tc_client_data), db)

        sample_tc_client_data['meta_agency'].update(SIGNUP_CONTACT)
        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        assert company.signup_email == 'aoife@brightside-tutoring.test'
        assert company.signup_phone == '+447700900123'

    async def test_missing_signup_contact_is_not_an_error(self, db, test_admin, sample_tc_client_data):
        """
        A company that signed up before TC2 sent these, or one that arrived with no click id, has
        neither. The payload has to parse and the columns stay empty.
        """
        assert 'signup_email' not in sample_tc_client_data['meta_agency']

        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        assert company.signup_email is None
        assert company.signup_phone is None

    async def test_signup_contact_reaches_the_pipedrive_organisation(self, db, test_admin, sample_tc_client_data):
        """They are sent on as Pipedrive custom fields, keyed by the field map."""
        sample_tc_client_data['meta_agency'].update(SIGNUP_CONTACT)
        company = await process_tc_client(TCClient(**sample_tc_client_data), db)

        custom_fields = _company_to_org_data(company)['custom_fields']

        assert custom_fields[COMPANY_PD_FIELD_MAP['signup_email']] == 'aoife@brightside-tutoring.test'
        assert custom_fields[COMPANY_PD_FIELD_MAP['signup_phone']] == '+447700900123'


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

    def test_every_syncable_field_exists_on_both_models(self):
        """_update_syncable_fields getattr()s each of these off meta_agency and sets it on Company."""
        missing = [f for f in COMPANY_SYNCABLE_FIELDS if f not in Company.model_fields]
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
