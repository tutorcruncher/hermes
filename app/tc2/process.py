import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.core.config import settings
from app.core.database import DBSession
from app.main_app.models import Admin, Company, Config, Contact, Deal, Pipeline
from app.tc2.api import get_client
from app.tc2.models import TCClient, TCRecipient

logger = logging.getLogger('hermes.tc2')

COMPANY_SYNCABLE_FIELDS = (
    # can simply override by setting the config vars
    # example 'pay0_dt,card_saved_dt'
    set(settings.company_syncable_fields.split(','))
    if settings.company_syncable_fields
    else {
        'pay0_dt',
        'pay1_dt',
        'pay3_dt',
        'card_saved_dt',
        'price_plan',
        'email_confirmed_dt',
        'gclid',
        'gclid_expiry_dt',
        'tc2_status',
        'narc',
        'paid_invoice_count',
    }
)


def _update_syncable_fields(company: Company, tc_client: TCClient):
    """
    Update only syncable fields for an existing company.
    This prevents the 3-hourly TC2 webhook job from overwriting fields that may have been
    updated in Pipedrive. Only fields in COMPANY_SYNCABLE_FIELDS will be updated.
    """
    for field in COMPANY_SYNCABLE_FIELDS:
        tc2_field = 'status' if field == 'tc2_status' else field
        value = getattr(tc_client.meta_agency, tc2_field)
        setattr(company, field, value)


def _close_open_deals_if_narc_or_terminated(company: Company, db: DBSession):
    """
    Close all open deals for a company if it's marked as NARC or terminated.
    """
    if company.narc or company.tc2_status == 'terminated':
        open_deals = db.exec(select(Deal).where(Deal.company_id == company.id, Deal.status == Deal.STATUS_OPEN)).all()
        for deal in open_deals:
            deal.status = Deal.STATUS_LOST
            db.add(deal)
        if open_deals:
            db.commit()
            logger.info(
                f'Closed {len(open_deals)} open deals for company {company.id} (narc={company.narc}, status={company.tc2_status})'
            )


async def get_or_create_company_from_tc2(tc2_cligency_id: int, db: DBSession) -> Company:
    """
    Get or create a company from TC2 data.
    Fetches full client data from TC2 API.
    """
    company = db.exec(select(Company).where(Company.tc2_cligency_id == tc2_cligency_id)).one_or_none()

    if company:
        return company

    # Fetch from TC2 API without holding DB session
    tc_client_data = await get_client(tc2_cligency_id)
    tc_client = TCClient(**tc_client_data)

    # Now process with DB
    company = await process_tc_client(tc_client, db)

    return company


async def process_tc_client(tc_client: TCClient, db: DBSession, create_deal: bool = True) -> Company:
    """
    Process TC2 client data and create/update Company and Contacts.

    Args:
        tc_client: Validated TC2 client data
        db: Database session
        create_deal: Whether to create a deal (default True, False for support calls)

    Returns:
        Created or updated Company
    """
    # Get or create company
    company = db.exec(select(Company).where(Company.tc2_cligency_id == tc_client.id)).one_or_none()

    # Get admin relationships
    sales_person = None
    support_person = None
    bdr_person = None

    logger.info(
        f'Processing client {tc_client.id}: sales_person_id={tc_client.sales_person_id}, support_person_id={tc_client.associated_admin_id}, bdr_person_id={tc_client.bdr_person_id}'
    )

    if tc_client.sales_person_id:
        sales_person = db.exec(select(Admin).where(Admin.tc2_admin_id == tc_client.sales_person_id)).one_or_none()

    if tc_client.associated_admin_id:
        support_person = db.exec(select(Admin).where(Admin.tc2_admin_id == tc_client.associated_admin_id)).one_or_none()

    if tc_client.bdr_person_id:
        bdr_person = db.exec(select(Admin).where(Admin.tc2_admin_id == tc_client.bdr_person_id)).one_or_none()
        if not bdr_person:
            logger.warning(f'BDR person {tc_client.bdr_person_id} not found for client {tc_client.id}')
    else:
        logger.info(f'Client {tc_client.id} has no bdr_person_id in TC2 data')

    if not sales_person:
        logger.error(f'Sales person {tc_client.sales_person_id} not found for client {tc_client.id}')
        # You may want to handle this differently - perhaps assign to a default admin
        return None

    # Get extra attributes and map to company fields
    extra_attrs_dict = {}
    if tc_client.extra_attrs:
        for attr in tc_client.extra_attrs:
            extra_attrs_dict[attr.machine_name] = attr.value

    if company:
        _update_syncable_fields(company, tc_client)
        _close_open_deals_if_narc_or_terminated(company, db)

        # handle extra attrs
        if 'utm_source' in extra_attrs_dict:
            company.utm_source = extra_attrs_dict['utm_source']
        if 'utm_campaign' in extra_attrs_dict:
            company.utm_campaign = extra_attrs_dict['utm_campaign']
        if 'signup_questionnaire' in extra_attrs_dict:
            company.signup_questionnaire = extra_attrs_dict['signup_questionnaire']
        if 'estimated_monthly_income' in extra_attrs_dict:
            company.estimated_income = extra_attrs_dict['estimated_monthly_income']

        db.add(company)
        db.commit()
        db.refresh(company)
    else:
        # Create new company
        company = Company(
            name=tc_client.meta_agency.name[:255],
            tc2_agency_id=tc_client.meta_agency.id,
            tc2_cligency_id=tc_client.id,
            tc2_status=tc_client.meta_agency.status,
            country=tc_client.meta_agency.country,
            website=tc_client.meta_agency.website,
            paid_invoice_count=tc_client.meta_agency.paid_invoice_count,
            price_plan=tc_client.meta_agency.price_plan,
            narc=tc_client.meta_agency.narc or False,
            pay0_dt=tc_client.meta_agency.pay0_dt,
            pay1_dt=tc_client.meta_agency.pay1_dt,
            pay3_dt=tc_client.meta_agency.pay3_dt,
            card_saved_dt=tc_client.meta_agency.card_saved_dt,
            email_confirmed_dt=tc_client.meta_agency.email_confirmed_dt,
            gclid=tc_client.meta_agency.gclid,
            gclid_expiry_dt=tc_client.meta_agency.gclid_expiry_dt,
            utm_source=extra_attrs_dict.get('utm_source'),
            utm_campaign=extra_attrs_dict.get('utm_campaign'),
            signup_questionnaire=extra_attrs_dict.get('signup_questionnaire'),
            estimated_income=extra_attrs_dict.get('estimated_monthly_income'),
            created=tc_client.meta_agency.created,
            sales_person_id=sales_person.id,
            support_person_id=support_person.id if support_person else None,
            bdr_person_id=bdr_person.id if bdr_person else None,
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        # should be done only once during company creation
        primary_contact = None
        for i, recipient in enumerate(tc_client.paid_recipients):
            contact = await process_tc_recipient(recipient, company, db, tc_client.user.email, tc_client.user.phone)
            if i == 0:
                primary_contact = contact

    # Create deal if requested and conditions are met
    if create_deal and not company.narc:
        # Determine if we should create a deal based on company status and age
        should_create_deal = (
            tc_client.meta_agency.status in [Company.STATUS_PENDING_EMAIL_CONF, Company.STATUS_TRIAL]
            and tc_client.meta_agency.created > datetime.now(timezone.utc) - timedelta(days=90)
            and tc_client.meta_agency.paid_invoice_count == 0
            and tc_client.sales_person_id is not None
        )

        if should_create_deal:
            try:
                deal = await get_or_create_deal(company, primary_contact, db)
                logger.info(f'Deal {deal.id} created/found for company {company.id}')
            except Exception as e:
                logger.error(f'Failed to create deal for company {company.id}: {e}')

    return company


async def process_tc_recipient(
    recipient: TCRecipient, company: Company, db: DBSession, user_email: str = None, user_phone: str = None
) -> Contact:
    """
    Process TC2 recipient (contact) data.

    Args:
        recipient: TC2 recipient data
        company: Company the contact belongs to
        db: Database session
        user_email: Fallback email from TC2 user if recipient has none
        user_phone: Fallback phone from TC2 user if recipient has none

    Returns:
        Created or updated Contact
    """
    contact = db.exec(select(Contact).where(Contact.tc2_sr_id == recipient.id)).one_or_none()

    # Use recipient email/phone if available, otherwise fallback to user email/phone
    contact_email = recipient.email or user_email
    contact_phone = user_phone  # Recipients don't have phone, always use user phone

    if not contact:
        # Create new contact
        contact = Contact(
            tc2_sr_id=recipient.id,
            first_name=recipient.first_name[:255] if recipient.first_name else None,
            last_name=recipient.last_name[:255] if recipient.last_name else None,
            email=contact_email[:255] if contact_email else None,
            phone=contact_phone[:255] if contact_phone else None,
            country=company.country,
            company_id=company.id,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

    # we return contact back without updating it if it already exists

    return contact


async def get_or_create_deal(company: Company, contact: Contact | None, db: DBSession) -> Deal:
    """
    Get or create an Open deal for a company.

    Args:
        company: Company to create deal for
        contact: Optional primary contact for the deal
        db: Database session

    Returns:
        Created or existing Deal
    """
    # Check if there's already an open deal for this company
    existing_deal = db.exec(select(Deal).where(Deal.company_id == company.id, Deal.status == Deal.STATUS_OPEN)).first()

    if existing_deal:
        logger.info(f'Found existing open deal {existing_deal.id} for company {company.id}')
        return existing_deal

    # Get config to determine pipeline
    config = db.exec(select(Config)).first()
    if not config:
        logger.error('No config found, cannot create deal')
        raise ValueError('Config not found')

    # Determine pipeline based on price plan
    pipeline_id = None
    match company.price_plan:
        case Company.PP_PAYG:
            pipeline_id = config.payg_pipeline_id
        case Company.PP_STARTUP:
            pipeline_id = config.startup_pipeline_id
        case Company.PP_ENTERPRISE:
            pipeline_id = config.enterprise_pipeline_id
        case _:
            logger.error(f'Unknown price plan {company.price_plan} for company {company.id}')
            raise ValueError(f'Unknown price plan {company.price_plan}')

    # Get the pipeline to get default entry stage
    pipeline = db.exec(select(Pipeline).where(Pipeline.id == pipeline_id)).first()
    if not pipeline:
        logger.error(f'Pipeline {pipeline_id} not found')
        raise ValueError(f'Pipeline {pipeline_id} not found')

    if not pipeline.dft_entry_stage_id:
        logger.error(f'Pipeline {pipeline_id} has no default entry stage')
        raise ValueError(f'Pipeline {pipeline_id} has no default entry stage')

    # Create the deal
    deal = Deal(
        company_id=company.id,
        contact_id=contact.id if contact else None,
        name=company.name,
        pipeline_id=pipeline.id,
        admin_id=company.sales_person_id,
        stage_id=pipeline.dft_entry_stage_id,
        status=Deal.STATUS_OPEN,
        # Copy company fields to deal
        support_person_id=company.support_person_id,
        bdr_person_id=company.bdr_person_id,
        paid_invoice_count=company.paid_invoice_count,
        tc2_status=company.tc2_status,
        website=company.website,
        price_plan=company.price_plan,
        estimated_income=company.estimated_income,
        signup_questionnaire=company.signup_questionnaire,
        utm_campaign=company.utm_campaign,
        utm_source=company.utm_source,
    )

    db.add(deal)
    db.commit()
    db.refresh(deal)

    logger.info(f'Created new deal {deal.id} for company {company.id} in pipeline {pipeline.name}')
    return deal
