"""
Tests for patch.py commands.
"""

from datetime import datetime, timezone
from unittest.mock import call, patch

import pytest
from click.testing import CliRunner
from sqlmodel import select

from app.main_app.common import get_or_create_deal
from app.main_app.models import Company, Config, Contact, Deal
from app.pipedrive.tasks import sync_company_to_pipedrive
from patch import fix_repeated_contact_names, patch as patch_command, point_enterprise_deals_to_onboarding
from tests.factories import CompanyFactory, DealFactory, PipelineFactory, StageFactory


class TestFixRepeatedContactNames:
    """Names repeated by #418 are de-duplicated, other names are left alone"""

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_fix_repeated_contact_names(self, mock_pd, db, test_company):
        repeated = db.create(Contact(first_name='john', last_name='john john Smith', company_id=test_company.id))
        jumped = db.create(
            Contact(first_name='john', last_name='john Smith john john Smith', company_id=test_company.id)
        )
        one_word = db.create(Contact(first_name='jOHN', last_name='jOHN jOHN', company_id=test_company.id))
        one_word_twice = db.create(Contact(first_name='aNNA', last_name='aNNA', company_id=test_company.id))
        lowercase = db.create(Contact(first_name='mary', last_name='Jones', company_id=test_company.id))
        capitalised = db.create(Contact(first_name='Ali', last_name='Ali Khan', company_id=test_company.id))
        no_capital = db.create(Contact(first_name='lee', last_name='lee', company_id=test_company.id))

        await fix_repeated_contact_names(db)
        db.commit()

        assert (repeated.first_name, repeated.last_name) == ('john', 'Smith')
        assert (jumped.first_name, jumped.last_name) == ('john', 'Smith')
        assert (one_word.first_name, one_word.last_name) == ('jOHN', 'jOHN')
        assert (one_word_twice.first_name, one_word_twice.last_name) == ('aNNA', 'aNNA')
        assert (lowercase.first_name, lowercase.last_name) == ('mary', 'Jones')
        assert (capitalised.first_name, capitalised.last_name) == ('Ali', 'Ali Khan')
        assert (no_capital.first_name, no_capital.last_name) == ('lee', 'lee')
        assert not mock_pd.called

    @patch('app.pipedrive.api.pipedrive_request')
    def test_fix_repeated_contact_names_live_updates_pipedrive(self, mock_pd, db, test_admin, test_company):
        mock_pd.side_effect = [{'data': {'id': 101}}, Exception('404 Not Found')]
        deleted_company = db.create(
            Company(name='Deleted', price_plan='payg', country='GB', sales_person_id=test_admin.id, is_deleted=True)
        )
        narc_company = db.create(
            Company(name='Narc', price_plan='payg', country='GB', sales_person_id=test_admin.id, narc=True)
        )
        in_deleted_company = db.create(
            Contact(first_name='tom', last_name='tom tom Hill', pd_person_id=103, company_id=deleted_company.id)
        )
        in_narc_company = db.create(
            Contact(first_name='sam', last_name='sam sam Hill', pd_person_id=104, company_id=narc_company.id)
        )
        synced = db.create(
            Contact(first_name='john', last_name='john john Smith', pd_person_id=101, company_id=test_company.id)
        )
        failed = db.create(
            Contact(first_name='anna', last_name='anna Lee', pd_person_id=102, company_id=test_company.id)
        )
        not_in_pd = db.create(Contact(first_name='mo', last_name='mo mo Khan', company_id=test_company.id))

        result = CliRunner().invoke(patch_command, ['fix_repeated_contact_names', '--live'])

        assert result.exit_code == 0
        assert 'Updated Pipedrive person 101' in result.output
        assert 'Failed to update Pipedrive person 102: 404 Not Found' in result.output
        assert mock_pd.call_args_list == [
            call('persons/101', method='PATCH', data={'name': 'john Smith'}),
            call('persons/102', method='PATCH', data={'name': 'anna Lee'}),
        ]
        db.expire_all()
        assert (synced.first_name, synced.last_name) == ('john', 'Smith')
        assert (failed.first_name, failed.last_name) == ('anna', 'Lee')
        assert (not_in_pd.first_name, not_in_pd.last_name) == ('mo', 'Khan')
        assert (in_deleted_company.first_name, in_deleted_company.last_name) == ('tom', 'tom tom Hill')
        assert (in_narc_company.first_name, in_narc_company.last_name) == ('sam', 'sam sam Hill')


class TestPointEnterpriseDealsToOnboarding:
    """New enterprise deals go to Onboarding, and the ones that never reached Pipedrive stop syncing (#372)"""

    @pytest.fixture
    def pipelines(self, db):
        new_signup = StageFactory.create_with_db(db, pd_stage_id=1, name='New Signup')
        onboarding = PipelineFactory.create_with_db(
            db, pd_pipeline_id=1, name='Onboarding (NEW)', dft_entry_stage_id=new_signup.id
        )
        meeting_booked = StageFactory.create_with_db(db, pd_stage_id=11)
        enterprise = PipelineFactory.create_with_db(
            db, pd_pipeline_id=3, name='Enterprise', dft_entry_stage_id=meeting_booked.id
        )
        db.create(
            Config(
                payg_pipeline_id=onboarding.id,
                startup_pipeline_id=onboarding.id,
                enterprise_pipeline_id=enterprise.id,
            )
        )
        return onboarding, enterprise

    def _deal(self, db, company, pipeline, **kwargs):
        return DealFactory.create_with_db(
            db,
            company_id=company.id,
            admin_id=company.sales_person_id,
            pipeline_id=pipeline.id,
            stage_id=pipeline.dft_entry_stage_id,
            **kwargs,
        )

    def _tc2_webhook(self, admin):
        subject = {
            'model': 'Client',
            'id': 123,
            'meta_agency': {
                'id': 456,
                'name': 'Enterprise Agency',
                'country': 'United Kingdom (GB)',
                'status': 'trial',
                'paid_invoice_count': 0,
                'created': datetime.now(timezone.utc).isoformat(),
                'price_plan': 'monthly-enterprise',
            },
            'user': {'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'},
            'status': 'active',
            'sales_person': {'id': admin.tc2_admin_id},
            'paid_recipients': [{'id': 789, 'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'}],
            'extra_attrs': [],
        }
        return {'events': [{'action': 'EDITED_A_CLIENT', 'verb': 'edit', 'subject': subject}], '_request_time': 1}

    def test_point_enterprise_deals_to_onboarding(self, db, test_admin, pipelines):
        onboarding, enterprise = pipelines
        company = CompanyFactory.create_with_db(db, price_plan='enterprise', sales_person_id=test_admin.id)
        unsynced = self._deal(db, company, enterprise)
        synced = self._deal(db, company, enterprise, pd_deal_id=500)
        lost = self._deal(db, company, enterprise, status=Deal.STATUS_LOST)
        onboarding_unsynced = self._deal(db, company, onboarding)

        result = CliRunner().invoke(patch_command, ['point_enterprise_deals_to_onboarding', '--live'])

        assert result.exit_code == 0
        assert (
            f'Config enterprise_pipeline_id {enterprise.id} -> {onboarding.id} (Onboarding (NEW), '
            'entry stage pd_stage_id=1 New Signup)'
        ) in result.output
        assert f'Marked 1 enterprise deals deleted: [{unsynced.id}]' in result.output
        db.expire_all()
        assert db.exec(select(Config)).one().enterprise_pipeline_id == onboarding.id
        assert [d.status for d in (unsynced, synced, lost, onboarding_unsynced)] == [
            Deal.STATUS_DELETED,
            Deal.STATUS_OPEN,
            Deal.STATUS_LOST,
            Deal.STATUS_OPEN,
        ]

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.api.pipedrive_request')
    async def test_deleted_enterprise_deal_is_not_synced(self, mock_pd, db, test_admin, pipelines):
        _, enterprise = pipelines
        company = CompanyFactory.create_with_db(
            db, price_plan='enterprise', sales_person_id=test_admin.id, pd_org_id=900
        )
        self._deal(db, company, enterprise)

        def pipedrive(endpoint, method='GET', **kwargs):
            if endpoint == 'deals':
                raise Exception('Validation failed: pipeline_id: Pipeline does not exist.')
            return {'data': {'id': 900, 'name': company.name}}

        mock_pd.side_effect = pipedrive

        await sync_company_to_pipedrive(company.id)
        deal_creates = [c for c in mock_pd.call_args_list if c.args[0] == 'deals']
        assert [(c.kwargs['data']['pipeline_id'], c.kwargs['data']['stage_id']) for c in deal_creates] == [(3, 11)]

        await point_enterprise_deals_to_onboarding(db)
        db.commit()
        mock_pd.reset_mock()
        await sync_company_to_pipedrive(company.id)

        endpoints = [c.args[0] for c in mock_pd.call_args_list]
        assert 'organizations/900' in endpoints
        assert not [e for e in endpoints if e.startswith('deals')]

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.api.pipedrive_request')
    async def test_new_enterprise_deal_is_created_in_onboarding(self, mock_pd, client, db, test_admin, pipelines):
        mock_pd.return_value = {'data': {'id': 999}}
        await point_enterprise_deals_to_onboarding(db)
        db.commit()

        r = client.post(client.app.url_path_for('tc2-callback'), json=self._tc2_webhook(test_admin))

        assert r.status_code == 200
        deal_creates = [c for c in mock_pd.call_args_list if c.args[0] == 'deals']
        assert [(c.kwargs['data']['pipeline_id'], c.kwargs['data']['stage_id']) for c in deal_creates] == [(1, 1)]

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.tc2.process.get_or_create_deal', wraps=get_or_create_deal)
    @patch('app.pipedrive.api.pipedrive_request')
    async def test_tc2_webhook_creates_no_deal_for_deleted_enterprise_deal(
        self, mock_pd, mock_get_or_create_deal, client, db, test_admin, pipelines
    ):
        _, enterprise = pipelines
        company = CompanyFactory.create_with_db(
            db,
            price_plan='enterprise',
            sales_person_id=test_admin.id,
            tc2_cligency_id=123,
            tc2_agency_id=456,
            pd_org_id=900,
        )
        deal = self._deal(db, company, enterprise)
        mock_pd.return_value = {'data': {'id': 900, 'name': company.name}}
        await point_enterprise_deals_to_onboarding(db)
        db.commit()

        r = client.post(client.app.url_path_for('tc2-callback'), json=self._tc2_webhook(test_admin))

        assert r.status_code == 200
        mock_get_or_create_deal.assert_awaited_once()
        db.expire_all()
        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert [(d.id, d.status) for d in deals] == [(deal.id, Deal.STATUS_DELETED)]
        endpoints = [c.args[0] for c in mock_pd.call_args_list]
        assert 'organizations/900' in endpoints
        assert not [e for e in endpoints if e.startswith('deals')]
