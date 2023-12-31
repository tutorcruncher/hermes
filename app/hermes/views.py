from fastapi import APIRouter, Header
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.requests import Request

from app.models import Admin, Company

main_router = APIRouter()


@main_router.get('/choose-roundrobin/sales/', name='Decide which sales person to assign to a new signup')
async def choose_sales_person(plan: str) -> Admin.pydantic_schema():
    """
    Chooses which sales person should be assigned to a new company if it were on a certain price plan. Uses simple
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
    admins = {a.id: a async for a in admins.filter(is_sales_person=True).order_by('id')}
    admin_ids = list(admins.keys())
    latest_company = await Company.filter(price_plan=plan, sales_person_id__isnull=False).order_by('-created').first()
    if latest_company:
        latest_sales_person = latest_company.sales_person_id
        try:
            next_sales_person = admin_ids[admin_ids.index(latest_sales_person) + 1]
        except (IndexError, ValueError):
            next_sales_person = admin_ids[0]
    else:
        next_sales_person = admin_ids[0]
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
