from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import select
from starlette.requests import Request

from app.core.database import DBSession, get_db
from app.main_app.models import Admin, Company

router = APIRouter()

EU_COUNTRIES = [
    'MD',
    'BG',
    'DE',
    'AL',
    'ME',
    'ES',
    'SE',
    'AD',
    'MT',
    'CZ',
    'GB',
    'GI',
    'CY',
    'MC',
    'RU',
    'IE',
    'FR',
    'BY',
    'PT',
    'HR',
    'LI',
    'HU',
    'IS',
    'PL',
    'CH',
    'MK',
    'XK',
    'BE',
    'RS',
    'NL',
    'DK',
    'LU',
    'FO',
    'SI',
    'UA',
    'FI',
    'AT',
    'BA',
    'GR',
    'GG',
    'EE',
    'SM',
    'VA',
    'IT',
    'SK',
    'LT',
    'IM',
    'NO',
    'LV',
    'RO',
    'SJ',
    'JE',
    'AX',
]


def get_next_sales_person(admins: list[Admin], latest_sales_person_id: int | None) -> int:
    """
    Get the next sales person ID using round-robin logic.

    Args:
        admins: List of admin objects
        latest_sales_person_id: ID of the latest sales person

    Returns:
        ID of the next sales person
    """
    admin_ids = [a.id for a in admins]
    if not admin_ids:
        raise HTTPException(status_code=404, detail='No admins found')

    if latest_sales_person_id:
        try:
            next_person_id = admin_ids[admin_ids.index(latest_sales_person_id) + 1]
        except (IndexError, ValueError):
            next_person_id = admin_ids[0]
    else:
        next_person_id = admin_ids[0]

    return next_person_id


@router.get('/choose-roundrobin/sales/', name='choose-sales-person')
async def choose_sales_person(plan: str, country_code: str, db: DBSession = Depends(get_db)):
    """
    Choose which sales person should be assigned to a new company based on price plan and region.
    Uses round-robin logic ordered by admin ID.
    """
    # Filter by price plan
    if plan == Company.PP_PAYG:
        stmt = select(Admin).where(Admin.is_sales_person, Admin.sells_payg)
    elif plan == Company.PP_STARTUP:
        stmt = select(Admin).where(Admin.is_sales_person, Admin.sells_startup)
    elif plan == Company.PP_ENTERPRISE:
        stmt = select(Admin).where(Admin.is_sales_person, Admin.sells_enterprise)
    else:
        raise HTTPException(status_code=422, detail='Price plan must be one of "payg", "startup", "enterprise"')

    admins = db.exec(stmt.order_by(Admin.id)).all()

    # Filter by region
    region = country_code or 'GB'
    regional_admins = []

    if region == 'US':
        regional_admins = [a for a in admins if a.sells_us]
    elif region == 'GB':
        regional_admins = [a for a in admins if a.sells_gb]
    elif region == 'AU':
        regional_admins = [a for a in admins if a.sells_au]
    elif region == 'CA':
        regional_admins = [a for a in admins if a.sells_ca]
    elif region in EU_COUNTRIES:
        regional_admins = [a for a in admins if a.sells_eu]
    else:
        regional_admins = [a for a in admins if a.sells_row]

    # Get latest company to determine round-robin position
    latest_company = db.exec(
        select(Company)
        .where(Company.price_plan == plan, Company.sales_person_id.isnot(None))
        .order_by(Company.created.desc())
    ).first()
    latest_sales_person = latest_company.sales_person_id if latest_company else None

    # Choose next person
    if regional_admins:
        next_sales_person_id = get_next_sales_person(regional_admins, latest_sales_person)
    else:
        next_sales_person_id = get_next_sales_person(admins, latest_sales_person)

    next_admin = db.get(Admin, next_sales_person_id)
    if not next_admin:
        raise HTTPException(status_code=404, detail='Admin not found')

    return {
        'id': next_admin.id,
        'first_name': next_admin.first_name,
        'last_name': next_admin.last_name,
        'email': next_admin.email,
        'tc2_admin_id': next_admin.tc2_admin_id,
        'pd_owner_id': next_admin.pd_owner_id,
    }


@router.get('/choose-roundrobin/support/', name='choose-support-person')
async def choose_support_person(db: DBSession = Depends(get_db)):
    """
    Choose which support person should be assigned to a new company.
    Uses round-robin logic ordered by admin ID.
    """
    stmt = select(Admin).where(Admin.is_support_person).order_by(Admin.id)
    admins = db.exec(stmt).all()

    if not admins:
        raise HTTPException(status_code=404, detail='No support admins found')

    # Get latest company to determine round-robin position
    latest_company = db.exec(
        select(Company).where(Company.support_person_id.isnot(None)).order_by(Company.created.desc())
    ).one_or_none()

    if latest_company:
        latest_support_person = latest_company.support_person_id
        admin_ids = [a.id for a in admins]
        try:
            next_support_person = admin_ids[admin_ids.index(latest_support_person) + 1]
        except (IndexError, ValueError):
            next_support_person = admin_ids[0]
    else:
        next_support_person = admins[0].id

    next_admin = db.get(Admin, next_support_person)

    return {
        'id': next_admin.id,
        'first_name': next_admin.first_name,
        'last_name': next_admin.last_name,
        'email': next_admin.email,
        'tc2_admin_id': next_admin.tc2_admin_id,
        'pd_owner_id': next_admin.pd_owner_id,
    }


@router.get('/loc/', name='get-country-code')
def get_country(cf_ipcountry: str = Header(None)):
    """Get the country code for the current user from Cloudflare header"""
    return {'country_code': cf_ipcountry or 'GB'}


@router.get('/companies/', name='get-companies')
async def get_companies(request: Request, db: DBSession = Depends(get_db)):
    """
    Get the first 10 companies by query parameters.
    Example: /companies/?name=Test&country=GB
    """
    query_params = {k: v for k, v in request.query_params.items() if v is not None}
    if not query_params:
        raise HTTPException(status_code=422, detail='Must provide at least one query parameter')

    # Build query dynamically from params
    stmt = select(Company)
    for key, value in query_params.items():
        if hasattr(Company, key):
            stmt = stmt.where(getattr(Company, key) == value)

    companies = db.exec(stmt.order_by(Company.name).limit(10)).all()

    return [
        {
            'id': c.id,
            'name': c.name,
            'pd_org_id': c.pd_org_id,
            'tc2_cligency_id': c.tc2_cligency_id,
            'tc2_agency_id': c.tc2_agency_id,
            'country': c.country,
            'price_plan': c.price_plan,
        }
        for c in companies
    ]
