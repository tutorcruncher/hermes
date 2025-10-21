import logging

from sqlmodel import select

from app.core.database import DBSession
from app.main_app.models import Admin, Company, Contact, Deal, Pipeline, Stage
from app.pipedrive.models import Organisation, PDDeal, PDPipeline, PDStage, Person

logger = logging.getLogger('hermes.pipedrive')


async def process_organisation(org_data: Organisation | None, previous_org: Organisation | None, db: DBSession):
    """
    Process Pipedrive organization webhook.
    Updates Hermes Company from Pipedrive data.
    Does NOT sync back to TC2 (one-way: Pipedrive → Hermes only).
    """
    if not org_data:
        # Deletion event
        if previous_org and previous_org.hermes_id:
            statement = select(Company).where(Company.id == previous_org.hermes_id)
            company = db.exec(statement).first()
            if company:
                company.pd_org_id = None
                db.add(company)
                db.commit()
                logger.info(f'Cleared pd_org_id for company {company.id} (org deleted in Pipedrive)')
        return None

    # Get or create company by hermes_id
    # Handle merged entities (Pipedrive sends comma-separated IDs like "123, 456")
    hermes_id = org_data.hermes_id
    if hermes_id and isinstance(hermes_id, str) and ',' in str(hermes_id):
        # Take the first ID from comma-separated list (primary entity after merge)
        hermes_id = int(str(hermes_id).split(',')[0].strip())
        logger.info(f'Detected merged organization, using first hermes_id: {hermes_id}')

    if hermes_id:
        statement = select(Company).where(Company.id == hermes_id)
        company = db.exec(statement).first()
    elif org_data.id:
        statement = select(Company).where(Company.pd_org_id == org_data.id)
        company = db.exec(statement).first()
    else:
        logger.warning('Organization webhook has no hermes_id or id, cannot process')
        return None

    if not company:
        logger.warning(f'Company with hermes_id {hermes_id} not found, cannot update from Pipedrive')
        return None

    # Update company from Pipedrive data
    company.name = (org_data.name or company.name)[:255] if org_data.name else company.name
    company.pd_org_id = org_data.id
    company.country = org_data.address_country or company.country

    # Update owner if changed
    if org_data.owner_id:
        statement = select(Admin).where(Admin.pd_owner_id == org_data.owner_id)
        admin = db.exec(statement).first()
        if admin:
            company.sales_person_id = admin.id

    # Update custom fields from Pipedrive
    if org_data.paid_invoice_count is not None:
        company.paid_invoice_count = org_data.paid_invoice_count
    if org_data.tc2_status:
        company.tc2_status = org_data.tc2_status
    if org_data.website:
        company.website = org_data.website
    if org_data.price_plan:
        company.price_plan = org_data.price_plan
    if org_data.estimated_income:
        company.estimated_income = org_data.estimated_income
    if org_data.utm_source:
        company.utm_source = org_data.utm_source
    if org_data.utm_campaign:
        company.utm_campaign = org_data.utm_campaign
    if org_data.gclid:
        company.gclid = org_data.gclid
    if org_data.pay0_dt:
        company.pay0_dt = org_data.pay0_dt
    if org_data.pay1_dt:
        company.pay1_dt = org_data.pay1_dt
    if org_data.pay3_dt:
        company.pay3_dt = org_data.pay3_dt
    if org_data.gclid_expiry_dt:
        company.gclid_expiry_dt = org_data.gclid_expiry_dt
    if org_data.email_confirmed_dt:
        company.email_confirmed_dt = org_data.email_confirmed_dt
    if org_data.card_saved_dt:
        company.card_saved_dt = org_data.card_saved_dt

    # Update support/BDR persons if provided
    if org_data.support_person_id:
        company.support_person_id = org_data.support_person_id
    if org_data.bdr_person_id:
        company.bdr_person_id = org_data.bdr_person_id

    db.add(company)
    db.commit()
    db.refresh(company)

    logger.info(f'Updated company {company.id} from Pipedrive organization {org_data.id}')
    return company


async def process_person(person_data: Person | None, previous_person: Person | None, db: DBSession):
    """
    Process Pipedrive person webhook.
    Updates Hermes Contact from Pipedrive data.
    """
    if not person_data:
        # Deletion event
        if previous_person and previous_person.hermes_id:
            statement = select(Contact).where(Contact.id == previous_person.hermes_id)
            contact = db.exec(statement).first()
            if contact:
                contact.pd_person_id = None
                db.add(contact)
                db.commit()
                logger.info(f'Cleared pd_person_id for contact {contact.id} (person deleted in Pipedrive)')
        return None

    # Get contact by hermes_id or pd_person_id
    # Handle merged entities (Pipedrive sends comma-separated IDs like "123, 456")
    hermes_id = person_data.hermes_id
    if hermes_id and isinstance(hermes_id, str) and ',' in str(hermes_id):
        # Take the first ID from comma-separated list (primary entity after merge)
        hermes_id = int(str(hermes_id).split(',')[0].strip())
        logger.info(f'Detected merged person, using first hermes_id: {hermes_id}')

    if hermes_id:
        statement = select(Contact).where(Contact.id == hermes_id)
        contact = db.exec(statement).first()
    elif person_data.id:
        statement = select(Contact).where(Contact.pd_person_id == person_data.id)
        contact = db.exec(statement).first()
    else:
        logger.warning('Person webhook has no hermes_id or id, cannot process')
        return None

    if not contact:
        logger.warning(f'Contact with hermes_id {hermes_id} not found, cannot update from Pipedrive')
        return None

    # Update contact from Pipedrive data
    if person_data.name:
        # Parse name into first/last (truncate to 255 chars)
        name_parts = person_data.name[:255].split(' ', 1)
        if len(name_parts) > 1:
            contact.first_name = name_parts[0][:255]
            contact.last_name = name_parts[1][:255]
        else:
            contact.last_name = name_parts[0][:255]

    contact.pd_person_id = person_data.id

    # Handle email (Pipedrive sends as list)
    if person_data.email and len(person_data.email) > 0:
        contact.email = person_data.email[0]

    if person_data.phone:
        contact.phone = person_data.phone

    # Update organization link
    # Handle org_id (if person has multiple orgs in Pipedrive, use the first one)
    if person_data.org_id:
        org_id = person_data.org_id
        if isinstance(org_id, list) and len(org_id) > 0:
            org_id = org_id[0]
        statement = select(Company).where(Company.pd_org_id == org_id)
        company = db.exec(statement).first()
        if company:
            contact.company_id = company.id

    db.add(contact)
    db.commit()
    db.refresh(contact)

    logger.info(f'Updated contact {contact.id} from Pipedrive person {person_data.id}')
    return contact


async def process_deal(deal_data: PDDeal | None, previous_deal: PDDeal | None, db: DBSession):
    """
    Process Pipedrive deal webhook.
    Updates Hermes Deal from Pipedrive data.
    """
    if not deal_data:
        # Deletion event
        if previous_deal and previous_deal.hermes_id:
            statement = select(Deal).where(Deal.id == previous_deal.hermes_id)
            deal = db.exec(statement).first()
            if deal:
                deal.pd_deal_id = None
                deal.status = Deal.STATUS_DELETED
                db.add(deal)
                db.commit()
                logger.info(f'Marked deal {deal.id} as deleted (deleted in Pipedrive)')
        return None

    # Get deal by hermes_id or pd_deal_id
    # Handle merged entities (Pipedrive sends comma-separated IDs like "123, 456")
    hermes_id = deal_data.hermes_id
    if hermes_id and isinstance(hermes_id, str) and ',' in str(hermes_id):
        # Take the first ID from comma-separated list (primary entity after merge)
        hermes_id = int(str(hermes_id).split(',')[0].strip())
        logger.info(f'Detected merged deal, using first hermes_id: {hermes_id}')

    if hermes_id:
        statement = select(Deal).where(Deal.id == hermes_id)
        deal = db.exec(statement).first()
    elif deal_data.id:
        statement = select(Deal).where(Deal.pd_deal_id == deal_data.id)
        deal = db.exec(statement).first()
    else:
        logger.warning('Deal webhook has no hermes_id or id, cannot process')
        return None

    if not deal:
        logger.warning(f'Deal with hermes_id {hermes_id} not found, cannot update from Pipedrive')
        return None

    # Update deal from Pipedrive data
    deal.name = (deal_data.title or deal.name)[:255] if deal_data.title else deal.name
    deal.pd_deal_id = deal_data.id
    deal.status = deal_data.status or deal.status

    # Update relationships
    if deal_data.user_id:
        statement = select(Admin).where(Admin.pd_owner_id == deal_data.user_id)
        admin = db.exec(statement).first()
        if admin:
            deal.admin_id = admin.id

    if deal_data.org_id:
        statement = select(Company).where(Company.pd_org_id == deal_data.org_id)
        company = db.exec(statement).first()
        if company:
            deal.company_id = company.id

    if deal_data.person_id:
        statement = select(Contact).where(Contact.pd_person_id == deal_data.person_id)
        contact = db.exec(statement).first()
        if contact:
            deal.contact_id = contact.id

    if deal_data.pipeline_id:
        statement = select(Pipeline).where(Pipeline.pd_pipeline_id == deal_data.pipeline_id)
        pipeline = db.exec(statement).first()
        if pipeline:
            deal.pipeline_id = pipeline.id

    if deal_data.stage_id:
        statement = select(Stage).where(Stage.pd_stage_id == deal_data.stage_id)
        stage = db.exec(statement).first()
        if stage:
            deal.stage_id = stage.id

    db.add(deal)
    db.commit()
    db.refresh(deal)

    logger.info(f'Updated deal {deal.id} from Pipedrive deal {deal_data.id}')
    return deal


async def process_pipeline(pipeline_data: PDPipeline | None, previous_pipeline: PDPipeline | None, db: DBSession):
    """Process Pipedrive pipeline webhook - create/update Pipeline"""
    if not pipeline_data or not pipeline_data.active:
        # Ignore inactive or deleted pipelines
        return None

    statement = select(Pipeline).where(Pipeline.pd_pipeline_id == pipeline_data.id)
    pipeline = db.exec(statement).first()

    if pipeline:
        pipeline.name = pipeline_data.name or pipeline.name
        db.add(pipeline)
        db.commit()
        logger.info(f'Updated pipeline {pipeline.id}')
    else:
        pipeline = Pipeline(pd_pipeline_id=pipeline_data.id, name=pipeline_data.name)
        db.add(pipeline)
        db.commit()
        db.refresh(pipeline)
        logger.info(f'Created pipeline {pipeline.id} from Pipedrive')

    return pipeline


async def process_stage(stage_data: PDStage | None, previous_stage: PDStage | None, db: DBSession):
    """Process Pipedrive stage webhook - create/update Stage"""
    if not stage_data:
        return None

    statement = select(Stage).where(Stage.pd_stage_id == stage_data.id)
    stage = db.exec(statement).first()

    if stage:
        stage.name = stage_data.name or stage.name
        db.add(stage)
        db.commit()
        logger.info(f'Updated stage {stage.id}')
    else:
        stage = Stage(pd_stage_id=stage_data.id, name=stage_data.name)
        db.add(stage)
        db.commit()
        db.refresh(stage)
        logger.info(f'Created stage {stage.id} from Pipedrive')

    return stage
