from fastapi import APIRouter, Header
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.requests import Request

from app.models import Admin, Company

main_router = APIRouter()

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
# EU Countries:
# MD: Moldova, BG: Bulgaria, DE: Germany, AL: Albania, ME: Montenegro, ES: Spain, SE: Sweden, AD: Andorra, MT: Malta,
# CZ: Czech Republic, GB: United Kingdom, GI: Gibraltar, CY: Cyprus, MC: Monaco, RU: Russia, IE: Ireland, FR: France,
# BY: Belarus, PT: Portugal, HR: Croatia, LI: Liechtenstein, HU: Hungary, IS: Iceland, PL: Poland, CH: Switzerland,
# MK: North Macedonia, XK: Kosovo, BE: Belgium, RS: Serbia, NL: Netherlands, DK: Denmark, LU: Luxembourg,
# FO: Faroe Islands, SI: Slovenia, UA: Ukraine, FI: Finland, AT: Austria, BA: Bosnia and Herzegovina, GR: Greece,
# GG: Guernsey, EE: Estonia, SM: San Marino, VA: Vatican City, IT: Italy, SK: Slovakia, LT: Lithuania,
# IM: Isle of Man, NO: Norway, LV: Latvia, RO: Romania, SJ: Svalbard and Jan Mayen, JE: Jersey, AX: Åland Islands


@main_router.get('/choose-roundrobin/sales/', name='Decide which sales person to assign to a new signup')
async def choose_sales_person(plan: str, cf_ipcountry: str = Header(None)) -> Admin.pydantic_schema():
    """
    Chooses which sales person should be assigned to a new company if it were on a certain price plan and region. Uses simple
    round robin logic where the order of admins is decided by their ID.
    """
    if plan == Company.PP_PAYG:
        admins = Admin.filter(sells_payg=True)
    elif plan == Company.PP_STARTUP:
        admins = Admin.filter(sells_startup=True)
    elif plan == Company.PP_ENTERPRISE:
        admins = Admin.filter(sells_enterprise=True)
    else:
        raise RequestValidationError('Price plan must be one of "payg,startup,enterprise"')

    region = cf_ipcountry or 'GB'

    if region == 'US':
        regional_admins = admins.filter(sells_us=True)
    elif region == 'GB':
        regional_admins = admins.filter(sells_gb=True)
    elif region == 'AU':
        regional_admins = admins.filter(sells_au=True)
    elif region == 'CA':
        regional_admins = admins.filter(sells_ca=True)
    elif region in EU_COUNTRIES:
        regional_admins = admins.filter(sells_eu=True)
    else:
        regional_admins = admins.filter(sells_row=True)

    admins = {a.id: a async for a in admins.filter(is_sales_person=True).order_by('id')}
    admins_ids = list(admins.keys())

    regional_admins = {a.id: a async for a in regional_admins.filter(is_sales_person=True).order_by('id')}
    regional_admins_ids = list(regional_admins.keys())
    latest_company = await Company.filter(price_plan=plan, sales_person_id__isnull=False).order_by('-created').first()
    if regional_admins:
        if latest_company:
            latest_sales_person = latest_company.sales_person_id
            try:
                next_sales_person = regional_admins_ids[regional_admins_ids.index(latest_sales_person) + 1]
            except (IndexError, ValueError):
                next_sales_person = regional_admins_ids[0]
        else:
            next_sales_person = regional_admins_ids[0]
    else:
        if latest_company:
            latest_sales_person = latest_company.sales_person_id
            try:
                next_sales_person = admins_ids[admins_ids.index(latest_sales_person) + 1]
            except (IndexError, ValueError):
                next_sales_person = admins_ids[0]
        else:
            next_sales_person = admins_ids[0]

    schema = Admin.pydantic_schema()
    return await schema.from_tortoise_orm(admins[next_sales_person])


@main_router.get('/choose-roundrobin/support/', name='Decide which support person to assign to a new signup')
async def choose_support_person() -> Admin.pydantic_schema():
    """
    Chooses which support person should be assigned to a new company. Uses simple round robin logic where the order of
    admins is decided by their ID.
    """
    admins = {a.id: a async for a in Admin.filter(is_support_person=True).order_by('id')}
    admin_ids = list(admins.keys())
    latest_company = await Company.filter(support_person_id__isnull=False).order_by('-created').first()
    if latest_company:
        latest_support_person = latest_company.support_person_id
        try:
            next_support_person = admin_ids[admin_ids.index(latest_support_person) + 1]
        except (IndexError, ValueError):
            next_support_person = admin_ids[0]
    else:
        next_support_person = admin_ids[0]
    schema = Admin.pydantic_schema()
    return await schema.from_tortoise_orm(admins[next_support_person])


@main_router.get('/loc/', name='Get the country code for the current user')
def get_country(cf_ipcountry: str = Header(None)) -> dict:
    return {'country_code': cf_ipcountry or 'GB'}


@main_router.get('/companies/', name='Get a list of companies')
async def get_companies(request: Request) -> list[dict]:
    """
    Get the first 10 companies by a list of kwargs.
    """
    query_params = {k: v for k, v in request.query_params.items() if v is not None}
    if not query_params:
        raise HTTPException(422, 'Must provide at least one param')
    companies = await Company.filter(**query_params).order_by('name').limit(10)
    schema = Company.pydantic_schema()
    return [(await schema.from_tortoise_orm(c)).model_dump() for c in companies]
