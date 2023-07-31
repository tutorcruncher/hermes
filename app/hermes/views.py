from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError

from app.models import Company, Admin

main_router = APIRouter()


@main_router.get('/choose-sales-person/', name='Decide which sales person to assign to a new sale')
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
        latest_salesperson = latest_company.sales_person_id
        try:
            next_sales_person = admin_ids[admin_ids.index(latest_salesperson) + 1]
        except (IndexError, ValueError):
            next_sales_person = admin_ids[0]
    else:
        next_sales_person = admin_ids[0]
    schema = Admin.pydantic_schema()
    return await schema.from_tortoise_orm(admins[next_sales_person])
