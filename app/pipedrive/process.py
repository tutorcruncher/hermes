import logging
from functools import cached_property

from sqlalchemy import func
from sqlmodel import select

from app.core.database import DBSession
from app.main_app.models import Admin, Company, Contact, Deal, Pipeline, Stage
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP
from app.pipedrive.models import Organisation, PDDeal, PDPipeline, PDStage, Person

logger = logging.getLogger('hermes.pipedrive')


def _contact_from_pd_person(pd_person: Person, company_id: int) -> Contact:
    return Contact(
        pd_person_id=pd_person.id,
        company_id=company_id,
        first_name=pd_person.first_name[:255] if pd_person.first_name else None,
        last_name=pd_person.last_name[:255] if pd_person.last_name else None,
        email=pd_person.email,
        phone=pd_person.phone,
    )


class PipedriveObjProcessor:
    hermes_model = NotImplemented
    pd_model = NotImplemented
    pd_id_field = NotImplemented

    def __init__(self, db: DBSession):
        self.db = db

    @cached_property
    def hermes_admin_ids(self) -> dict[int, int]:
        return {admin.pd_owner_id: admin.id for admin in self.db.exec(select(Admin)).all()}

    async def save_obj(
        self, obj: Company | Contact | Deal, new_pd_obj: Organisation | Person | PDDeal, action: str
    ) -> Company | Contact | Deal:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        logger.info(
            '%s %s:%s from Pipedrive %s:%s with data %r',
            action,
            self.hermes_model,
            obj.id,
            self.pd_model,
            new_pd_obj.id,
            new_pd_obj.model_dump(mode='json'),
        )
        return obj

    async def delete_obj(self, pd_obj: Organisation | Person | PDDeal):
        # For deletions, we just clear the pd_*_id field to indicate the object no longer exists in Pipedrive
        # We don't delete from Hermes because the data may still be useful
        hermes_obj = self.db.exec(
            select(self.hermes_model).where(getattr(self.hermes_model, self.pd_id_field) == pd_obj.id)
        ).one_or_none()
        if hermes_obj:
            if self.hermes_model == Deal:
                hermes_obj.status = Deal.STATUS_DELETED
            if self.hermes_model == Company:
                hermes_obj.is_deleted = True
            if self.hermes_model == Contact:
                hermes_obj.is_deleted = True
            setattr(hermes_obj, self.pd_id_field, None)
            self.db.add(hermes_obj)
            self.db.commit()
            logger.info(
                'Cleared %s from %s:%s (marked as deleted in Pipedrive)',
                self.pd_id_field,
                self.hermes_model.__name__,
                hermes_obj.id,
            )
        return None

    def _mark_merged_losers_deleted(self, loser_ids: list[int]) -> None:
        """Mark merged losers as deleted and clear their Pipedrive ID,
        since the entity no longer exists in Pipedrive after the merge."""
        for loser_id in loser_ids:
            loser_obj = self.db.get(self.hermes_model, loser_id)
            if loser_obj and not loser_obj.is_deleted:
                loser_obj.is_deleted = True
                setattr(loser_obj, self.pd_id_field, None)
                self.db.add(loser_obj)
        self.db.commit()

    async def _update_obj(
        self, hermes_obj: Company | Contact | Deal, pd_obj: Organisation | Person | PDDeal
    ) -> Company | Contact | Deal:
        raise NotImplementedError

    async def _add_obj(self, new_pd_obj: Organisation | Person | PDDeal) -> Company | Contact | Deal | None:
        """Build a new Hermes object from the Pipedrive one, or return None when it cannot be stored in Hermes"""
        raise NotImplementedError

    def _on_created(self, hermes_obj: Company | Contact | Deal, pd_obj: Organisation | Person | PDDeal) -> None:
        """Runs after a brand-new object from Pipedrive has been saved"""
        pass

    async def process(
        self, old_pd_obj: Organisation | Person | PDDeal | None, new_pd_obj: Organisation | Person | PDDeal | None
    ):
        if not new_pd_obj:
            # The object has been deleted
            await self.delete_obj(old_pd_obj)
        else:
            if hasattr(new_pd_obj, 'hermes_id') and new_pd_obj.hermes_id:
                if isinstance(new_pd_obj.hermes_id, str) and ',' in str(new_pd_obj.hermes_id):
                    hermes_ids = list(map(int, map(lambda x: x.strip(), str(new_pd_obj.hermes_id).split(','))))
                    winner_id = hermes_ids[0]
                    loser_ids = hermes_ids[1:]

                    # Take the first ID from comma-separated list (primary entity after merge)
                    new_pd_obj.hermes_id = winner_id
                    logger.info(f'Detected merged entity, using first hermes_id: {new_pd_obj.hermes_id}')

                    self._mark_merged_losers_deleted(loser_ids)

                hermes_obj = self.db.get(self.hermes_model, new_pd_obj.hermes_id)
                if hermes_obj:
                    # The obj exists in Hermes and therefore needs updated
                    updated_obj = await self._update_obj(hermes_obj=hermes_obj, pd_obj=new_pd_obj)
                    await self.save_obj(updated_obj, new_pd_obj, 'Updated')
                else:
                    # Somehow the object has been deleted in Hermes? Don't think this can happen
                    logger.error(
                        f'Object exists in Pipedrive with hermes_id {new_pd_obj.hermes_id} but not found in Hermes'
                    )
            else:
                hermes_obj = self.db.exec(
                    select(self.hermes_model).where(getattr(self.hermes_model, self.pd_id_field) == new_pd_obj.id)
                ).one_or_none()
                if hermes_obj:
                    # The object exists in Hermes already, but the PD object doesn't have the hermes_id. It should
                    # be updated in Hermes
                    updated_obj = await self._update_obj(hermes_obj=hermes_obj, pd_obj=new_pd_obj)
                    await self.save_obj(updated_obj, new_pd_obj, 'Updated')
                else:
                    # The object is brand new
                    new_obj = await self._add_obj(new_pd_obj)
                    if new_obj:
                        await self.save_obj(new_obj, new_pd_obj, 'Created')
                        self._on_created(new_obj, new_pd_obj)


class OrganisationProcessor(PipedriveObjProcessor):
    hermes_model = Company
    pd_model = Organisation
    pd_id_field = 'pd_org_id'

    @property
    def custom_field_names(self):
        return [
            f
            for f in list(COMPANY_PD_FIELD_MAP.keys())
            # receive_marketing_emails and operate_as_ea are TC2-authoritative; Pipedrive must not write them back.
            if f
            not in [
                'hermes_id',
                'bdr_person_id',
                'support_person_id',
                'tc2_cligency_url',
                'receive_marketing_emails',
                'operate_as_ea',
            ]
        ]

    async def _add_obj(self, pd_obj: Organisation) -> Company:
        kwargs = {
            'name': pd_obj.name[:255],
            'country': pd_obj.address_country,
            'pd_org_id': pd_obj.id,
            'sales_person_id': self.hermes_admin_ids[pd_obj.owner_id],
        }
        kwargs.update({f: getattr(pd_obj, f) for f in self.custom_field_names})
        if pd_obj.bdr_person_id and pd_obj.bdr_person_id in self.hermes_admin_ids:
            kwargs['bdr_person_id'] = self.hermes_admin_ids[pd_obj.bdr_person_id]
        if pd_obj.support_person_id and pd_obj.support_person_id in self.hermes_admin_ids:
            kwargs['support_person_id'] = self.hermes_admin_ids[pd_obj.support_person_id]
        return Company(**kwargs)

    async def _update_obj(self, hermes_obj: Company, pd_obj: Organisation) -> Company:
        hermes_obj.is_deleted = False

        if pd_obj.name and hermes_obj.name != pd_obj.name[:255]:
            hermes_obj.name = pd_obj.name[:255]
        if pd_obj.address_country and hermes_obj.country != pd_obj.address_country:
            hermes_obj.country = pd_obj.address_country

        if pd_obj.owner_id and pd_obj.owner_id in self.hermes_admin_ids:
            new_sales_person_id = self.hermes_admin_ids[pd_obj.owner_id]
            if hermes_obj.sales_person_id != new_sales_person_id:
                hermes_obj.sales_person_id = new_sales_person_id

        if pd_obj.bdr_person_id and pd_obj.bdr_person_id in self.hermes_admin_ids:
            new_bdr_id = self.hermes_admin_ids[pd_obj.bdr_person_id]
            if hermes_obj.bdr_person_id != new_bdr_id:
                hermes_obj.bdr_person_id = new_bdr_id

        if pd_obj.support_person_id and pd_obj.support_person_id in self.hermes_admin_ids:
            new_support_id = self.hermes_admin_ids[pd_obj.support_person_id]
            if hermes_obj.support_person_id != new_support_id:
                hermes_obj.support_person_id = new_support_id

        for f in self.custom_field_names:
            pd_val = getattr(pd_obj, f)
            if pd_val is not None and pd_val != getattr(hermes_obj, f):
                setattr(hermes_obj, f, pd_val)
        return hermes_obj


class PersonProcessor(PipedriveObjProcessor):
    hermes_model = Contact
    pd_model = Person
    pd_id_field = 'pd_person_id'

    @property
    def custom_field_names(self):
        return [f for f in list(CONTACT_PD_FIELD_MAP.keys()) if f != 'hermes_id']

    async def _add_obj(self, pd_obj: Person) -> Contact | None:
        if not pd_obj.org_id:
            # Comparing pd_org_id with None would match every company without a Pipedrive organisation
            logger.info(f'Skipping Pipedrive person {pd_obj.id}: it has no organisation and a contact needs a company')
            return None
        company = self.db.exec(select(Company).where(Company.pd_org_id == pd_obj.org_id)).one()
        return _contact_from_pd_person(pd_obj, company.id)

    async def _update_obj(self, hermes_obj: Contact, pd_obj: Person) -> Contact:
        hermes_obj.is_deleted = False

        if pd_obj.first_name and pd_obj.first_name[:255] != hermes_obj.first_name:
            hermes_obj.first_name = pd_obj.first_name[:255]
        if pd_obj.last_name and pd_obj.last_name[:255] != hermes_obj.last_name:
            hermes_obj.last_name = pd_obj.last_name[:255]
        if pd_obj.phone and pd_obj.phone != hermes_obj.phone:
            hermes_obj.phone = pd_obj.phone
        if pd_obj.email and pd_obj.email != hermes_obj.email:
            hermes_obj.email = pd_obj.email

        if pd_obj.org_id:
            org_id = pd_obj.org_id
            if isinstance(org_id, list) and len(org_id) > 0:
                # For merges, get the first one.
                org_id = org_id[0]

            company = self.db.exec(select(Company).where(Company.pd_org_id == org_id)).one_or_none()
            if company and company.id != hermes_obj.company_id:
                hermes_obj.company_id = company.id
        return hermes_obj


class PDDealProcessor(PipedriveObjProcessor):
    hermes_model = Deal
    pd_model = PDDeal
    pd_id_field = 'pd_deal_id'

    @property
    def custom_field_names(self):
        return [f for f in list(DEAL_PD_FIELD_MAP.keys()) if f != 'hermes_id']

    def __init__(self, db: DBSession):
        super().__init__(db)
        # (deal id, Pipedrive person id) pairs whose person the view fetches in a background task
        self.contacts_to_fetch: list[tuple[int, int]] = []

    def _mark_merged_losers_deleted(self, loser_ids: list[int]) -> None:
        pass

    async def _add_obj(self, pd_obj: PDDeal) -> Deal | None:
        if not pd_obj.org_id:
            # Comparing pd_org_id with None would match every company without a Pipedrive organisation
            logger.info(f'Skipping Pipedrive deal {pd_obj.id}: it has no organisation and a deal needs a company')
            return None
        company = self.db.exec(select(Company).where(Company.pd_org_id == pd_obj.org_id)).one()
        pipeline = self.db.exec(select(Pipeline).where(Pipeline.pd_pipeline_id == pd_obj.pipeline_id)).one()
        stage = self.db.exec(select(Stage).where(Stage.pd_stage_id == pd_obj.stage_id)).one()

        kwargs = {
            'pd_deal_id': pd_obj.id,
            'name': pd_obj.title[:255],
            'status': pd_obj.status,
            'admin_id': self.hermes_admin_ids[pd_obj.user_id],
            'company_id': company.id,
            'pipeline_id': pipeline.id,
            'stage_id': stage.id,
        }

        if pd_obj.person_id:
            contact = self.db.exec(select(Contact).where(Contact.pd_person_id == pd_obj.person_id)).one_or_none()
            if contact:
                kwargs['contact_id'] = contact.id
        kwargs.update({f: getattr(pd_obj, f) for f in self.custom_field_names})
        return Deal(**kwargs)

    def _on_created(self, hermes_obj: Deal, pd_obj: PDDeal) -> None:
        # A deal made outside Hermes can link a person whose own webhook was skipped because it had no organisation
        if not hermes_obj.contact_id and pd_obj.person_id:
            self.contacts_to_fetch.append((hermes_obj.id, pd_obj.person_id))

    async def _update_obj(self, hermes_obj: Deal, pd_obj: PDDeal) -> Deal:
        if pd_obj.title and pd_obj.title[:255] != hermes_obj.name:
            hermes_obj.name = pd_obj.title[:255]
        if pd_obj.status and pd_obj.status != hermes_obj.status:
            hermes_obj.status = pd_obj.status

        if pd_obj.user_id:
            new_admin_id = self.hermes_admin_ids[pd_obj.user_id]
            if hermes_obj.admin_id != new_admin_id:
                hermes_obj.admin_id = new_admin_id

        if pd_obj.pipeline_id:
            pipeline = self.db.exec(select(Pipeline).where(Pipeline.pd_pipeline_id == pd_obj.pipeline_id)).one_or_none()
            if pipeline and pipeline.id != hermes_obj.pipeline_id:
                hermes_obj.pipeline_id = pipeline.id

        if pd_obj.stage_id:
            stage = self.db.exec(select(Stage).where(Stage.pd_stage_id == pd_obj.stage_id)).one_or_none()
            if stage and stage.id != hermes_obj.stage_id:
                hermes_obj.stage_id = stage.id

        if pd_obj.org_id:
            company = self.db.exec(select(Company).where(Company.pd_org_id == pd_obj.org_id)).one()
            if company.id != hermes_obj.company_id:
                hermes_obj.company_id = company.id

        if pd_obj.person_id:
            contact = self.db.exec(select(Contact).where(Contact.pd_person_id == pd_obj.person_id)).one_or_none()
            if contact and contact.id != hermes_obj.contact_id:
                hermes_obj.contact_id = contact.id

        for f in self.custom_field_names:
            pd_val = getattr(pd_obj, f)
            if pd_val is not None and pd_val != getattr(hermes_obj, f):
                setattr(hermes_obj, f, pd_val)

        return hermes_obj


class PDPipelineProcessor(PipedriveObjProcessor):
    hermes_model = Pipeline
    pd_model = PDPipeline
    pd_id_field = 'pd_pipeline_id'

    async def delete_obj(self, pd_obj: PDPipeline):
        # Pipelines shouldn't be deleted from Hermes, just ignore deletion events
        logger.info(f'Ignoring deletion of pipeline {pd_obj.id} - pipelines are not deleted from Hermes')
        return None

    async def _add_obj(self, pd_obj: PDPipeline) -> Pipeline:
        # It's a new pipeline, we create it with the first stage we have.
        stage = self.db.exec(select(Stage)).first()
        return Pipeline(pd_pipeline_id=pd_obj.id, name=pd_obj.name, dft_entry_stage_id=stage.id)

    async def _update_obj(self, hermes_obj: Pipeline, pd_obj: PDPipeline) -> Pipeline:
        if pd_obj.name and hermes_obj.name != pd_obj.name[:255]:
            hermes_obj.name = pd_obj.name[:255]
        return hermes_obj


class PDStageProcessor(PipedriveObjProcessor):
    hermes_model = Stage
    pd_model = PDStage
    pd_id_field = 'pd_stage_id'

    async def delete_obj(self, pd_obj: PDStage):
        # Stages shouldn't be deleted from Hermes, just ignore deletion events
        logger.info(f'Ignoring deletion of stage {pd_obj.id} - stages are not deleted from Hermes')
        return None

    async def _add_obj(self, pd_obj: PDStage) -> Stage:
        return Stage(pd_stage_id=pd_obj.id, name=pd_obj.name)

    async def _update_obj(self, hermes_obj: Stage, pd_obj: PDStage) -> Stage:
        if pd_obj.name and hermes_obj.name != pd_obj.name[:255]:
            hermes_obj.name = pd_obj.name[:255]
        return hermes_obj


def find_or_create_pd_contact(db: DBSession, pd_person: Person, company: Company) -> tuple[Contact | None, str]:
    """
    Find or create the contact for a Pipedrive person linked to a deal of `company`, returning it with the outcome.

    The callbooker books into the newest contact with the booker's email, so a new contact is only created when no
    other contact has its email. Otherwise it would take over another company's bookings. Flushes, never commits.
    """
    contact = db.exec(select(Contact).where(Contact.pd_person_id == pd_person.id)).one_or_none()
    if contact:
        return contact, 'existing'
    if pd_person.hermes_id:
        # Hermes created this person, so its contact already exists
        return None, 'hermes_id'
    if pd_person.org_id and pd_person.org_id != company.pd_org_id:
        # Syncing the contact would move the person out of their own organisation in Pipedrive
        return None, 'other_org'
    if not pd_person.email:
        # The callbooker can't book a contact with no email, and without one the person can't be checked against
        # the existing contacts below
        return None, 'no_email'

    # Deleted contacts count too, because the callbooker's email lookup doesn't skip them
    same_email = db.exec(select(Contact).where(func.lower(Contact.email) == pd_person.email.lower())).all()
    if len(same_email) == 1:
        match = same_email[0]
        if match.company_id == company.id and not match.is_deleted and not match.pd_person_id:
            match.pd_person_id = pd_person.id
            db.add(match)
            db.flush()
            return match, 'adopted'
    if same_email:
        return None, 'email_elsewhere'

    contact = _contact_from_pd_person(pd_person, company.id)
    db.add(contact)
    db.flush()
    return contact, 'created'
