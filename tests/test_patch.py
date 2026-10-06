"""
Tests for patch.py commands.
"""

from unittest.mock import call, patch

from click.testing import CliRunner

from app.main_app.models import Company, Contact
from patch import fix_repeated_contact_names, patch as patch_command


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
