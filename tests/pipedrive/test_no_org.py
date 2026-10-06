"""Tests for Pipedrive persons and deals with no organisation, and deals whose person is not in Hermes"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import event
from sqlmodel import select

from app.core.database import DBSession, get_session
from app.main_app.models import Company, Contact, Deal
from app.pipedrive.field_mappings import CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP
from app.pipedrive.tasks import _company_sync_locks, create_contact_for_pd_deal

PERSON_ID = 300
DEAL_ID = 900
ORG_ID = 456


def error_logs(caplog) -> list[str]:
    """Messages of the ERROR records logged during the test"""
    return [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR]


def person_webhook(action: str = 'create', org_id: int | None = None) -> dict:
    """A Pipedrive v2 person webhook"""
    return {
        'meta': {'entity': 'person', 'action': action},
        'data': {
            'id': PERSON_ID,
            'name': 'Lead Person',
            'first_name': 'Lead',
            'last_name': 'Person',
            'emails': [{'value': 'lead@example.com', 'primary': True}],
            'phones': [{'value': '+44 7700 900123', 'primary': True}],
            'org_id': org_id,
            'owner_id': 1,
        },
        'previous': None,
    }


def deal_webhook(
    deal_id: int = DEAL_ID, org_id: int | None = ORG_ID, person_id: int | None = PERSON_ID, hermes_id: int | None = None
) -> dict:
    """A Pipedrive v2 deal webhook"""
    data = {
        'id': deal_id,
        'title': 'Lead Deal',
        'status': 'open',
        'owner_id': 1,
        'org_id': org_id,
        'person_id': person_id,
        'pipeline_id': 1,
        'stage_id': 1,
    }
    if hermes_id:
        data['custom_fields'] = {DEAL_PD_FIELD_MAP['hermes_id']: {'type': 'varchar', 'value': str(hermes_id)}}
    return {'meta': {'entity': 'deal', 'action': 'create'}, 'data': data, 'previous': None}


def pd_person_response(
    email: str | None = 'lead@example.com', hermes_id: str | None = None, org_id: int | None = None
) -> dict:
    """A Pipedrive v2 GET /persons/{id} response, where custom fields hold plain values"""
    return {
        'success': True,
        'data': {
            'id': PERSON_ID,
            'name': 'Lead Person',
            'first_name': 'Lead',
            'last_name': 'Person',
            'emails': [{'value': email, 'primary': True, 'label': 'work'}] if email else [],
            'phones': [{'value': '+44 7700 900123', 'primary': True, 'label': 'work'}],
            'org_id': org_id,
            'owner_id': 1,
            'custom_fields': {CONTACT_PD_FIELD_MAP['hermes_id']: hermes_id},
        },
    }


@pytest.fixture(autouse=True)
def unlinked_rows(db, test_admin):
    """
    Companies and contacts with no Pipedrive id. Comparing a Pipedrive id column with None matches all of them,
    which is what raised MultipleResultsFound, so every test needs at least two of each.
    """
    companies = [
        db.create(Company(name=f'No Org {i}', sales_person_id=test_admin.id, price_plan='payg')) for i in range(2)
    ]
    for company in companies:
        db.create(Contact(last_name='No Person', email=f'no-person-{company.id}@example.com', company_id=company.id))
    return companies


@pytest.fixture
def lead_company(db, test_admin, test_pipeline, test_stage):
    """The company of the Pipedrive organisation the lead's deal belongs to"""
    return db.create(Company(name='Lead Co', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=ORG_ID))


@pytest.fixture
def clash_on_insert(lead_company):
    """
    Makes the other web process add the contact for PERSON_ID just before this process inserts its own, so the insert
    really hits the unique pd_person_id. With link_deal the other process also links the deal to its contact.
    """
    company_id = lead_company.id
    listeners = []

    def setup(link_deal: bool = False):
        fired = False

        def other_process_wins(session, flush_context, instances):
            nonlocal fired
            if fired or not any(isinstance(obj, Contact) and obj.pd_person_id == PERSON_ID for obj in session.new):
                return
            fired = True
            with get_session() as other_db:
                contact = other_db.create(Contact(last_name='Racer', pd_person_id=PERSON_ID, company_id=company_id))
                if link_deal:
                    deal = other_db.exec(select(Deal).where(Deal.pd_deal_id == DEAL_ID)).one()
                    deal.contact_id = contact.id
                    other_db.add(deal)
                    other_db.commit()

        event.listen(DBSession, 'before_flush', other_process_wins)
        listeners.append(other_process_wins)

    yield setup
    for listener in listeners:
        event.remove(DBSession, 'before_flush', listener)


def get_deal(db) -> Deal | None:
    db.expire_all()
    return db.exec(select(Deal).where(Deal.pd_deal_id == DEAL_ID)).one_or_none()


def get_lead_contact(db) -> Contact | None:
    db.expire_all()
    return db.exec(select(Contact).where(Contact.pd_person_id == PERSON_ID)).one_or_none()


class TestNoOrganisation:
    """Persons and deals with no organisation can't be stored in Hermes, so they are skipped without an error"""

    @pytest.mark.parametrize('action', ['create', 'change'])
    async def test_person_without_org_is_skipped(self, client, db, action, caplog):
        """A person with no organisation creates no contact and logs no error"""
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=person_webhook(action=action))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        assert get_lead_contact(db) is None
        assert error_logs(caplog) == []

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_deal_without_org_is_skipped(self, mock_get_person, client, db, lead_company, caplog):
        """A deal with no organisation creates no deal and logs no error"""
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook(org_id=None))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        assert get_deal(db) is None
        mock_get_person.assert_not_called()
        assert error_logs(caplog) == []

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_deal_without_person_is_created(self, mock_get_person, client, db, lead_company, caplog):
        """A deal with an organisation but no person is created with no contact"""
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook(person_id=None))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        deal = get_deal(db)
        assert deal.company_id == lead_company.id
        assert deal.contact_id is None
        mock_get_person.assert_not_called()
        assert error_logs(caplog) == []


class TestDealPersonNotInHermes:
    """A deal made outside Hermes gets its Pipedrive person as its contact"""

    @pytest.mark.parametrize('person_org_id', [None, ORG_ID], ids=['no_org', 'deal_org'])
    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_contact_created_and_linked(self, mock_get_person, person_org_id, client, db, lead_company, caplog):
        """The person is fetched from Pipedrive and created as a contact of the deal's company"""
        mock_get_person.return_value = pd_person_response(org_id=person_org_id)

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        mock_get_person.assert_called_once_with(PERSON_ID)
        contact = get_lead_contact(db)
        assert contact.company_id == lead_company.id
        assert contact.first_name == 'Lead'
        assert contact.last_name == 'Person'
        assert contact.email == 'lead@example.com'
        assert contact.phone == '+44 7700 900123'
        assert get_deal(db).contact_id == contact.id
        assert error_logs(caplog) == []

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_existing_contact_is_linked_without_fetching(self, mock_get_person, client, db, lead_company):
        """A deal whose person is already a contact links it straight away"""
        contact = db.create(
            Contact(last_name='Known', email='known@example.com', pd_person_id=PERSON_ID, company_id=lead_company.id)
        )

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_deal(db).contact_id == contact.id
        mock_get_person.assert_not_called()

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_fetch_failure_leaves_deal_without_contact(self, mock_get_person, client, db, lead_company, caplog):
        """If Pipedrive can't be reached the deal is still created, and one error is logged"""
        mock_get_person.side_effect = RuntimeError('Pipedrive is down')

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        assert get_deal(db).contact_id is None
        assert get_lead_contact(db) is None
        assert error_logs(caplog) == [
            f'Error adding Pipedrive person {PERSON_ID} to deal {get_deal(db).id}: Pipedrive is down'
        ]

    @pytest.mark.parametrize('status_code', [404, 410])
    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_person_gone_from_pipedrive(self, mock_get_person, status_code, client, db, lead_company, caplog):
        """A person deleted from Pipedrive before it was fetched is skipped without an error"""
        mock_get_person.side_effect = httpx.HTTPStatusError(
            f'{status_code} Not Found',
            request=httpx.Request('GET', f'https://api.pipedrive.com/api/v2/persons/{PERSON_ID}'),
            response=httpx.Response(status_code),
        )

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_deal(db).contact_id is None
        assert get_lead_contact(db) is None
        assert error_logs(caplog) == []
        assert f'Not adding Pipedrive person {PERSON_ID} to deal {get_deal(db).id}: it no longer exists' in caplog.text

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_person_in_another_org(self, mock_get_person, client, db, lead_company, caplog):
        """A person whose own organisation isn't the deal's is not added, so syncing can't move them out of it"""
        mock_get_person.return_value = pd_person_response(org_id=ORG_ID + 1)

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None
        assert error_logs(caplog) == []
        assert f'deal {get_deal(db).id} of company {lead_company.id}: other_org, contact None' in caplog.text

    @pytest.mark.parametrize(
        'response',
        [pd_person_response(email=None), pd_person_response(hermes_id='42')],
        ids=['no_email', 'hermes_id'],
    )
    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_person_not_added(self, mock_get_person, response, client, db, lead_company, caplog):
        """A person with no email, or one Hermes created itself, is not added as a contact"""
        mock_get_person.return_value = response

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None
        assert error_logs(caplog) == []

    @pytest.mark.parametrize(
        'company_changes',
        [{'is_deleted': True}, {'narc': True}, {'price_plan': 'startup, payg'}],
        ids=['deleted', 'narc', 'bad_price_plan'],
    )
    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_company_not_eligible(self, mock_get_person, company_changes, client, db, lead_company, caplog):
        """A deleted or NARC company, or one with an invalid price plan, gets no contact and its person isn't fetched"""
        mock_get_person.return_value = pd_person_response()
        for field, value in company_changes.items():
            setattr(lead_company, field, value)
        db.add(lead_company)
        db.commit()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None
        mock_get_person.assert_not_called()
        assert error_logs(caplog) == []

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_deleted_deal_gets_no_contact(self, mock_get_person, client, db, lead_company):
        """A deal deleted while the person was being fetched is left alone"""

        async def delete_deal(pd_person_id):
            with get_session() as other_db:
                deal = other_db.exec(select(Deal).where(Deal.pd_deal_id == DEAL_ID)).one()
                deal.status = Deal.STATUS_DELETED
                other_db.add(deal)
                other_db.commit()
            return pd_person_response()

        mock_get_person.side_effect = delete_deal

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_second_deal_reuses_contact(self, mock_get_person, client, db, lead_company):
        """A second deal for the same person links the same contact without fetching it again"""
        mock_get_person.return_value = pd_person_response()

        client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook(deal_id=901))

        assert r.status_code == 200
        contact = get_lead_contact(db)
        second_deal = db.exec(select(Deal).where(Deal.pd_deal_id == 901)).one()
        assert get_deal(db).contact_id == contact.id
        assert second_deal.contact_id == contact.id
        mock_get_person.assert_called_once_with(PERSON_ID)

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_later_person_webhook_without_org_updates_contact(
        self, mock_get_person, client, db, lead_company, caplog
    ):
        """Once the person is a contact, its webhooks with no organisation update it instead of failing"""
        mock_get_person.return_value = pd_person_response()
        client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        webhook = person_webhook(action='change')
        webhook['data']['phones'] = [{'value': '+44 7700 900999', 'primary': True}]
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook)

        assert r.status_code == 200
        contact = get_lead_contact(db)
        assert contact.company_id == lead_company.id
        assert contact.phone == '+44 7700 900999'
        assert error_logs(caplog) == []

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_hermes_deal_does_not_fetch_person(
        self, mock_get_person, client, db, lead_company, test_admin, test_pipeline, test_stage
    ):
        """A deal Hermes created (it has a hermes_id) is updated as before, without fetching its person"""
        deal = db.create(
            Deal(
                name='Hermes Deal',
                company_id=lead_company.id,
                admin_id=test_admin.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
                pd_deal_id=DEAL_ID,
            )
        )

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook(hermes_id=deal.id))

        assert r.status_code == 200
        mock_get_person.assert_not_called()
        assert get_deal(db).contact_id is None


class TestDealPersonEmailClash:
    """
    The callbooker books into the newest contact with the booker's email, so no contact is created for a person
    whose email another contact already has
    """

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_email_of_another_company_contact(self, mock_get_person, client, db, lead_company, test_admin):
        """A contact of another company with the same email, in any letter case, blocks creating a contact"""
        other_company = db.create(Company(name='TC2 Co', sales_person_id=test_admin.id, price_plan='payg'))
        db.create(Contact(last_name='Existing', email='Lead@Example.com', company_id=other_company.id))
        mock_get_person.return_value = pd_person_response()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_email_of_deleted_contact(self, mock_get_person, client, db, lead_company):
        """A deleted contact with the same email also blocks it, because the callbooker still books into it"""
        db.create(Contact(last_name='Gone', email='lead@example.com', is_deleted=True, company_id=lead_company.id))
        mock_get_person.return_value = pd_person_response()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_same_company_contact_is_adopted(self, mock_get_person, client, db, lead_company):
        """The one contact with that email, in the deal's company and not yet in Pipedrive, becomes the person"""
        contact = db.create(Contact(last_name='Signed Up', email='lead@example.com', company_id=lead_company.id))
        mock_get_person.return_value = pd_person_response()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert db.exec(select(Contact).where(Contact.email == 'lead@example.com')).one().id == contact.id
        assert get_lead_contact(db).id == contact.id
        assert get_deal(db).contact_id == contact.id

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_same_company_contact_with_other_person_is_not_adopted(
        self, mock_get_person, client, db, lead_company
    ):
        """A same-company contact that is already another Pipedrive person is left alone"""
        db.create(Contact(last_name='Other', email='lead@example.com', pd_person_id=301, company_id=lead_company.id))
        mock_get_person.return_value = pd_person_response()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_lead_contact(db) is None
        assert get_deal(db).contact_id is None


class TestDealPersonRace:
    """The other web process can add the same person while this one waits on Pipedrive"""

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_contact_added_while_fetching(self, mock_get_person, client, db, lead_company):
        """A contact added while the person was fetched is linked, not duplicated"""

        async def add_contact_first(pd_person_id):
            with get_session() as other_db:
                other_db.add(Contact(last_name='Racer', pd_person_id=pd_person_id, company_id=lead_company.id))
                other_db.commit()
            return pd_person_response()

        mock_get_person.side_effect = add_contact_first

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        assert get_deal(db).contact_id == get_lead_contact(db).id

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_duplicate_insert_links_other_process_contact(
        self, mock_get_person, clash_on_insert, client, db, lead_company, caplog
    ):
        """If the insert clashes with the contact the other process just added, that contact is linked"""
        mock_get_person.return_value = pd_person_response()
        clash_on_insert()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        contact = get_lead_contact(db)
        assert contact.last_name == 'Racer'
        assert get_deal(db).contact_id == contact.id
        assert error_logs(caplog) == []
        assert f'company {lead_company.id}: existing, contact {contact.id}' in caplog.text

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_duplicate_insert_when_deal_already_linked(
        self, mock_get_person, clash_on_insert, client, db, lead_company, caplog
    ):
        """If the other process also linked the deal, it is left as it is"""
        mock_get_person.return_value = pd_person_response()
        clash_on_insert(link_deal=True)

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook())

        assert r.status_code == 200
        contact = get_lead_contact(db)
        assert contact.last_name == 'Racer'
        assert get_deal(db).contact_id == contact.id
        assert error_logs(caplog) == []
        assert f'the other process linked contact {contact.id}' in caplog.text

    @patch('app.pipedrive.api.get_person', new_callable=AsyncMock)
    async def test_waits_for_company_sync(
        self, mock_get_person, db, lead_company, test_admin, test_pipeline, test_stage
    ):
        """
        A contact isn't adopted while a company sync holds the company's lock, because the sync may be creating that
        contact's own Pipedrive person
        """
        contact = db.create(Contact(last_name='Signed Up', email='lead@example.com', company_id=lead_company.id))
        deal = db.create(
            Deal(
                name='Lead Deal',
                company_id=lead_company.id,
                admin_id=test_admin.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
                pd_deal_id=DEAL_ID,
            )
        )
        mock_get_person.return_value = pd_person_response()

        async with _company_sync_locks.acquire(lead_company.id):
            task = asyncio.create_task(create_contact_for_pd_deal(deal.id, PERSON_ID))
            await asyncio.sleep(0.5)
            mock_get_person.assert_called_once_with(PERSON_ID)
            assert not task.done()
            # sync_person creates the contact's own Pipedrive person while the sync holds the lock
            contact.pd_person_id = 555
            db.add(contact)
            db.commit()
        await task

        db.expire_all()
        assert db.get(Contact, contact.id).pd_person_id == 555
        assert get_deal(db).contact_id is None
