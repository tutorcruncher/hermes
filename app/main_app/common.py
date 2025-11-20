import logging

from sqlmodel import select

from app.core.database import DBSession
from app.exceptions import DealCreationError
from app.main_app.models import Company, Config, Contact, Deal, Pipeline, Stage

logger = logging.getLogger('hermes.main_app')


async def get_or_create_deal(company: Company, contact: Contact, db: DBSession, **filters):
    """
    Get or create a deal for a company.

    Args:
        company: Company to get/create deal for
        contact: Contact for the deal (can be None)
        db: Database session
        **filters: Additional filters (e.g., status=Deal.STATUS_OPEN)

    Returns:
        Existing or newly created Deal
    """
    query = select(Deal).where(Deal.company_id == company.id)
    for key, value in filters.items():
        query = query.where(getattr(Deal, key) == value)

    existing_deal = db.exec(query).first()

    if existing_deal:
        logger.info(f'Found existing deal {existing_deal.id} (status={existing_deal.status}) for company {company.id}')
        return existing_deal

    config = db.exec(select(Config)).first()
    if not config:
        logger.error('No config found, cannot create deal')
        raise DealCreationError('Config not found')

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
            raise DealCreationError(f'Unknown price plan: {company.price_plan}')

    pipeline = db.exec(select(Pipeline).where(Pipeline.id == pipeline_id)).first()
    if not pipeline:
        logger.error(f'Pipeline {pipeline_id} not found')
        raise DealCreationError(f'Pipeline {pipeline_id} not found')

    if not pipeline.dft_entry_stage_id:
        logger.error(f'Pipeline {pipeline_id} has no default entry stage')
        raise DealCreationError(f'Pipeline {pipeline_id} has no default entry stage')

    # Verify stage exists
    stage = db.exec(select(Stage).where(Stage.id == pipeline.dft_entry_stage_id)).first()
    if not stage:
        logger.error(f'Stage {pipeline.dft_entry_stage_id} not found for pipeline {pipeline_id}')
        raise DealCreationError(f'Stage {pipeline.dft_entry_stage_id} not found')

    deal = Deal(
        company_id=company.id,
        contact_id=contact.id if contact else None,
        name=company.name,
        pipeline_id=pipeline.id,
        admin_id=company.sales_person_id,
        stage_id=pipeline.dft_entry_stage_id,
        status=Deal.STATUS_OPEN,
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
