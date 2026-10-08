"""
Tests for patch.py commands.
"""

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import call, patch

import pytest
from click.testing import CliRunner
from sqlmodel import select

from app.main_app.common import get_or_create_deal
from app.main_app.models import Company, Config, Contact, Deal
from app.pipedrive.tasks import sync_company_to_pipedrive
from patch import fix_repeated_contact_names, patch as patch_command, point_enterprise_deals_to_onboarding
from tests.factories import (
    CompanyFactory,
    ContactFactory,
    DealFactory,
    MeetingFactory,
    PipelineFactory,
    StageFactory,
)
from tests.helpers import pipedrive_http_error


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
    """
    New enterprise deals go to Onboarding. Of the ones that never reached Pipedrive, recent ones move to Onboarding
    and are sent to Pipedrive, the rest stop syncing (#372)
    """

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

    def _company(self, db, admin, days_old, **kwargs):
        return CompanyFactory.create_with_db(
            db,
            price_plan='enterprise',
            sales_person_id=admin.id,
            created=datetime.now(timezone.utc) - timedelta(days=days_old),
            **kwargs,
        )

    def _meeting(self, db, deal, days_ago):
        contact = ContactFactory.create_with_db(db, company_id=deal.company_id)
        return MeetingFactory.create_with_db(
            db,
            company_id=deal.company_id,
            contact_id=contact.id,
            admin_id=deal.admin_id,
            deal_id=deal.id,
            created=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )

    def _pipedrive(self, open_deal_orgs=(), create_error=None):
        pd_ids = count(1000)

        def pipedrive(endpoint, method='GET', query_params=None, data=None):
            if endpoint == 'deals' and method == 'GET':
                return {'data': [{'id': 1}] if query_params['org_id'] in open_deal_orgs else []}
            if endpoint == 'deals' and method == 'POST' and create_error:
                raise create_error
            if method == 'POST':
                return {'data': {'id': next(pd_ids)}}
            return {'data': {}}

        return pipedrive

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

    @patch('app.pipedrive.api.pipedrive_request')
    def test_point_enterprise_deals_to_onboarding(self, mock_pd, db, test_admin, pipelines):
        onboarding, enterprise = pipelines
        mock_pd.side_effect = self._pipedrive(open_deal_orgs={906})
        recent_signup = self._deal(db, self._company(db, test_admin, 2, pd_org_id=901), enterprise)
        recent_booking = self._deal(db, self._company(db, test_admin, 300, pd_org_id=902), enterprise)
        self._meeting(db, recent_booking, 3)
        old_booking = self._deal(db, self._company(db, test_admin, 300), enterprise)
        self._meeting(db, old_booking, 20)
        old_signup = self._deal(db, self._company(db, test_admin, 30), enterprise)
        deleted_company = self._deal(db, self._company(db, test_admin, 2, is_deleted=True), enterprise)
        narc = self._deal(db, self._company(db, test_admin, 2, narc=True), enterprise)
        paying = self._deal(db, self._company(db, test_admin, 2, paid_invoice_count=1), enterprise)
        twice = self._company(db, test_admin, 2, pd_org_id=905)
        twice_older = self._deal(db, twice, enterprise)
        twice_newer = self._deal(db, twice, enterprise)
        has_deal = self._company(db, test_admin, 2)
        has_deal_stuck = self._deal(db, has_deal, enterprise)
        self._deal(db, has_deal, onboarding, pd_deal_id=500)
        open_in_pd = self._deal(db, self._company(db, test_admin, 2, pd_org_id=906), enterprise)
        self._deal(db, has_deal, enterprise, pd_deal_id=501)
        lost = self._deal(db, has_deal, enterprise, status=Deal.STATUS_LOST)

        result = CliRunner().invoke(patch_command, ['point_enterprise_deals_to_onboarding'])

        assert result.exit_code == 0
        for line in [
            f'Config enterprise_pipeline_id {enterprise.id} -> {onboarding.id} (Onboarding (NEW), '
            'entry stage pd_stage_id=1 New Signup)',
            f'Moving 3 enterprise deals to Onboarding (NEW), stage New Signup: '
            f'{[recent_signup.id, recent_booking.id, twice_newer.id]}',
            f'Marking 2 enterprise deals deleted, no signup or call booking in the last 14 days: '
            f'{[old_booking.id, old_signup.id]}',
            f'Marking 2 enterprise deals deleted, company deleted or NARC: {[deleted_company.id, narc.id]}',
            f'Marking 1 enterprise deals deleted, company is paying: {[paying.id]}',
            f'Marking 2 enterprise deals deleted, company has another open deal: {[twice_older.id, has_deal_stuck.id]}',
            f'Marking 1 enterprise deals deleted, org already has an open Pipedrive deal: {[open_in_pd.id]}',
            'Not committing changes',
        ]:
            assert line in result.output
        assert mock_pd.call_args_list == [
            call('deals', query_params={'org_id': org_id, 'status': 'open', 'limit': 1})
            for org_id in (906, 905, 902, 901)
        ]
        db.expire_all()
        assert db.exec(select(Config)).one().enterprise_pipeline_id == enterprise.id
        assert {(d.pipeline_id, d.status) for d in db.exec(select(Deal).where(Deal.id != lost.id)).all()} == {
            (enterprise.id, Deal.STATUS_OPEN),
            (onboarding.id, Deal.STATUS_OPEN),
        }

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.api.pipedrive_request')
    def test_live_moves_recent_deals_and_sends_them_to_pipedrive(self, mock_pd, db, test_admin, pipelines):
        onboarding, enterprise = pipelines
        mock_pd.side_effect = self._pipedrive()
        recent = self._deal(db, self._company(db, test_admin, 2, pd_org_id=901), enterprise)
        old = self._deal(db, self._company(db, test_admin, 30, pd_org_id=902), enterprise)
        company = self._company(db, test_admin, 30)
        synced = self._deal(db, company, enterprise, pd_deal_id=500)
        lost = self._deal(db, company, enterprise, status=Deal.STATUS_LOST)
        onboarding_unsynced = self._deal(db, company, onboarding)

        result = CliRunner().invoke(patch_command, ['point_enterprise_deals_to_onboarding', '--live'])

        assert result.exit_code == 0
        deal_creates = [
            c.kwargs['data'] for c in mock_pd.call_args_list if c.args[0] == 'deals' and c.kwargs.get('data')
        ]
        assert [(d['org_id'], d['pipeline_id'], d['stage_id']) for d in deal_creates] == [(901, 1, 1)]
        db.expire_all()
        assert db.exec(select(Config)).one().enterprise_pipeline_id == onboarding.id
        assert f'Created Pipedrive deal {recent.pd_deal_id} for deal {recent.id}' in result.output
        assert [(d.pipeline_id, d.stage_id, d.status, d.pd_deal_id) for d in (recent, old, synced, lost)] == [
            (onboarding.id, onboarding.dft_entry_stage_id, Deal.STATUS_OPEN, 1000),
            (enterprise.id, enterprise.dft_entry_stage_id, Deal.STATUS_DELETED, None),
            (enterprise.id, enterprise.dft_entry_stage_id, Deal.STATUS_OPEN, 500),
            (enterprise.id, enterprise.dft_entry_stage_id, Deal.STATUS_LOST, None),
        ]
        assert (onboarding_unsynced.status, onboarding_unsynced.pd_deal_id) == (Deal.STATUS_OPEN, None)

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.api.pipedrive_request')
    def test_live_reports_a_deal_pipedrive_rejects(self, mock_pd, db, test_admin, pipelines):
        onboarding, enterprise = pipelines
        mock_pd.side_effect = self._pipedrive(create_error=pipedrive_http_error(400, 'deals', 'POST'))
        recent = self._deal(db, self._company(db, test_admin, 2, pd_org_id=901), enterprise)

        result = CliRunner().invoke(patch_command, ['point_enterprise_deals_to_onboarding', '--live'])

        assert result.exit_code == 0
        assert [c.args[0] for c in mock_pd.call_args_list if c.kwargs.get('method') == 'POST'] == ['deals']
        assert f'Deal {recent.id} still has no Pipedrive deal, see the sync log above' in result.output
        db.expire_all()
        assert (recent.pipeline_id, recent.status, recent.pd_deal_id) == (onboarding.id, Deal.STATUS_OPEN, None)

    @patch('app.pipedrive.api.pipedrive_request')
    def test_pipedrive_error_in_open_deal_check_changes_nothing(self, mock_pd, db, test_admin, pipelines):
        _, enterprise = pipelines
        mock_pd.side_effect = pipedrive_http_error(500, 'deals')
        recent = self._deal(db, self._company(db, test_admin, 2, pd_org_id=901), enterprise)
        old = self._deal(db, self._company(db, test_admin, 30), enterprise)

        result = CliRunner().invoke(patch_command, ['point_enterprise_deals_to_onboarding', '--live'])

        assert result.exit_code == 1
        assert "Client error '500'" in str(result.exception)
        assert mock_pd.call_count == 1
        db.expire_all()
        assert db.exec(select(Config)).one().enterprise_pipeline_id == enterprise.id
        assert [(d.pipeline_id, d.status) for d in (recent, old)] == [(enterprise.id, Deal.STATUS_OPEN)] * 2

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.api.pipedrive_request')
    async def test_deleted_enterprise_deal_is_not_synced(self, mock_pd, db, test_admin, pipelines):
        _, enterprise = pipelines
        company = self._company(db, test_admin, 30, pd_org_id=900)
        self._deal(db, company, enterprise)

        def pipedrive(endpoint, method='GET', **kwargs):
            if endpoint == 'deals':
                raise pipedrive_http_error(400, 'deals', 'POST')
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
        company = self._company(db, test_admin, 30, tc2_cligency_id=123, tc2_agency_id=456, pd_org_id=900)
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
